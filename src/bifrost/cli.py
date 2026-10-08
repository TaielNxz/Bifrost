import argparse
import tempfile
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from botocore.exceptions import BotoCoreError, ClientError

from .archives import create_zip, extract_zip, verify_zip
from .config import Settings, load_settings
from .local_state import check_base_destination, read_base_version, save_base_version
from .local_worlds import (
    check_copy_destination,
    check_install_destination,
    find_world,
    install_staged_world,
    list_worlds,
    save_world_copy,
)
from .locks import active_lock_value, build_lock, ensure_restore_unlocked
from .manifests import build_manifest, next_version, parse_iso_datetime, validate_manifest
from .models import LocalBase, Manifest, World, WorldLock
from .paths import version_upload_zip_key
from .remote_state import (
    StateSnapshot,
    commit_world_state,
    read_world_state,
    updated_world_state,
)
from .restoration import restore_world_version
from .storage import ConcurrentUpdateError, R2Storage
from .versions import (
    MAX_PREVIOUS_REMOTE_VERSIONS,
    archive_current_version,
    list_previous_versions,
    prune_remote_versions,
    read_version_manifest,
    record_published_version,
)
from .world_names import (
    InvalidWorldNameError,
    WorldNameConflictError,
    WorldNameIssue,
    world_name_key,
)

T = TypeVar("T")


# ======================================================================================= #
# Formato y presentación
# ======================================================================================= #

def _format_size(size_bytes: int) -> str:
    """Formatea una cantidad de bytes con una unidad legible."""
    size = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("Unidad de tamaño inalcanzable")


def _show_world_name_errors(errors: Sequence[WorldNameIssue]) -> None:
    """Muestra los motivos por los que algunos mundos quedaron fuera del listado."""
    for error in errors:
        print(f"[BLOQUEADO] {error}")


def show_world_comparison(world: World, manifest: Manifest) -> tuple[datetime, datetime]:
    """Muestra la fecha de subida remota y la de modificación local de un mundo.

    Devuelve ambas fechas para compararlas.
    """
    remote_date = parse_iso_datetime(manifest["uploaded_at"])
    local_date = world.modified_at.astimezone()
    print("\n[INFO] Comparando versiones...")
    print(
        f"       Remoto: versión {manifest['version']}, "
        f"fecha {remote_date:%Y-%m-%d %H:%M} UTC, "
        f"subido por {manifest['uploaded_by']}"
    )
    print(f"       Local:  modificado {local_date:%Y-%m-%d %H:%M %Z}")
    return remote_date, local_date


# ======================================================================================= #
# Interacción con el usuario
# ======================================================================================= #

def confirm(question: str) -> bool:
    """Pregunta al usuario y devuelve True si responde 's' (sí)."""
    return input(f"{question} [s/n]: ").strip().lower() == "s"


def choose(items: Sequence[T], formatter: Callable[[T], str], prompt: str = "Elegí un mundo") -> T | None:
    """Muestra una lista y devuelve el elemento elegido.

    Devuelve None si el usuario cancela o ingresa una opción inválida.
    """
    # Presenta las opciones numeradas y la posibilidad de volver.
    for index, item in enumerate(items, 1):
        print(f"  {index}) {formatter(item)}")
    print("  0) Volver")

    answer = input(f"\n{prompt}: ").strip()

    # Cancelación: vuelve sin seleccionar un elemento.
    if answer == "0":
        return None

    # Valida el número elegido antes de devolver el elemento.
    try:
        index = int(answer) - 1
        if index < 0:
            raise IndexError
        return items[index]
    except (ValueError, IndexError):
        # Opción inválida: informa el problema y vuelve sin una selección.
        print("\nOpción inválida.")
        return None


# ======================================================================================= #
# Consulta de mundos remotos
# ======================================================================================= #

def _remote_world_names(storage: R2Storage) -> list[str]:
    """Consulta nombres remotos utilizables e informa los rechazos sin leer sus estados."""
    errors: list[WorldNameIssue] = []
    names = storage.list_worlds(errors=errors)
    _show_world_name_errors(errors)
    return names


def _remote_worlds(storage: R2Storage) -> list[tuple[str, Manifest, StateSnapshot]]:
    """Lista los mundos remotos con manifest e incluye el estado leído de cada uno.

    Omite las entradas cuya metadata no puede interpretar o presentar.
    """
    worlds = []
    for name in _remote_world_names(storage):
        try:
            snapshot = read_world_state(storage, name)
            manifest = snapshot.value["manifest"]
            if manifest is not None:
                # Revisa también los campos usados al presentar la selección.
                parse_iso_datetime(manifest["uploaded_at"])
                _format_size(manifest["size"])
                manifest["uploaded_by"]
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            # Error de metadata: informa la exclusión y continúa con los demás mundos.
            print(f"[BLOQUEADO] Mundo remoto {name!r}: {error}")
            continue

        # Omite los mundos sin una versión publicada disponible para descargar.
        if manifest is not None:
            worlds.append((name, manifest, snapshot))
    return worlds


def _check_remote_name(storage: R2Storage, world_name: str) -> None:
    """Bloquea una subida si su nombre coincide con otras identidades remotas."""
    # Recoge los nombres utilizables y muestra los motivos de exclusión del listado.
    key = world_name_key(world_name)
    errors: list[WorldNameIssue] = []
    names = storage.list_worlds(errors=errors)
    _show_world_name_errors(errors)

    # Conflicto previo: bloquea el mundo solicitado si pertenece a un grupo ambiguo.
    for error in errors:
        if isinstance(error, WorldNameConflictError) and world_name_key(error.names[0]) == key:
            raise error

    # Conflicto de identidad: tampoco admite un nombre remoto único con otra escritura.
    for name in names:
        if world_name_key(name) == key and name != world_name:
            raise WorldNameConflictError([world_name, name])


# ======================================================================================= #
# Validaciones y confirmaciones
# ======================================================================================= #

def allow_push(
    world: World, remote_manifest: Manifest | None, local_base: LocalBase | None
) -> bool:
    """Comprueba que la base local permita publicar sobre la versión remota.

    Admite una primera subida y pide confirmación si la fecha remota es posterior.
    """
    # Caso 1: No hay manifest remoto; distingue una primera subida de una base previa.
    if remote_manifest is None:
        # Caso 1.1: Hay una base local sin manifest remoto; bloquea el reinicio del historial.
        if local_base is not None:
            print(
                f"\n[CONFLICTO] '{world.name}' parte de la versión "
                f"{local_base['version']}, pero el manifest remoto no está disponible."
            )
            print("    La subida fue bloqueada para evitar reiniciar el historial remoto.")
            return False

        # Caso 1.2: Tampoco hay base local; permite una primera publicación.
        print(f"\n[INFO] No hay versión previa de '{world.name}' en la nube.")
        return True

    # Caso 2: Hay manifest remoto sin base local; bloquea una subida sin origen registrado.
    if local_base is None:
        print(f"\n[CONFLICTO] No hay una versión base registrada para '{world.name}'.")
        print(
            f"    La nube contiene la versión {remote_manifest['version']} "
            f"subida por {remote_manifest['uploaded_by']}."
        )
        print("    Descargá la versión vigente antes de iniciar una nueva sesión.")
        print("    La subida fue bloqueada para evitar sobrescribir progreso.")
        return False

    # Compara versión y hash para comprobar el origen del mundo local.
    remote_version = remote_manifest["version"]
    remote_sha256 = remote_manifest["sha256"].lower()

    # Caso 3: La versión o el hash de la base difieren; bloquea la publicación.
    if local_base["version"] != remote_version or local_base["sha256"] != remote_sha256:
        print(f"\n[CONFLICTO] '{world.name}' no parte de la versión remota vigente.")
        print(
            f"    Base local: versión {local_base['version']}, "
            f"SHA-256 {local_base['sha256'][:12]}..."
        )
        print(
            f"    Remoto:     versión {remote_version}, "
            f"SHA-256 {remote_sha256[:12]}..., "
            f"subido por {remote_manifest['uploaded_by']}"
        )
        print("    La subida fue bloqueada para preservar ambas versiones.")
        return False

    # Con la base coincidente, usa las fechas como una advertencia adicional de frescura.
    remote_date, local_date = show_world_comparison(world, remote_manifest)

    # Caso 4: La fecha remota es posterior a la local; requiere confirmación.
    if remote_date > local_date:
        print("\n[!] La versión remota es MÁS NUEVA que tu versión local.")
        print("    Si subís ahora, VAS A SOBRESCRIBIR ese progreso.")
        return confirm("\n¿Continuar igual?")

    # Caso 5: La fecha local es igual o posterior a la remota; permite continuar.
    print("\n[OK] Tu versión local es igual o más nueva que la remota.")
    return True


def allow_pull(settings: Settings, world_name: str, manifest: Manifest) -> bool:
    """Comprueba si se puede reemplazar el mundo local con la versión remota.

    Pide confirmación cuando la fecha local es posterior a la remota.
    """
    try:
        local_world = find_world(settings.worlds_path, world_name)
    except (InvalidWorldNameError, WorldNameConflictError) as error:
        # Un destino ambiguo no equivale a un mundo ausente y no permite adquirir el lock.
        print(f"\n[BLOQUEADO] {error}")
        return False

    # Caso 1: No existe el mundo local; permite crearlo.
    if local_world is None:
        print(f"\n[INFO] No tenés '{world_name}' localmente. Se va a crear.")
        return True

    remote_date, local_date = show_world_comparison(local_world, manifest)

    # Caso 2: La fecha local es posterior a la remota; requiere confirmar el reemplazo.
    if local_date > remote_date:
        print("\n[!] Tu versión local es MÁS NUEVA que la de la nube.")
        print("    Si descargás, VAS A PERDER los cambios locales.")
        return confirm("\n¿Continuar igual?")

    # Caso 3: La fecha remota es igual o posterior a la local; permite continuar.
    print("\n[OK] La versión remota es igual o más nueva. Seguro bajar.")
    return True


def _allow_lock_override(
    world_lock: WorldLock | None, world_name: str, player: str
) -> bool:
    """Comprueba si se puede adquirir el lock de un mundo.

    Pide confirmación para reemplazar un lock activo de otro jugador.
    """
    # Caso 1: No hay lock activo; permite continuar.
    if world_lock is None:
        return True

    # Caso 2: El lock pertenece al jugador actual; permite continuar.
    if world_lock["player"] == player:
        print(f"\n[INFO] Ya tenés el lock de '{world_name}'.")
        return True

    # Caso 3: El lock pertenece a otro jugador; requiere confirmación para reemplazarlo.
    expiration = parse_iso_datetime(world_lock["expires_at"])
    print(
        f"\n[!] '{world_name}' está bloqueado por '{world_lock['player']}' "
        f"({world_lock['machine']})."
    )
    print(f"    Expira: {expiration:%Y-%m-%d %H:%M} UTC")
    return confirm("¿Forzar de todas formas?")


def _allow_push_lock(
    world_name: str,
    world_lock: WorldLock | None,
    player: str,
    local_base: LocalBase | None,
) -> bool:
    """Comprueba si el lock permite publicar al jugador y su sesión."""
    # Caso 1: No hay lock activo; permite continuar.
    if world_lock is None:
        return True

    # Caso 2: El lock pertenece al jugador actual; compara las sesiones.
    if world_lock["player"] == player:
        remote_session = world_lock.get("session_id") if world_lock is not None else None
        local_session = local_base.get("session_id") if local_base is not None else None

        # Caso 2.1: Las sesiones difieren; bloquea la publicación.
        if remote_session != local_session:
            print(f"\n[BLOQUEADO] El lock de '{world_name}' pertenece a otra sesión tuya.")
            print("    Volvé a descargar para hostear o liberá el lock conscientemente.")
            return False

        # Caso 2.2: Las sesiones coinciden; permite continuar.
        print(f"\n[INFO] El lock activo de '{world_name}' pertenece a esta sesión.")
        return True

    # Caso 3: El lock pertenece a otro jugador; bloquea la publicación.
    expiration = parse_iso_datetime(world_lock["expires_at"])
    print(f"\n[BLOQUEADO] '{world_name}' está siendo usado por otro jugador.")
    print(f"    Jugador: {world_lock['player']} ({world_lock['machine']})")
    print(f"    El lock vence: {expiration:%Y-%m-%d %H:%M} UTC")
    print("    La publicación normal fue bloqueada para proteger su sesión.")
    return False


# ======================================================================================= #
# Acciones del menú
# ======================================================================================= #

def status_menu(storage: R2Storage) -> None:
    """Muestra la versión, fecha, autor, tamaño y estado de uso de los mundos remotos."""
    print("\n=== Estado de los mundos ===\n")

    # Consulta los mundos disponibles; una lista vacía no requiere más lecturas.
    world_names = _remote_world_names(storage)
    if not world_names:
        print("No hay mundos disponibles en la nube.")
        return

    # Presenta la versión publicada y el lock activo de cada mundo.
    for index, world_name in enumerate(world_names):
        if index:
            print()
        print(world_name)

        try:
            snapshot = read_world_state(storage, world_name)
            manifest = snapshot.value["manifest"]

            # La falta de manifest se informa sin impedir la consulta del lock.
            if manifest is None:
                print("  Manifest:       No disponible")
            else:
                uploaded_at = parse_iso_datetime(manifest["uploaded_at"])
                print(f"  Versión:        {manifest['version']}")
                print(f"  Última subida:  {uploaded_at:%Y-%m-%d %H:%M} UTC")
                print(f"  Subido por:     {manifest['uploaded_by']}")
                print(f"  Tamaño:         {_format_size(manifest['size'])}")
            world_lock = active_lock_value(snapshot.value["lock"])

            # Los locks ausentes o vencidos se muestran como un mundo libre.
            if world_lock is None:
                print("  Estado:         Libre")
            else:
                expiration = parse_iso_datetime(world_lock["expires_at"])
                print(
                    f"  Estado:         En uso por {world_lock['player']} "
                    f"({world_lock['machine']})"
                )
                print(f"  Lock vence:     {expiration:%Y-%m-%d %H:%M} UTC")

        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            # Error de lectura o interpretación: informa el problema y sigue con otros mundos.
            print("  Manifest:       Inválido")
            print("  Estado:         Lock inválido")
            print(f"  [BLOQUEADO] {world_name!r}: {error}")


def push_menu(settings: Settings, storage: R2Storage) -> None:
    """Permite elegir un mundo local y publicar sus cambios.

    Actualiza la versión remota y libera el lock en un mismo commit condicional.
    """
    print("\n=== Subir un mundo ===\n")

    # Busca mundos locales disponibles para publicar.
    errors: list[WorldNameIssue] = []
    worlds = list_worlds(settings.worlds_path, errors=errors)
    _show_world_name_errors(errors)
    if not worlds:
        print("No hay mundos locales disponibles.")
        return

    # Solicita la selección del mundo y la confirmación de la subida.
    world = choose(
        worlds,
        lambda item: (
            f"{item.name:<15} ({_format_size(item.size_bytes)}, "
            f"mod. {item.modified_at:%Y-%m-%d %H:%M})"
        ),
    )
    if world is None or not confirm(f"\n¿Confirmás subir '{world.name}' a la nube?"):
        print("\nOperación cancelada.")
        return

    # Valida la identidad remota y lee el estado con el ETag que se usará al publicar.
    try:
        _check_remote_name(storage, world.name)
        snapshot = read_world_state(storage, world.name)
        remote_manifest = snapshot.value["manifest"]
        local_base = read_base_version(settings.worlds_path, world.name)
        world_lock = active_lock_value(snapshot.value["lock"])
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        # Error de estado o identidad: cancela antes de preparar una subida.
        print(f"\n[BLOQUEADO] {world.name!r}: {error}")
        return

    # Comprueba que el lock autorice al jugador y su sesión.
    if not _allow_push_lock(world.name, world_lock, settings.player_name, local_base):
        print("\nOperación cancelada.")
        return

    # Comprueba la base local y solicita cualquier confirmación adicional de frescura.
    if not allow_push(world, remote_manifest, local_base):
        print("\nOperación cancelada.")
        return

    # Reserva una clave única para evitar que subidas concurrentes sobrescriban el ZIP.
    version = next_version(remote_manifest)
    zip_key = version_upload_zip_key(world.name, version, uuid.uuid4().hex)

    # Revisa identidades históricas antes de preparar o publicar el ZIP candidato.
    try:
        if remote_manifest is not None:
            read_version_manifest(storage, world.name, remote_manifest["version"])

        # Conflicto de historial: impide reutilizar una versión que ya está registrada.
        if read_version_manifest(storage, world.name, version) is not None:
            raise RuntimeError(f"La versión histórica {version} de {world.name!r} ya existe.")
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        # Error de historial: cancela antes de crear el ZIP candidato.
        print(f"\n[BLOQUEADO] {world.name!r}: {error}")
        return

    with tempfile.TemporaryDirectory(prefix="bifrost-push-") as temporary_dir:
        # Prepara el ZIP y su manifest fuera de la carpeta activa del mundo.
        zip_path = create_zip(world.path, Path(temporary_dir) / "world.zip")
        manifest = build_manifest(
            zip_path, world.name, version, settings.player_name, filename=zip_key
        )

        # Preserva la versión vigente en el historial antes de publicar la siguiente.
        if remote_manifest is not None:
            archived = archive_current_version(storage, world.name, remote_manifest)
            if archived:
                print(f"[historial] Versión {remote_manifest['version']} preservada.")
        print(f"[push] Subiendo ZIP de {_format_size(zip_path.stat().st_size)}...")

        # Completa la subida del ZIP antes de publicar el manifest y liberar el lock.
        storage.upload_file(zip_path, zip_key)
        next_state = updated_world_state(snapshot, manifest=manifest, world_lock=None)
        try:
            commit_world_state(storage, world.name, snapshot, next_state)
        except ConcurrentUpdateError:
            # Conflicto: descarta el ZIP candidato porque el estado leído ya cambió.
            storage.delete(zip_key)
            print(f"\n[CONFLICTO] El estado remoto de '{world.name}' cambió durante el push.")
            print("    El ZIP candidato fue descartado y la versión oficial no se modificó.")
            return

        # Tras el commit, registra la nueva base local y la versión publicada en el historial.
        save_base_version(
            settings.worlds_path, world.name, manifest["version"], manifest["sha256"]
        )
        record_published_version(storage, world.name, manifest)

        # Conserva la versión vigente y hasta cinco versiones anteriores.
        removed_versions = prune_remote_versions(
            storage, world.name, keep=MAX_PREVIOUS_REMOTE_VERSIONS + 1
        )
        if removed_versions:
            removed = ", ".join(str(item) for item in removed_versions)
            print(f"[historial] Versiones antiguas eliminadas: {removed}.")

    # Informa la liberación del lock que ya ocurrió dentro del commit.
    if world_lock is not None:
        print("[lock] Liberado")
    print(f"\n[OK] '{world.name}' subido correctamente (versión {version}).")


def pull_menu(settings: Settings, storage: R2Storage) -> None:
    """Permite elegir y descargar un mundo remoto para hostear.

    Adquiere el lock y reemplaza el mundo local conservando un backup si ya existía.
    """
    print("\n=== Descargar para hostear ===\n")

    # Consulta las versiones remotas disponibles para descargar.
    remote_worlds = _remote_worlds(storage)
    if not remote_worlds:
        print("No hay mundos legibles en la nube todavía.")
        return

    # Solicita la selección del mundo; volver termina la operación.
    selected = choose(
        remote_worlds,
        lambda item: (
            f"{item[0]:<15} (versión {item[1]['version']}, "
            f"{_format_size(item[1]['size'])}, "
            f"fecha {parse_iso_datetime(item[1]['uploaded_at']):%Y-%m-%d %H:%M} UTC, "
            f"subido por {item[1]['uploaded_by']})"
        ),
    )
    if selected is None:
        return

    world_name, manifest, snapshot = selected

    # Revisa el destino, la base y el lock antes de confirmar o adquirir la sesión.
    try:
        destination = check_install_destination(settings.worlds_path, world_name)

        # Conflicto de nombre: exige la misma escritura en el mundo local y el remoto.
        if destination.name != world_name:
            raise WorldNameConflictError([destination.name, world_name])

        check_base_destination(
            settings.worlds_path, world_name, manifest["version"], manifest["sha256"]
        )
        world_lock = active_lock_value(snapshot.value["lock"])
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        # Error de preparación: cancela sin adquirir el lock ni reemplazar el mundo.
        print(f"\n[BLOQUEADO] {world_name!r}: {error}")
        return

    # Confirma el reemplazo y comprueba si la fecha local requiere otra confirmación.
    if not confirm(f"\n¿Descargar '{world_name}' y reemplazar tu copia local?"):
        print("\nOperación cancelada.")
        return

    if not allow_pull(settings, world_name, manifest):
        return

    # Comprueba si se puede adquirir el lock o si es necesario confirmar uno ajeno.
    if not _allow_lock_override(world_lock, world_name, settings.player_name):
        print("\nOperación cancelada.")
        return

    # Adquiere el lock sobre el estado leído antes de comenzar la descarga.
    world_lock = build_lock(
        settings.player_name, base_version=manifest["version"]
    )
    locked_state = updated_world_state(snapshot, manifest=manifest, world_lock=world_lock)
    try:
        commit_world_state(storage, world_name, snapshot, locked_state)
    except ConcurrentUpdateError:
        # Conflicto: termina sin descargar ni reemplazar el mundo local.
        print("\n[CONFLICTO] El estado remoto cambió antes de adquirir el lock.")
        print("    Volvé a intentar para trabajar con la versión vigente.")
        return
    print(
        f"[lock] Adquirido hasta "
        f"{parse_iso_datetime(world_lock['expires_at']):%Y-%m-%d %H:%M} UTC"
    )

    # Descarga y prepara el mundo en un temporal antes de tocar la carpeta activa.
    with tempfile.TemporaryDirectory(prefix="bifrost-pull-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        zip_path = storage.download_file(manifest["filename"], temporary_root / "world.zip")

        # Error de integridad: conserva el mundo local y no libera el lock adquirido.
        if not verify_zip(zip_path, manifest["sha256"]):
            print("\n[ERROR] El ZIP descargado no coincide con el manifest.")
            return

        # Valida las rutas al extraer y conserva un backup durante la instalación.
        staged_world = extract_zip(zip_path, temporary_root / "staged-world")
        backup = install_staged_world(settings.worlds_path, world_name, staged_world)

        # Registra la base descargada y la sesión que podrá publicar al terminar de hostear.
        save_base_version(
            settings.worlds_path,
            world_name,
            manifest["version"],
            manifest["sha256"],
            session_id=world_lock["session_id"],
        )

    print(f"\n[OK] '{world_name}' descargado y verificado.")
    if backup:
        print(f"[INFO] Tu versión anterior está en '{backup}'.")


def copy_menu(settings: Settings, storage: R2Storage) -> None:
    """Permite elegir un mundo remoto y guardar su ZIP verificado en .bifrost-copies.

    No reemplaza el mundo local ni modifica su base o sus locks.
    """
    print("\n=== Descargar una copia ===\n")

    # Consulta las versiones remotas disponibles para guardar una copia.
    remote_worlds = _remote_worlds(storage)
    if not remote_worlds:
        print("No hay mundos legibles en la nube todavía.")
        return

    # Solicita la selección del mundo; volver termina la operación.
    selected = choose(
        remote_worlds,
        lambda item: (
            f"{item[0]:<15} (versión {item[1]['version']}, "
            f"{_format_size(item[1]['size'])}, "
            f"fecha {parse_iso_datetime(item[1]['uploaded_at']):%Y-%m-%d %H:%M} UTC, "
            f"subido por {item[1]['uploaded_by']})"
        ),
    )
    if selected is None:
        return

    # Explica el alcance de la copia independiente.
    print("\n[INFO] Esta descarga no reemplaza tu mundo local ni adquiere el lock.")
    world_name, manifest, _ = selected

    # Revisa los datos y el destino antes de confirmar o descargar la copia.
    try:
        check_copy_destination(
            settings.worlds_path, world_name, manifest["version"], manifest["sha256"]
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        # Error de destino o metadata: cancela sin iniciar la descarga.
        print(f"\n[BLOQUEADO] {world_name!r}: {error}")
        return

    # Solicita confirmación una vez comprobado el destino de la copia.
    if not confirm(f"¿Guardar una copia de '{world_name}'?"):
        print("\nOperación cancelada.")
        return

    # Descarga a un temporal para verificar el ZIP antes de guardarlo como copia.
    with tempfile.TemporaryDirectory(prefix="bifrost-copy-") as temporary_dir:
        zip_path = storage.download_file(
            manifest["filename"], Path(temporary_dir) / "world.zip"
        )

        # Error de integridad: descarta la descarga sin guardar una copia.
        if not verify_zip(zip_path, manifest["sha256"]):
            print("\n[ERROR] El ZIP descargado no coincide con el manifest.")
            return

        # Guarda el ZIP verificado en .bifrost-copies, fuera de los mundos activos.
        destination = save_world_copy(
            settings.worlds_path,
            world_name,
            manifest["version"],
            manifest["sha256"],
            zip_path,
        )

    print(f"\n[OK] Copia verificada guardada en '{destination}'.")
    print("[INFO] No se adquirió ningún lock ni se modificó la versión base local.")


def restore_menu(settings: Settings, storage: R2Storage) -> None:
    """Permite confirmar contenido histórico como una nueva versión compartida.

    Conserva el estado leído al seleccionar el mundo y no modifica sus archivos ni base locales.
    """
    print("\n=== Restaurar una versión anterior ===\n")

    try:
        # Consulta los mundos remotos disponibles y sus versiones históricas.
        remote_worlds = _remote_worlds(storage)
        if not remote_worlds:
            print("No hay mundos legibles en la nube todavía.")
            return

        # Solicita la selección del mundo; volver termina la operación.
        selected = choose(
            remote_worlds,
            lambda item: (
                f"{item[0]:<15} (versión vigente {item[1]['version']}, "
                f"{_format_size(item[1]['size'])})"
            ),
        )
        if selected is None:
            print("\nOperación cancelada.")
            return
        world_name, manifest, snapshot = selected

        # Valida la publicación y bloquea cualquier lock activo antes de ofrecer el historial.
        current = validate_manifest(world_name, manifest)
        ensure_restore_unlocked(snapshot.value["lock"])
        previous = list_previous_versions(storage, world_name, current)
        if not previous:
            print(f"\n[INFO] '{world_name}' no tiene versiones anteriores publicadas disponibles.")
            return

        # Solicita la selección de la versión histórica; volver termina la operación.
        print(f"\nVersiones anteriores de '{world_name}' (vigente: {current['version']}):\n")
        historical = choose(
            previous,
            lambda item: (
                f"Versión {item['version']}, "
                f"fecha {parse_iso_datetime(item['uploaded_at']):%Y-%m-%d %H:%M} UTC, "
                f"subido por {item['uploaded_by']}, {_format_size(item['size'])}"
            ),
            prompt="Elegí una versión anterior",
        )
        if historical is None:
            print("\nOperación cancelada.")
            return

        # Explica la nueva numeración y el alcance global antes de pedir una decisión explícita.
        new_version = current["version"] + 1
        print(f"\n[INFO] Se publicará una nueva versión {new_version}, vigente para todo el grupo.")
        print("    Tus archivos locales permanecerán sin cambios.")
        print("    Después usá 'Descargar para hostear' antes de hostear o subir progreso.")
        if not confirm(
            f"¿Restaurar '{world_name}' con el contenido de la versión "
            f"{historical['version']} para todo el grupo?"
        ):
            print("\nOperación cancelada.")
            return

        print("\n[INFO] Descargando y verificando la versión histórica...")
        result = restore_world_version(
            storage, world_name, historical["version"], settings.player_name, snapshot=snapshot
        )
    
    except ConcurrentUpdateError as error:
        print(f"\n[CONFLICTO] {error}")
        print("    Volvé a consultar las versiones antes de intentar restaurar.")
        return
    
    except ClientError as error:
        # Los errores S3 se presentan sin incluir respuestas, endpoints ni credenciales.
        if R2Storage._is_not_found(error):
            print("\n[ERROR] No está disponible un archivo remoto necesario para restaurar.")
        else:
            print("\n[ERROR] No se pudo acceder a R2; revisá los permisos y la configuración.")
        return
    
    except BotoCoreError:
        print("\n[ERROR] No se pudo consultar R2; revisá la conexión y la configuración.")
        return
    
    except (zipfile.BadZipFile, zlib.error):
        print("\n[BLOQUEADO] El ZIP histórico no es válido o está dañado.")
        return
    
    except OSError:
        print("\n[ERROR] No se pudo completar la transferencia o preparar sus archivos temporales.")
        return
    
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        # Incluye respuestas inciertas del commit sin afirmar que la publicación se canceló.
        print(f"\n[ERROR] {error}")
        return

    print(
        f"\n[OK] '{world_name}': contenido de la versión {historical['version']} "
        f"publicado como versión {result.manifest['version']}."
    )
    
    for warning in result.warnings:
        print(f"[ADVERTENCIA] {warning}")
        
    if result.removed_versions:
        versions = ", ".join(str(version) for version in result.removed_versions)
        print(f"[historial] Versiones antiguas eliminadas: {versions}.")
        
    print("[INFO] Tu mundo local y su versión base siguen sin cambios.")
    print("    Usá 'Descargar para hostear' antes de hostear o subir progreso.")


def lock_menu(settings: Settings, storage: R2Storage) -> None:
    """Muestra los locks y permite liberar el elegido con confirmación.

    Advierte al usuario si el lock pertenece a otro jugador.
    """
    print("\n=== Estado del lock ===\n")

    # Consulta el lock activo y conserva el estado leído para una posible liberación.
    lock_info = []
    for name in _remote_world_names(storage):
        try:
            snapshot = read_world_state(storage, name)
            world_lock = active_lock_value(snapshot.value["lock"])

            # Comprueba que un lock activo incluya el jugador que se mostrará en el menú.
            if world_lock is not None:
                world_lock["player"]
            lock_info.append((name, world_lock, snapshot))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            # Error de metadata: excluye este mundo sin ocultar los demás locks consultables.
            print(f"[BLOQUEADO] Mundo remoto {name!r}: {error}")
    if not lock_info:
        print("No hay mundos disponibles en la nube.")
        return

    def format_lock(item: tuple[str, WorldLock | None, StateSnapshot]) -> str:
        """Describe un mundo libre o muestra el dueño y vencimiento de su lock activo."""
        name, world_lock, _ = item

        # Caso 1: No hay lock activo; muestra el mundo como libre.
        if world_lock is None:
            return f"{name:<15} (libre)"

        # Caso 2: Hay lock activo; muestra quién lo tiene y cuándo vence.
        expiration = parse_iso_datetime(world_lock["expires_at"])
        return (
            f"{name:<15} (bloqueado por {world_lock['player']} "
            f"hasta {expiration:%Y-%m-%d %H:%M} UTC)"
        )

    # Solicita la selección del mundo; volver termina la operación.
    selected = choose(lock_info, format_lock)
    if selected is None:
        return

    world_name, world_lock, snapshot = selected

    # Un mundo libre no requiere ninguna modificación remota.
    if world_lock is None:
        print(f"\n[INFO] '{world_name}' no tiene lock activo.")
        return

    # Advierte si el lock es ajeno antes de solicitar la confirmación de liberación.
    if world_lock["player"] != settings.player_name:
        print(f"\n[!] El lock es de '{world_lock['player']}', no tuyo.")

    # Libera el lock solo si el usuario confirma y el estado remoto sigue coincidiendo.
    if confirm(f"¿Liberar el lock de '{world_name}'?"):
        unlocked = updated_world_state(
            snapshot, manifest=snapshot.value["manifest"], world_lock=None
        )
        try:
            commit_world_state(storage, world_name, snapshot, unlocked)
        except ConcurrentUpdateError:
            # Conflicto: conserva el estado remoto que cambió después de la lectura.
            print("\n[CONFLICTO] El estado remoto cambió; no se liberó ningún lock.")
            return
        print("[lock] Liberado")


# ======================================================================================= #
# Menú principal e inicio
# ======================================================================================= #

def run_menu(settings: Settings, storage: R2Storage) -> None:
    """Mantiene el menú principal abierto y ejecuta las opciones hasta que el usuario sale."""
    while True:
        print("\n=== Bifröst ===")
        print("  1) Estado de los mundos")
        print("  2) Subir un mundo")
        print("  3) Descargar para hostear")
        print("  4) Descargar una copia")
        print("  5) Ver/liberar lock")
        print("  6) Restaurar una versión anterior")
        print("  7) Salir")

        # Ejecuta la acción elegida y vuelve al menú, salvo cuando se solicita salir.
        option = input("\nElegí una opción: ").strip()
        if option == "1":
            status_menu(storage)
        elif option == "2":
            push_menu(settings, storage)
        elif option == "3":
            pull_menu(settings, storage)
        elif option == "4":
            copy_menu(settings, storage)
        elif option == "5":
            lock_menu(settings, storage)
        elif option == "6":
            restore_menu(settings, storage)
        elif option == "7":
            print("\n¡Chau!")
            return
        else:
            print("\nOpción inválida.")


def main() -> None:
    """Carga la configuración e inicia la interfaz interactiva de Bifröst."""
    # Procesa los argumentos antes de cargar la configuración o conectarse a R2.
    parser = argparse.ArgumentParser(
        prog="bifrost",
        description="Sincroniza mundos de Valheim mediante Cloudflare R2.",
    )
    parser.parse_args()
    try:
        # Valida la carpeta local y prepara el acceso remoto antes de abrir el menú.
        settings = load_settings()
        settings.validate_worlds_path()
        storage = R2Storage(settings)
        run_menu(settings, storage)
    except (RuntimeError, OSError) as error:
        # Error operativo: muestra el motivo y termina con un código de salida de fallo.
        print(f"\n[ERROR] {error}")
        raise SystemExit(1) from error
