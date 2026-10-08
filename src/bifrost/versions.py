import json
import re
import uuid
from typing import cast

from .manifests import validate_manifest
from .manifests import validate_manifest_identity
from .models import Manifest
from .paths import (
    current_zip_key,
    version_manifest_key,
    version_upload_zip_key,
    version_zip_key,
    versions_prefix,
)
from .storage import ConcurrentUpdateError, R2Storage

MAX_PREVIOUS_REMOTE_VERSIONS = 5


def list_previous_versions(
    storage: R2Storage, world_name: str, current_manifest: Manifest | None
) -> list[Manifest]:
    """Lista publicaciones anteriores a la vigente, de la más reciente a la más antigua.

    Usa el manifest vigente ya leído y exige registros históricos válidos con ZIP versionado.
    La consulta no escribe objetos ni verifica todavía la existencia o integridad de los ZIP.
    """
    # Caso 1: No hay publicación vigente; no deduce versiones publicadas a partir del historial.
    if current_manifest is None:
        return []

    # Caso 2: Hay publicación vigente; la valida antes de consultar versiones anteriores.
    current = validate_manifest(world_name, current_manifest)

    # Solo los manifests históricos exactos identifican publicaciones; los ZIP sueltos no.
    prefix = f"{versions_prefix(world_name)}/"
    pattern = re.escape(prefix) + r"([1-9][0-9]*)/manifest\.json"
    records: set[tuple[int, str]] = set()
    for key in storage.list_keys(prefix):
        match = re.fullmatch(pattern, key)
        if match is not None:
            version = int(match[1])
            if version < current["version"]:
                records.add((version, key))

    # Lee de mayor a menor versión; un registro inválido impide devolver un listado parcial.
    manifests: list[Manifest] = []
    for version, key in sorted(records, reverse=True):
        try:
            value = storage.get_json(key)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            # Error de interpretación: conserva la causa y detiene la consulta del historial.
            raise RuntimeError(
                f"No se pudo interpretar la versión histórica {version} de '{world_name}'."
            ) from error

        # Error de disponibilidad: un registro listado que desapareció no equivale a historial vacío.
        if value is None:
            raise RuntimeError(
                f"El manifest histórico {version} de '{world_name}' no está disponible."
            )

        # Valida la metadata antes de comprobar su correspondencia con la clave histórica.
        manifest = validate_manifest(world_name, value)

        # Conflicto de historial: rechaza otra versión o una referencia al ZIP vigente mutable.
        if manifest["version"] != version or manifest["filename"] == current_zip_key(world_name):
            raise RuntimeError(
                f"El manifest histórico {version} de '{world_name}' no corresponde a su versión."
            )
        manifests.append(manifest)
    return manifests

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
    *,
    current_version: int | None = None,
) -> list[int]:
    """Conserva las versiones más recientes y elimina los objetos de las restantes.

    Devuelve los números de versión eliminados. Con current_version cuenta solo registros
    publicados hasta esa versión, protege la vigente e ignora candidatos sin manifest.
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

    if current_version is not None:
        version_manifest_key(world_name, current_version)
        versions = sorted(
            {current_version}
            | {
                version
                for key in keys
                if (version := _version_from_key(world_name, key)) is not None
                and version <= current_version
                and key == version_manifest_key(world_name, version)
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


def read_published_version(
    storage: R2Storage, world_name: str, version: int
) -> Manifest | None:
    """Lee y valida un registro histórico completo, diferenciando ausencia de JSON null."""
    
    # Valida la identidad antes de consultar el registro histórico.
    key = version_manifest_key(world_name, version)
    try:
        value, etag = storage.get_json_with_etag(key)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("No se pudo interpretar el manifest histórico.") from error
    
    # Caso 1: No hay registro histórico; informa la ausencia del manifest.
    if value is None and etag is None:
        return None

    # Caso 2: Hay registro histórico; valida su identidad y la versión declarada.
    manifest = validate_manifest(world_name, value)
    validate_manifest_identity(world_name, manifest)
    
    # Conflicto de versión: rechaza un manifest que no corresponda a la clave consultada.
    if manifest["version"] != version or manifest["filename"] == current_zip_key(world_name):
        raise RuntimeError("El manifest histórico no corresponde a un ZIP de su versión.")
    return manifest


def _same_publication(first: Manifest, second: Manifest) -> bool:
    """Compara la publicación, permitiendo otra ubicación del ZIP preservado."""
    return all(
        first[field] == second[field]
        for field in ("world", "version", "size", "sha256", "uploaded_by", "uploaded_at")
    )


def record_published_version_if_absent(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> bool:
    """Crea un registro histórico sin sobrescribirlo, incluso ante escritores concurrentes.

    Devuelve False si otra operación ya registró la misma publicación.
    """
    manifest = validate_manifest(world_name, manifest)
    validate_manifest_identity(world_name, manifest)
    
    # Rechaza un registro existente con un hash distinto; no sobrescribe el historial.
    if manifest["filename"] == current_zip_key(world_name):
        raise RuntimeError("El historial requiere un ZIP versionado.")
    version = manifest["version"]
    
    try:
        storage.put_json_conditional(version_manifest_key(world_name, version), manifest, None)
    except ConcurrentUpdateError as error:
        existing = read_published_version(storage, world_name, version)
        if existing is not None and _same_publication(existing, manifest):
            return False
        raise RuntimeError(
            f"La versión histórica {version} ya existe con otra publicación."
        ) from error
    return True


def archive_current_version_conditionally(
    storage: R2Storage, world_name: str, manifest: Manifest
) -> bool:
    """Preserva la publicación vigente con un registro de creación condicional.

    Si el ZIP vigente es heredado, lo copia a una clave única antes de registrar el historial.
    Una respuesta remota incierta puede dejar esa copia huérfana; nunca borra un ZIP que podría
    haber quedado referenciado por un registro creado.
    """
    manifest = validate_manifest(world_name, manifest)
    validate_manifest_identity(world_name, manifest)
    
    # Rechaza un registro existente con un hash distinto; no sobrescribe el historial.
    existing = read_published_version(storage, world_name, manifest["version"])
    if existing is not None:
        if _same_publication(existing, manifest):
            return False
        raise RuntimeError("El historial de la versión vigente tiene otra publicación.")

    # Copia el ZIP vigente a una clave única antes de registrar el historial.
    if manifest["filename"] == current_zip_key(world_name):
        filename = version_upload_zip_key(world_name, manifest["version"], uuid.uuid4().hex)
        storage.copy(manifest["filename"], filename)
        manifest = cast(Manifest, {**manifest, "filename": filename})
    
    return record_published_version_if_absent(storage, world_name, manifest)
