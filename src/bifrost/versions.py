from typing import cast

from .manifests import validate_manifest_identity
from .models import Manifest
from .paths import (
    current_zip_key,
    version_manifest_key,
    version_zip_key,
    versions_prefix,
)
from .storage import R2Storage

MAX_PREVIOUS_REMOTE_VERSIONS = 5


def read_version_manifest(
    storage: R2Storage, world_name: str, version: int
) -> Manifest | None:
    """Lee un manifest histórico y comprueba que pertenezca al mundo y versión solicitados.

    Devuelve None si no existe el registro.
    """
    value = storage.get_json(version_manifest_key(world_name, version))

    # Caso 1: No hay un manifest histórico; informa la ausencia del registro.
    if value is None:
        return None

    # Caso 2: Hay un manifest histórico; valida su identidad y la versión declarada.
    manifest = validate_manifest_identity(world_name, value)

    # Conflicto de versión: rechaza un manifest que no corresponda a la clave consultada.
    if manifest["version"] != version:
        raise ValueError(
            f"El manifest histórico de {world_name!r}, versión {version}, "
            f"declara la versión {manifest['version']!r}."
        )
    return manifest


def archive_current_version(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> bool:
    """Registra la versión vigente en el historial y preserva su ZIP heredado si hace falta.

    Devuelve False si ya hay un manifest con la misma versión y hash, y rechaza conflictos.
    """
    # Valida la identidad antes de consultar el historial o copiar el ZIP vigente.
    validate_manifest_identity(world_name, manifest)
    version = manifest["version"]
    manifest_key = version_manifest_key(world_name, version)
    archived = read_version_manifest(storage, world_name, version)

    # Caso 1: Ya hay un manifest histórico; comprueba si corresponde a la misma versión.
    if archived is not None:
        # Caso 1.1: La versión y el hash coinciden; conserva el registro existente.
        if archived.get("version") == version and archived.get("sha256") == manifest["sha256"]:
            return False

        # Caso 1.2: El registro difiere; bloquea la sobrescritura del historial.
        raise RuntimeError(
            f"La versión histórica {version} de '{world_name}' ya existe con otro hash."
        )

    # Caso 2: El ZIP usa la clave heredada mutable; lo copia a la ruta histórica.
    if manifest["filename"] == current_zip_key(world_name):
        zip_key = version_zip_key(world_name, version)
        storage.copy(current_zip_key(world_name), zip_key)
    # Caso 3: El ZIP no usa la clave heredada; conserva la ubicación indicada sin copiarlo.
    else:
        zip_key = manifest["filename"]

    # Publica el manifest histórico después de preservar el ZIP al que apunta.
    archived_manifest = cast(Manifest, {**manifest, "filename": zip_key})
    storage.put_json(manifest_key, archived_manifest)
    return True


def record_published_version(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> None:
    """Guarda el manifest histórico de una versión ya publicada.

    Rechaza un registro existente con un hash distinto.
    """
    # Valida la identidad antes de consultar o escribir el registro histórico.
    validate_manifest_identity(world_name, manifest)
    key = version_manifest_key(world_name, manifest["version"])
    existing = read_version_manifest(storage, world_name, manifest["version"])

    # Conflicto: bloquea el reemplazo de un manifest histórico con otro hash.
    if existing is not None and existing.get("sha256") != manifest["sha256"]:
        raise RuntimeError(
            f"La versión histórica {manifest['version']} de '{world_name}' tiene otro hash."
        )
    storage.put_json(key, manifest)


def _version_from_key(world_name: str, key: str) -> int | None:
    """Extrae la versión numérica de una clave del historial del mundo.

    Devuelve None si el prefijo o el segmento de versión no corresponden.
    """
    prefix = f"{versions_prefix(world_name)}/"
    if not key.startswith(prefix):
        return None

    # Reconoce versiones ASCII positivas en el primer segmento; el resto identifica sus objetos.
    segment = key[len(prefix) :].partition("/")[0]
    if not segment.isascii() or not segment.isdigit() or int(segment) < 1:
        return None
    return int(segment)


def prune_remote_versions(
    storage: R2Storage,
    world_name: str,
    keep: int = MAX_PREVIOUS_REMOTE_VERSIONS,
) -> list[int]:
    """Conserva las versiones más recientes y elimina los objetos de las restantes.

    Devuelve los números de versión eliminados.
    """
    if keep < 1:
        raise ValueError("La cantidad de versiones remotas a conservar debe ser positiva.")

    # Agrupa las claves por versión para contar cada versión una sola vez.
    prefix = f"{versions_prefix(world_name)}/"
    keys = storage.list_keys(prefix)
    versions = sorted(
        {
            version
            for key in keys
            if (version := _version_from_key(world_name, key)) is not None
        }
    )

    # Selecciona las versiones más antiguas que exceden el límite de retención.
    removed = versions[: max(0, len(versions) - keep)]
    removed_set = set(removed)

    # Elimina todos sus objetos, incluidos ZIP candidatos y manifests históricos.
    for key in keys:
        if _version_from_key(world_name, key) in removed_set:
            storage.delete(key)
    return removed
