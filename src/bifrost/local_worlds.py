import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .models import World

COPIES_DIRECTORY_NAME = ".bifrost-copies"


def is_backup(name: str) -> bool:
    """Indica si el nombre corresponde a una carpeta de backup local."""
    return "_backup_" in name or "_pre_pull_" in name


def is_bifrost_directory(name: str) -> bool:
    """Indica si una carpeta pertenece al estado interno de Bifröst."""
    return name == COPIES_DIRECTORY_NAME


def directory_size(directory: str | os.PathLike[str]) -> int:
    """Calcula en bytes el tamaño acumulado de los archivos de una carpeta."""
    total = 0
    for current_dir, _, files in os.walk(directory):
        for filename in files:
            try:
                total += (Path(current_dir) / filename).stat().st_size
            except OSError:
                pass
    return total


def list_worlds(worlds_path: str | os.PathLike[str]) -> list[World]:
    """Lista los mundos locales, omitiendo las carpetas identificadas como backups."""
    root = Path(worlds_path)
    if not root.is_dir():
        raise RuntimeError(f"La carpeta de mundos no existe:\n  {root}")

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
    """Busca un mundo local por nombre sin distinguir mayúsculas de minúsculas."""
    return next((world for world in list_worlds(worlds_path) if world.name.lower() == name.lower()), None)


def backup_world(worlds_path: str | os.PathLike[str], name: str) -> Path | None:
    """Mueve un mundo local a una carpeta de backup con fecha y devuelve su ruta."""
    world = find_world(worlds_path, name)
    if world is None:
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = Path(worlds_path) / f"{name}_pre_pull_{timestamp}"
    shutil.move(str(world.path), str(destination))
    return destination


def install_staged_world(
    worlds_path: str | os.PathLike[str], name: str, staged_world: str | os.PathLike[str]
) -> Path | None:
    """Reemplaza un mundo preparado y restaura el anterior si falla el movimiento final."""
    backup = backup_world(worlds_path, name)
    destination = Path(worlds_path) / name
    try:
        shutil.move(str(staged_world), str(destination))
    except Exception:
        if backup is not None and not destination.exists():
            shutil.move(str(backup), str(destination))
        raise
    return backup


def save_world_copy(
    worlds_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    sha256: str,
    source_zip: str | os.PathLike[str],
) -> Path:
    """Guarda un ZIP verificado como copia independiente del mundo activo."""
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", world_name).strip(" .")
    safe_name = safe_name[:80] or "world"
    copies_directory = Path(worlds_path) / COPIES_DIRECTORY_NAME
    copies_directory.mkdir(parents=True, exist_ok=True)
    destination = copies_directory / f"{safe_name}_v{version}_{sha256[:12]}.zip"

    temporary_path: Path | None = None
    try:
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
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination

