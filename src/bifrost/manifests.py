import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .archives import calculate_sha256
from .models import Manifest
from .paths import current_zip_key, version_prefix, version_upload_zip_key, version_zip_key
from .world_names import validate_world_name


def validate_manifest_identity(world_name: object, value: object) -> Manifest:
    """Comprueba la identidad y la ubicación del ZIP sin modificar la metadata.

    Admite las claves heredadas y versionadas del protocolo para este mismo mundo.
    """
    # Valida los nombres y exige que el manifest declare exactamente el mundo solicitado.
    world_name = validate_world_name(world_name)
    if not isinstance(value, dict):
        raise ValueError(f"El manifest de {world_name!r} no es un objeto válido.")
    declared_name = validate_world_name(value.get("world"))
    if declared_name != world_name:
        raise ValueError(
            f"El manifest de {world_name!r} declara otro mundo: {declared_name!r}."
        )

    # Comprueba la versión y prepara las claves admitidas para ese mundo.
    version = value.get("version")
    prefix = version_prefix(world_name, version)
    filename = value.get("filename")

    # Caso 1: El ZIP usa la clave heredada o histórica sin identificador de subida; acepta el manifest.
    if filename in (current_zip_key(world_name), version_zip_key(world_name, version)):
        return cast(Manifest, value)

    # Caso 2: El ZIP usa una clave de candidato; comprueba su formato e identificador.
    if isinstance(filename, str) and filename.startswith(f"{prefix}/"):
        parts = filename[len(prefix) + 1:].split("/")
        if len(parts) == 2 and parts[1] == "world.zip":
            if filename == version_upload_zip_key(world_name, version, parts[0]):
                return cast(Manifest, value)

    # Error de ubicación: ninguna clave admitida coincide; rechaza el manifest.
    raise ValueError(
        f"El ZIP del manifest de {world_name!r} tiene una ubicación inválida: {filename!r}."
    )


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
    # Comprueba la identidad y la clave del ZIP antes de consultar su contenido o tamaño.
    identity = validate_manifest_identity(
        world_name,
        {
            "world": world_name,
            "version": version,
            "filename": current_zip_key(world_name) if filename is None else filename,
        },
    )
    path = Path(zip_path)

    # Calcula la metadata desde el ZIP terminado; la clave heredada es el destino por defecto.
    return {
        "version": version,
        "world": world_name,
        "filename": identity["filename"],
        "size": path.stat().st_size,
        "sha256": calculate_sha256(path),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save_manifest(manifest: Manifest, destination: str | os.PathLike[str]) -> Path:
    """Guarda un manifest como JSON legible y devuelve la ruta creada."""
    # Rechaza una identidad o ubicación de ZIP inválida antes de escribir el JSON.
    validate_manifest_identity(manifest.get("world"), manifest)

    path = Path(destination)
    path.write_text(json.dumps(manifest, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def next_version(remote_manifest: Manifest | None) -> int:
    """Devuelve la versión siguiente a la remota, o 1 si no hay una publicación previa."""
    return 1 if remote_manifest is None else remote_manifest["version"] + 1
