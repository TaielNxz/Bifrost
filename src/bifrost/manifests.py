import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .archives import calculate_sha256
from .models import Manifest
from .paths import current_zip_key


def parse_iso_datetime(value: str) -> datetime:
    """Interpreta una fecha ISO 8601, admitiendo la terminación Z para UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_manifest(
    zip_path: str | os.PathLike[str],
    world_name: str,
    version: int,
    uploaded_by: str,
    filename: str | None = None,
) -> Manifest:
    """Construye el manifest de un ZIP con tamaño, SHA-256, autor y fecha UTC.

    No publica el ZIP ni el manifest.
    """
    path = Path(zip_path)

    # Calcula la metadata desde el ZIP terminado; la clave heredada es el destino por defecto.
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
    """Devuelve la versión siguiente a la remota, o 1 si no hay una publicación previa."""
    return 1 if remote_manifest is None else remote_manifest["version"] + 1
