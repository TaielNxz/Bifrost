import os
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path

from .local_paths import ensure_local_path, iter_local_files
from .models import World
from .world_names import (
    InvalidWorldNameError,
    WorldNameConflictError,
    WorldNameIssue,
    filter_world_names,
    validate_world_name,
    world_name_key,
)

COPIES_DIRECTORY_NAME = ".bifrost-copies"


# ======================================================================================= #
# Detección de mundos
# ======================================================================================= #

def is_backup(name: str) -> bool:
    """Indica si el nombre corresponde a una carpeta de backup local."""
    comparison_name = name.casefold()
    return "_backup_" in comparison_name or "_pre_pull_" in comparison_name


def is_bifrost_directory(name: str) -> bool:
    """Indica si el nombre corresponde a la carpeta de copias independientes de Bifröst."""
    return name.casefold() == COPIES_DIRECTORY_NAME.casefold()


def directory_size(directory: str | os.PathLike[str]) -> int:
    """Suma recursivamente el tamaño de los archivos de una carpeta.

    Rechaza enlaces y junctions; omite los archivos cuyo tamaño no puede consultar.
    """
    total = 0
    for file_path in iter_local_files(directory):
        try:
            total += file_path.stat().st_size
        except OSError:
            # Error de consulta: conserva el total parcial y continúa con otros archivos.
            pass
    return total


def list_worlds(
    worlds_path: str | os.PathLike[str], *, errors: list[WorldNameIssue] | None = None
) -> list[World]:
    """Lista mundos locales utilizables, omitiendo backups y copias independientes.

    Excluye nombres inválidos o ambiguos y enlaces o junctions en los mundos.
    Permite recoger los errores de nombres sin bloquear el listado de los demás mundos.
    """
    root = Path(worlds_path)
    if not root.is_dir():
        raise RuntimeError(f"La carpeta de mundos no existe:\n  {root}")

    # Selecciona entradas candidatas sin seguir enlaces ni incluir carpetas reservadas.
    entries = {}
    for entry in root.iterdir():
        if is_backup(entry.name) or is_bifrost_directory(entry.name):
            continue
        # lstat identifica carpetas y enlaces sin consultar el destino de estos últimos.
        metadata = entry.lstat()
        if stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            entries[entry.name] = entry

    # Excluye nombres inválidos o ambiguos antes de consultar el contenido de los mundos.
    issues: list[WorldNameIssue] = []
    names = filter_world_names(entries, errors=issues)

    # Consulta tamaño y fecha únicamente para mundos con nombres utilizables.
    worlds = []
    for name in names:
        try:
            path = ensure_local_path(root, entries[name])
            world = World(
                name=name,
                path=path,
                size_bytes=directory_size(path),
                # La fecha es la de la carpeta raíz, no la del archivo más reciente.
                modified_at=datetime.fromtimestamp(path.stat().st_mtime),
            )
        except RuntimeError as error:
            # Error de ruta: excluye este mundo y permite continuar con los demás.
            issues.append(InvalidWorldNameError(name, str(error)))
            continue
        worlds.append(world)

    # Entrega los motivos de exclusión cuando el llamador solicita recogerlos.
    if errors is not None:
        errors.extend(issues)
    return worlds


def find_world(worlds_path: str | os.PathLike[str], name: str) -> World | None:
    """Busca un mundo válido sin distinguir mayúsculas y devuelve None si no existe.

    Rechaza nombres inválidos o ambiguos en lugar de tratarlos como mundos ausentes.
    """
    key = world_name_key(name)
    errors: list[WorldNameIssue] = []
    worlds = list_worlds(worlds_path, errors=errors)

    # Propaga los problemas del mundo solicitado sin bloquearlo por errores de otros nombres.
    for error in errors:
        if isinstance(error, WorldNameConflictError) and world_name_key(error.names[0]) == key:
            raise error
        if (
            isinstance(error, InvalidWorldNameError)
            and isinstance(error.name, str)
            and error.name.casefold() == key
        ):
            raise error

    return next((world for world in worlds if world_name_key(world.name) == key), None)


# ======================================================================================= #
# Backup e instalación
# ======================================================================================= #

def _backup_destination(worlds_path: str | os.PathLike[str], name: str) -> Path:
    """Busca una ruta de backup validada que todavía no exista."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    basename = f"{name}_pre_pull_{timestamp}"
    destination = ensure_local_path(worlds_path, Path(worlds_path) / basename)

    # Agrega un sufijo si otro backup ya utiliza la misma fecha y hora.
    index = 1
    while destination.exists():
        destination = ensure_local_path(worlds_path, Path(worlds_path) / f"{basename}_{index}")
        index += 1
    return destination


def backup_world(worlds_path: str | os.PathLike[str], name: str) -> Path | None:
    """Mueve un mundo local a un backup fechado y devuelve su ruta.

    Devuelve None si no hay un mundo local para respaldar.
    """
    world = find_world(worlds_path, name)

    # Caso 1: No existe el mundo local; no hay nada que respaldar.
    if world is None:
        return None

    # Caso 2: Existe el mundo local; lo aparta de la ruta activa como backup fechado.
    destination = _backup_destination(worlds_path, world.name)
    ensure_local_path(worlds_path, world.path)
    shutil.move(str(world.path), str(destination))
    return destination


def check_install_destination(worlds_path: str | os.PathLike[str], name: str) -> Path:
    """Revisa el mundo, su destino y el backup sin crear ni mover archivos."""
    # Resuelve el mundo existente y conserva la escritura de su nombre real.
    validate_world_name(name)
    world = find_world(worlds_path, name)
    destination = ensure_local_path(
        worlds_path, world.path if world else Path(worlds_path) / name
    )

    # Error de destino: impide instalar sobre una entrada que no sea un mundo utilizable.
    if world is None and destination.exists():
        raise RuntimeError(f"El destino local ya está ocupado: {str(destination)!r}.")

    # Comprueba también el futuro backup cuando hay un mundo que deberá apartarse.
    if world is not None:
        _backup_destination(worlds_path, world.name)
    return destination


def install_staged_world(
    worlds_path: str | os.PathLike[str], name: str, staged_world: str | os.PathLike[str]
) -> Path | None:
    """Instala un mundo preparado conservando el anterior como backup, si existe.

    Intenta restaurar el original si la instalación falla antes de crear el destino.
    """
    # Valida el nombre y las rutas antes de preparar el reemplazo.
    destination = check_install_destination(worlds_path, name)
    staged = Path(staged_world)
    ensure_local_path(staged.parent, staged)
    if not staged.is_dir():
        raise RuntimeError(f"No existe la carpeta preparada: {str(staged)!r}.")

    # Impide que el origen y el destino coincidan o que uno contenga al otro.
    staged_resolved = staged.resolve()
    destination_resolved = destination.resolve()
    if (
        staged_resolved.is_relative_to(destination_resolved)
        or destination_resolved.is_relative_to(staged_resolved)
    ):
        raise RuntimeError("La carpeta preparada debe estar separada del mundo activo.")

    # Revisa todo el contenido preparado para rechazar enlaces antes de apartar el original.
    directory_size(staged)

    # Aparta el mundo anterior como backup conservando su nombre real.
    backup = backup_world(worlds_path, name)

    # Instala la carpeta preparada después de volver a comprobar el destino.
    try:
        ensure_local_path(worlds_path, destination)
        shutil.move(str(staged), str(destination))
    except Exception:
        # Error de instalación: intenta recuperar el original si el destino sigue sin existir.
        if backup is not None and not destination.exists():
            ensure_local_path(worlds_path, backup)
            ensure_local_path(worlds_path, destination)
            shutil.move(str(backup), str(destination))

        # Propaga el fallo de instalación aunque se haya podido restaurar el original.
        raise
    return backup


# ======================================================================================= #
# Copias independientes
# ======================================================================================= #

def check_copy_destination(
    worlds_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    sha256: str,
) -> Path:
    """Revisa los datos y el destino de una copia sin crear archivos ni carpetas."""
    # Valida los datos usados en el nombre de la copia antes de preparar su destino.
    validate_world_name(world_name)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("La versión de la copia debe ser un entero positivo.")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        raise ValueError("El SHA-256 de la copia no es válido.")

    # Comprueba la ruta de la copia fuera de las carpetas detectadas como mundos activos.
    copies_directory = ensure_local_path(worlds_path, Path(worlds_path) / COPIES_DIRECTORY_NAME)
    destination = ensure_local_path(
        worlds_path, copies_directory / f"{world_name}_v{version}_{sha256[:12].lower()}.zip"
    )

    # Error de destino: rechaza entradas cuyo tipo impediría guardar el ZIP.
    if destination.is_dir():
        raise RuntimeError(f"El destino de la copia ya es una carpeta: {str(destination)!r}.")
    if copies_directory.exists() and not copies_directory.is_dir():
        raise RuntimeError(f"La carpeta de copias ya está ocupada: {str(copies_directory)!r}.")
    return destination


def save_world_copy(
    worlds_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    sha256: str,
    source_zip: str | os.PathLike[str],
) -> Path:
    """Guarda un ZIP previamente verificado sin modificar el mundo activo ni su base."""
    destination = check_copy_destination(worlds_path, world_name, version, sha256)

    # Comprueba que el ZIP de origen sea un archivo, sin aceptar enlaces ni junctions.
    source = Path(source_zip)
    ensure_local_path(source.parent, source)
    if not source.is_file():
        raise RuntimeError(f"No existe el ZIP de origen: {str(source)!r}.")

    # Crea la carpeta de copias solo después de validar el origen y el destino.
    copies_directory = destination.parent
    copies_directory.mkdir(exist_ok=True)

    temporary_path: Path | None = None
    try:
        # Prepara la copia en el mismo directorio antes de reemplazar el ZIP de destino.
        with tempfile.NamedTemporaryFile(
            dir=copies_directory,
            prefix="bifrost-copy-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        shutil.copyfile(source, temporary_path)

        # Vuelve a comprobar el destino antes de sustituir la copia anterior, si existe.
        ensure_local_path(worlds_path, destination)
        temporary_path.replace(destination)
    finally:
        # Limpia cualquier temporal restante, incluso si falla la copia o el reemplazo.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination

