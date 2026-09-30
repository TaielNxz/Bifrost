import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from .archives import create_zip, extract_zip, verify_zip
from .config import Settings, load_settings
from .local_worlds import find_world, install_staged_world, list_worlds
from .locks import acquire_lock, active_lock, release_lock
from .manifests import build_manifest, next_version, parse_iso_datetime
from .models import Manifest, World
from .paths import current_zip_key
from .storage import R2Storage

T = TypeVar("T")


def confirm(question: str) -> bool:
    """Pregunta al usuario y devuelve True si responde 's' (sí)."""
    return input(f"{question} [s/n]: ").strip().lower() == "s"


def choose(items: Sequence[T], formatter: Callable[[T], str], prompt: str = "Elegí un mundo") -> T | None:
    """Muestra una lista de items y devuelve el elegido por el usuario, o None si cancela."""
    for index, item in enumerate(items, 1):
        print(f"  {index}) {formatter(item)}")
    print("  0) Volver")
    answer = input(f"\n{prompt}: ").strip()
    if answer == "0":
        return None
    try:
        index = int(answer) - 1
        if index < 0:
            raise IndexError
        return items[index]
    except (ValueError, IndexError):
        print("\nOpción inválida.")
        return None


def show_comparison(world: World, manifest: Manifest) -> tuple[datetime, datetime]:
    """Muestra la comparación entre la versión remota y la local de un mundo."""
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


def allow_push(world: World, remote_manifest: Manifest | None) -> bool:
    """Devuelve True si se permite subir el mundo, o False si se cancela."""
    if remote_manifest is None:
        print(f"\n[INFO] No hay versión previa de '{world.name}' en la nube.")
        return True
    remote_date, local_date = show_comparison(world, remote_manifest)
    if remote_date > local_date:
        print("\n[!] La versión remota es MÁS NUEVA que tu versión local.")
        print("    Si subís ahora, VAS A SOBRESCRIBIR ese progreso.")
        return confirm("\n¿Continuar igual?")
    print("\n[OK] Tu versión local es igual o más nueva que la remota.")
    return True


def allow_pull(settings: Settings, world_name: str, manifest: Manifest) -> bool:
    """Devuelve True si se permite descargar el mundo, o False si se cancela."""
    local_world = find_world(settings.worlds_path, world_name)
    if local_world is None:
        print(f"\n[INFO] No tenés '{world_name}' localmente. Se va a crear.")
        return True
    remote_date, local_date = show_comparison(local_world, manifest)
    if local_date > remote_date:
        print("\n[!] Tu versión local es MÁS NUEVA que la de la nube.")
        print("    Si descargás, VAS A PERDER los cambios locales.")
        return confirm("\n¿Continuar igual?")
    print("\n[OK] La versión remota es igual o más nueva. Seguro bajar.")
    return True


def _format_size(size_bytes: int) -> str:
    """Formatea una cantidad de bytes con una unidad legible."""
    size = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("Unidad de tamaño inalcanzable")


def status_menu(storage: R2Storage) -> None:
    """Muestra la versión remota y el lock activo de todos los mundos."""
    print("\n=== Estado de los mundos ===\n")
    
    # Obtiene nombres de mundos remotos
    world_names = storage.list_worlds()
    if not world_names:
        print("No hay mundos en la nube.")
        return

    # Por cada mundo, muestra su manifest y estado de lock
    for index, world_name in enumerate(world_names):
        
        # Muestra el nombre del mundo
        if index:
            print()
        print(world_name)

        # Verifica la validez del manifest remoto
        invalid_manifest = False
        try:
            manifest = storage.read_manifest(world_name)
        except (TypeError, ValueError):
            manifest = None
            invalid_manifest = True

        if invalid_manifest:
            print("  Manifest:       Inválido")
        elif manifest is None:
            print("  Manifest:       No disponible")
        else:
            try:
                uploaded_at = parse_iso_datetime(manifest["uploaded_at"])
                print(f"  Versión:        {manifest['version']}")
                print(f"  Última subida:  {uploaded_at:%Y-%m-%d %H:%M} UTC")
                print(f"  Subido por:     {manifest['uploaded_by']}")
                print(f"  Tamaño:         {_format_size(manifest['size'])}")
            except (KeyError, TypeError, ValueError):
                print("  Manifest:       Inválido")

        # Verifica el estado del lock remoto
        try:
            world_lock = active_lock(storage, world_name)
            if world_lock is None:
                print("  Estado:         Libre")
            else:
                expiration = parse_iso_datetime(world_lock["expires_at"])
                print(
                    f"  Estado:         En uso por {world_lock['player']} "
                    f"({world_lock['machine']})"
                )
                print(f"  Lock vence:     {expiration:%Y-%m-%d %H:%M} UTC")
        except (KeyError, TypeError, ValueError):
            print("  Estado:         Lock inválido")


def push_menu(settings: Settings, storage: R2Storage) -> None:
    """Sube un mundo local a la nube, reemplazando la versión remota si existe."""
    print("\n=== Subir un mundo ===\n")
    worlds = list_worlds(settings.worlds_path)
    if not worlds:
        print("No hay mundos locales.")
        return
    world = choose(
        worlds,
        lambda item: (
            f"{item.name:<15} ({item.size_mb} MB, "
            f"mod. {item.modified_at:%Y-%m-%d %H:%M})"
        ),
    )
    if world is None or not confirm(f"\n¿Confirmás subir '{world.name}' a la nube?"):
        print("\nOperación cancelada.")
        return

    remote_manifest = storage.read_manifest(world.name)
    if not allow_push(world, remote_manifest):
        print("\nOperación cancelada.")
        return

    version = next_version(remote_manifest)
    with tempfile.TemporaryDirectory(prefix="bifrost-push-") as temporary_dir:
        zip_path = create_zip(world.path, Path(temporary_dir) / "world.zip")
        manifest = build_manifest(zip_path, world.name, version, settings.player_name)
        print(f"[push] Subiendo ZIP de {zip_path.stat().st_size} bytes...")
        storage.upload_file(zip_path, current_zip_key(world.name))
        storage.write_manifest(world.name, manifest)

    world_lock = active_lock(storage, world.name)
    if world_lock and world_lock["player"] == settings.player_name:
        release_lock(storage, world.name)
        print("[lock] Liberado")
    print(f"\n[OK] '{world.name}' subido correctamente (versión {version}).")


def _allow_lock_override(storage: R2Storage, world_name: str, player: str) -> bool:
    """Devuelve True si se permite forzar el lock, o False si se cancela."""
    world_lock = active_lock(storage, world_name)
    if world_lock is None:
        return True
    if world_lock["player"] == player:
        print(f"\n[INFO] Ya tenés el lock de '{world_name}'.")
        return True
    expiration = parse_iso_datetime(world_lock["expires_at"])
    print(
        f"\n[!] '{world_name}' está bloqueado por '{world_lock['player']}' "
        f"({world_lock['machine']})."
    )
    print(f"    Expira: {expiration:%Y-%m-%d %H:%M} UTC")
    return confirm("¿Forzar de todas formas?")


def pull_menu(settings: Settings, storage: R2Storage) -> None:
    """Descarga un mundo de la nube y reemplaza la versión local si existe."""
    print("\n=== Descargar un mundo ===\n")
    remote_worlds = []
    for name in storage.list_worlds():
        manifest = storage.read_manifest(name)
        if manifest is not None:
            remote_worlds.append((name, manifest))
    if not remote_worlds:
        print("No hay mundos legibles en la nube todavía.")
        return

    selected = choose(
        remote_worlds,
        lambda item: (
            f"{item[0]:<15} (versión {item[1]['version']}, "
            f"fecha {parse_iso_datetime(item[1]['uploaded_at']):%Y-%m-%d %H:%M} UTC, "
            f"subido por {item[1]['uploaded_by']})"
        ),
    )
    if selected is None:
        return
    world_name, manifest = selected
    if not confirm(f"\n¿Descargar '{world_name}' y reemplazar tu copia local?"):
        print("\nOperación cancelada.")
        return
    if not allow_pull(settings, world_name, manifest):
        return
    if not _allow_lock_override(storage, world_name, settings.player_name):
        print("\nOperación cancelada.")
        return

    world_lock = acquire_lock(storage, world_name, settings.player_name)
    print(f"[lock] Adquirido hasta {parse_iso_datetime(world_lock['expires_at']):%Y-%m-%d %H:%M} UTC")

    with tempfile.TemporaryDirectory(prefix="bifrost-pull-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        zip_path = storage.download_file(
            current_zip_key(world_name), temporary_root / "world.zip"
        )
        if not verify_zip(zip_path, manifest["sha256"]):
            print("\n[ERROR] El ZIP descargado no coincide con el manifest.")
            return
        staged_world = extract_zip(zip_path, temporary_root / "staged-world")
        backup = install_staged_world(settings.worlds_path, world_name, staged_world)

    print(f"\n[OK] '{world_name}' descargado y verificado.")
    if backup:
        print(f"[INFO] Tu versión anterior está en '{backup}'.")


def lock_menu(settings: Settings, storage: R2Storage) -> None:
    """Muestra el estado de los locks y permite liberar uno propio."""
    print("\n=== Estado del lock ===\n")
    lock_info = [(name, active_lock(storage, name)) for name in storage.list_worlds()]
    if not lock_info:
        print("No hay mundos en la nube.")
        return

    def format_lock(item: tuple[str, object]) -> str:
        """Formatea un mundo y el estado de su lock para el menú."""
        name, world_lock = item
        if world_lock is None:
            return f"{name:<15} (libre)"
        expiration = parse_iso_datetime(world_lock["expires_at"])  # type: ignore[index]
        return (
            f"{name:<15} (bloqueado por {world_lock['player']} "  # type: ignore[index]
            f"hasta {expiration:%Y-%m-%d %H:%M} UTC)"
        )

    selected = choose(lock_info, format_lock)
    if selected is None:
        return
    world_name, world_lock = selected
    if world_lock is None:
        print(f"\n[INFO] '{world_name}' no tiene lock activo.")
        return
    if world_lock["player"] != settings.player_name:
        print(f"\n[!] El lock es de '{world_lock['player']}', no tuyo.")
    if confirm(f"¿Liberar el lock de '{world_name}'?"):
        release_lock(storage, world_name)
        print("[lock] Liberado")


def run_menu(settings: Settings, storage: R2Storage) -> None:
    """Muestra el menú principal y ejecuta la opción elegida por el usuario."""
    while True:
        print("\n=== Bifröst ===")
        print("  1) Estado de los mundos")
        print("  2) Subir un mundo")
        print("  3) Descargar un mundo")
        print("  4) Ver/liberar lock")
        print("  5) Salir")
        option = input("\nElegí una opción: ").strip()
        if option == "1":
            status_menu(storage)
        elif option == "2":
            push_menu(settings, storage)
        elif option == "3":
            pull_menu(settings, storage)
        elif option == "4":
            lock_menu(settings, storage)
        elif option == "5":
            print("\n¡Chau!")
            return
        else:
            print("\nOpción inválida.")


def main() -> None:
    """Carga la configuración e inicia la interfaz interactiva de Bifröst."""
    parser = argparse.ArgumentParser(
        prog="bifrost",
        description="Sincroniza mundos de Valheim mediante Cloudflare R2.",
    )
    parser.parse_args()
    try:
        settings = load_settings()
        settings.validate_worlds_path()
        storage = R2Storage(settings)
        run_menu(settings, storage)
    except (RuntimeError, OSError) as error:
        print(f"\n[ERROR] {error}")
        raise SystemExit(1) from error
