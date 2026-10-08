import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .archives import calculate_sha256
from .models import Manifest
from .paths import current_zip_key, version_prefix


def parse_iso_datetime(value: str) -> datetime:
    """Interpreta una fecha ISO 8601, admitiendo la terminación Z para UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_manifest(world_name: str, value: object) -> Manifest:
    """Valida la metadata y la ubicación de un ZIP publicado para el mundo indicado.

    Admite la clave vigente heredada y las claves versionadas, y devuelve una copia con el hash
    en minúsculas. No comprueba la existencia ni el contenido del ZIP.
    """
    if not isinstance(value, dict):
        raise RuntimeError(f"El manifest remoto de '{world_name}' no tiene un formato válido.")

    # Comprueba los datos necesarios para identificar y presentar una publicación.
    version = value.get("version")
  
    # Comprueba que la versión sea un entero positivo.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RuntimeError(f"La versión del manifest de '{world_name}' no es válida.")
    
    # Comprueba que el mundo coincida con el manifest.
    if value.get("world") != world_name:
        raise RuntimeError(f"El manifest remoto no corresponde al mundo '{world_name}'.")
    
    # Comprueba que el tamaño sea un entero no negativo.
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise RuntimeError(f"El tamaño del manifest de '{world_name}' no es válido.")
    
    # Comprueba que el autor sea una cadena no vacía.
    uploaded_by = value.get("uploaded_by")
    if not isinstance(uploaded_by, str) or not uploaded_by.strip():
        raise RuntimeError(f"El autor del manifest de '{world_name}' no es válido.")

    # Comprueba que el hash SHA-256 sea una cadena hexadecimal de 64 caracteres.
    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
        raise RuntimeError(f"El SHA-256 del manifest de '{world_name}' no es válido.")
    
    # Comprueba que la fecha sea una cadena ISO 8601 con zona UTC.
    uploaded_at = value.get("uploaded_at")
    try:
        date = parse_iso_datetime(uploaded_at) if isinstance(uploaded_at, str) else None
    except ValueError as error:
        raise RuntimeError(f"La fecha del manifest de '{world_name}' no es válida.") from error
    
    # Comprueba que la fecha sea UTC.
    if date is None or date.utcoffset() != timezone.utc.utcoffset(None):
        raise RuntimeError(f"La fecha del manifest de '{world_name}' debe indicar UTC.")

    # Comprueba que la clave del ZIP sea una cadena y que coincida con la versión.
    filename = value.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError(f"La clave del ZIP de '{world_name}' no es válida.")
    
    # Comprueba que la clave del ZIP coincida con la versión, salvo que sea la clave heredada vigente.
    if filename != current_zip_key(world_name):
        pattern = re.escape(version_prefix(world_name, version)) + (
            r"/(?:(?P<upload_id>[^/\\\x00-\x1f]+)/)?world\.zip"
        )
        match = re.fullmatch(pattern, filename)
        if match is None or match["upload_id"] in {".", ".."}:
            raise RuntimeError(f"La clave del ZIP de '{world_name}' no corresponde a su versión.")

    return cast(Manifest, {**value, "sha256": sha256.lower()})


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
