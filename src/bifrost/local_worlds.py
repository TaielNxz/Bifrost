import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .models import World

COPIES_DIRECTORY_NAME = ".bifrost-copies"


# ======================================================================================= #
# Detección de mundos
# ======================================================================================= #

def is_backup(name: str) -> bool:
    """Indica si el nombre corresponde a una carpeta de backup local."""
    return "_backup_" in name or "_pre_pull_" in name


def is_bifrost_directory(name: str) -> bool:
    """Indica si el nombre corresponde a la carpeta de copias independientes de Bifröst."""
    return name == COPIES_DIRECTORY_NAME


def directory_size(directory: str | os.PathLike[str]) -> int:
    """Suma recursivamente el tamaño de los archivos de una carpeta.

    Omite los archivos cuyo tamaño no puede consultar.
    """
    total = 0
    for current_dir, _, files in os.walk(directory):
        for filename in files:
            try:
                total += (Path(current_dir) / filename).stat().st_size
            except OSError:
                # Error de consulta: conserva el total parcial y continúa con otros archivos.
                pass
    return total


def list_worlds(worlds_path: str | os.PathLike[str]) -> list[World]:
    """Lista los mundos locales por nombre, omitiendo backups y la carpeta de copias."""
    root = Path(worlds_path)
    if not root.is_dir():
        raise RuntimeError(f"La carpeta de mundos no existe:\n  {root}")

    # Cada subcarpeta directa es un mundo, salvo las carpetas reservadas.
    # La fecha corresponde a la carpeta raíz, no al archivo más reciente de su interior.
    worlds = [
        World(
            name=entry.name,
            path=entry,
            size_bytes=directory_size(entry),
            modified_at=datetime.fromtimestamp(entry.stat().st_mtime),
        )
        for entry in root.iterdir()
        if entry.is_dir()
        and not is_backup(entry.name)
        and not is_bifrost_directory(entry.name)
    ]
    return sorted(worlds, key=lambda world: world.name.lower())


def find_world(worlds_path: str | os.PathLike[str], name: str) -> World | None:
    """Busca un mundo local por nombre sin distinguir mayúsculas; devuelve None si no existe."""
    return next((world for world in list_worlds(worlds_path) if world.name.lower() == name.lower()), None)


# ======================================================================================= #
# Backup e instalación
# ======================================================================================= #

def backup_world(worlds_path: str | os.PathLike[str], name: str) -> Path | None:
    """Mueve un mundo local a un backup fechado y devuelve su ruta.

    Devuelve None si no hay un mundo local para respaldar.
    """
    world = find_world(worlds_path, name)

    # Caso 1: No existe el mundo local; no hay nada que respaldar.
    if world is None:
        return None

    # Caso 2: Existe el mundo local; lo aparta de la ruta activa como backup fechado.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = Path(worlds_path) / f"{name}_pre_pull_{timestamp}"
    shutil.move(str(world.path), str(destination))
    return destination


def install_staged_world(
    worlds_path: str | os.PathLike[str], name: str, staged_world: str | os.PathLike[str]
) -> Path | None:
    """Instala un mundo preparado conservando el anterior como backup, si existe.

    Intenta restaurar el original si la instalación falla antes de crear el destino.
    """
    # Aparta el mundo anterior antes de ocupar su ruta con el mundo preparado.
    backup = backup_world(worlds_path, name)
    destination = Path(worlds_path) / name
    try:
        shutil.move(str(staged_world), str(destination))
    except Exception:
        # Error de instalación: intenta recuperar el original si el destino sigue sin existir.
        if backup is not None and not destination.exists():
            shutil.move(str(backup), str(destination))

        # Propaga el fallo de instalación aunque se haya podido restaurar el original.
        raise
    return backup


# ======================================================================================= #
# Copias independientes
# ======================================================================================= #

def save_world_copy(
    worlds_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    sha256: str,
    source_zip: str | os.PathLike[str],
) -> Path:
    """Guarda un ZIP en .bifrost-copies sin modificar el mundo activo ni su base.

    El ZIP debe estar verificado previamente.
    """
    # Adapta el nombre a las restricciones de Windows y limita su longitud.
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", world_name).strip(" .")
    safe_name = safe_name[:80] or "world"

    # Guarda las copias fuera de las carpetas detectadas como mundos activos.
    copies_directory = Path(worlds_path) / COPIES_DIRECTORY_NAME
    copies_directory.mkdir(parents=True, exist_ok=True)
    destination = copies_directory / f"{safe_name}_v{version}_{sha256[:12]}.zip"

    temporary_path: Path | None = None
    try:
        # Prepara la copia en el mismo directorio antes de reemplazar el ZIP de destino.
        with tempfile.NamedTemporaryFile(
            dir=copies_directory,
            prefix=f"{safe_name}_v{version}_",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        shutil.copyfile(source_zip, temporary_path)
        temporary_path.replace(destination)
    finally:
        # Limpia cualquier temporal restante, incluso si falla la copia o el reemplazo.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination

