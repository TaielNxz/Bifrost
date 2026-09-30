import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .archives import calculate_sha256
from .models import Manifest
from .paths import current_zip_key


def parse_iso_datetime(value: str) -> datetime:
    """Convierte una fecha ISO 8601, incluida la terminación Z, a datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_manifest(
    zip_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    uploaded_by: str,
    filename: str | None = None,
) -> Manifest:
    """Construye el manifest de una versión local lista para publicar."""
    path = Path(zip_path)
    return {
        "version": version,
        "world": world_name,
        "filename": filename or current_zip_key(world_name),
        "size": path.stat().st_size,
        "sha256": calculate_sha256(path),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save_manifest(manifest: Manifest, destination: str | os.PathLike[str]) -> Path:
    """Guarda un manifest como JSON legible y devuelve la ruta creada."""
    path = Path(destination)
    path.write_text(json.dumps(manifest, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def next_version(remote_manifest: Manifest | None) -> int:
    """Calcula el siguiente número de versión a partir del manifest remoto."""
    return 1 if remote_manifest is None else remote_manifest["version"] + 1
