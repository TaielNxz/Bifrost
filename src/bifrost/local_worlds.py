import os
import shutil
from datetime import datetime
from pathlib import Path

from .models import World


def is_backup(name: str) -> bool:
    return "_backup_" in name or "_pre_pull_" in name


def directory_size(directory: str | os.PathLike[str]) -> int:
    total = 0
    for current_dir, _, files in os.walk(directory):
        for filename in files:
            try:
                total += (Path(current_dir) / filename).stat().st_size
            except OSError:
                pass
    return total


def list_worlds(worlds_path: str | os.PathLike[str]) -> list[World]:
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
        if entry.is_dir() and not is_backup(entry.name)
    ]
    return sorted(worlds, key=lambda world: world.name.lower())


def find_world(worlds_path: str | os.PathLike[str], name: str) -> World | None:
    return next((world for world in list_worlds(worlds_path) if world.name.lower() == name.lower()), None)


def backup_world(worlds_path: str | os.PathLike[str], name: str) -> Path | None:
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

