from typing import cast

from .models import Manifest
from .paths import (
    current_zip_key,
    version_manifest_key,
    version_zip_key,
    versions_prefix,
)
from .storage import R2Storage

MAX_PREVIOUS_REMOTE_VERSIONS = 5


def archive_current_version(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> bool:
    """Archiva el ZIP y manifest vigentes sin sobrescribir un snapshot válido."""
    version = manifest["version"]
    manifest_key = version_manifest_key(world_name, version)
    archived = storage.get_json(manifest_key)
    if archived is not None:
        if archived.get("version") == version and archived.get("sha256") == manifest["sha256"]:
            return False
        raise RuntimeError(
            f"La versión histórica {version} de '{world_name}' ya existe con otro hash."
        )

    if manifest["filename"] == current_zip_key(world_name):
        zip_key = version_zip_key(world_name, version)
        storage.copy(current_zip_key(world_name), zip_key)
    else:
        zip_key = manifest["filename"]
    archived_manifest = cast(Manifest, {**manifest, "filename": zip_key})
    storage.put_json(manifest_key, archived_manifest)
    return True


def record_published_version(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> None:
    """Registra el manifest auxiliar de una versión publicada inmutable."""
    key = version_manifest_key(world_name, manifest["version"])
    existing = storage.get_json(key)
    if existing is not None and existing.get("sha256") != manifest["sha256"]:
        raise RuntimeError(
            f"La versión histórica {manifest['version']} de '{world_name}' tiene otro hash."
        )
    storage.put_json(key, manifest)


def _version_from_key(world_name: str, key: str) -> int | None:
    """Extrae el número de versión de una clave histórica válida."""
    prefix = f"{versions_prefix(world_name)}/"
    if not key.startswith(prefix):
        return None
    segment = key[len(prefix) :].partition("/")[0]
    if not segment.isdigit():
        return None
    return int(segment)


def prune_remote_versions(
    storage: R2Storage,
    world_name: str,
    keep: int = MAX_PREVIOUS_REMOTE_VERSIONS,
) -> list[int]:
    """Elimina las versiones históricas más antiguas y devuelve sus números."""
    if keep < 1:
        raise ValueError("La cantidad de versiones remotas a conservar debe ser positiva.")
    prefix = f"{versions_prefix(world_name)}/"
    keys = storage.list_keys(prefix)
    versions = sorted(
        {
            version
            for key in keys
            if (version := _version_from_key(world_name, key)) is not None
        }
    )
    removed = versions[: max(0, len(versions) - keep)]
    removed_set = set(removed)
    for key in keys:
        if _version_from_key(world_name, key) in removed_set:
            storage.delete(key)
    return removed
