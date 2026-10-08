"""Restauración remota explícita, sin instalar mundos ni alterar su base local."""

import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from botocore.exceptions import ClientError

from .archives import validate_zip, verify_zip
from .locks import ensure_restore_unlocked
from .manifests import build_manifest, validate_manifest, validate_manifest_identity
from .models import Manifest
from .paths import version_manifest_key, version_upload_zip_key
from .remote_state import (
    STATE_SCHEMA_VERSION,
    StateSnapshot,
    commit_world_state,
    read_world_state,
    updated_world_state,
)
from .storage import ConcurrentUpdateError, R2Storage
from .versions import (
    MAX_PREVIOUS_REMOTE_VERSIONS,
    archive_current_version_conditionally,
    prune_remote_versions,
    read_published_version,
    record_published_version_if_absent,
)
from .world_names import validate_world_name


@dataclass(frozen=True)
class RestorationResult:
    """Informa una publicación confirmada y los fallos de mantenimiento posteriores."""

    manifest: Manifest
    removed_versions: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()


def restore_world_version(
    storage: R2Storage,
    world_name: str,
    historical_version: int,
    player: str,
    *,
    snapshot: StateSnapshot,
) -> RestorationResult:
    """Publica contenido histórico como una nueva versión usando el snapshot recibido.

    El llamador obtiene el snapshot antes de seleccionar y confirmar la restauración.
    No relee el estado para renovar la precondición ni usa la base de un mundo local.
    Los fallos anteriores al commit se propagan; los posteriores se devuelven como avisos.
    """
    validate_world_name(world_name)
    version_manifest_key(world_name, historical_version)
    schema_version = snapshot.value.get("schema_version")
    revision = snapshot.value.get("revision")
    if (
        isinstance(schema_version, bool)
        or schema_version != STATE_SCHEMA_VERSION
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
        or (not snapshot.legacy and (not isinstance(snapshot.etag, str) or not snapshot.etag))
        or (snapshot.legacy and snapshot.etag is not None)
    ):
        raise RuntimeError("El estado leído no permite una publicación condicional segura.")
    current = validate_manifest(world_name, snapshot.value.get("manifest"))
    validate_manifest_identity(world_name, current)
    ensure_restore_unlocked(snapshot.value.get("lock"))
    
    if historical_version >= current["version"]:
        raise RuntimeError("Solo se puede restaurar una versión anterior a la vigente.")
    
    if not isinstance(player, str) or not player.strip():
        raise RuntimeError("El nombre del jugador no es válido.")

    historical = read_published_version(storage, world_name, historical_version)
    
    if historical is None:
        raise RuntimeError("El manifest histórico seleccionado no está disponible.")
    new_version = current["version"] + 1
    
    if read_published_version(storage, world_name, new_version) is not None:
        raise RuntimeError("La siguiente versión ya tiene un registro histórico.")

    with TemporaryDirectory(prefix="bifrost-restore-") as temporary_dir:
        zip_path = Path(temporary_dir) / "world.zip"
        try:
            storage.download_file(historical["filename"], zip_path)
        except ClientError as error:
            if R2Storage._is_not_found(error):
                raise RuntimeError("El ZIP histórico seleccionado no está disponible.") from error
            raise RuntimeError(
                "Falló la descarga remota del ZIP histórico; revisá el acceso a R2."
            ) from error
        if not verify_zip(zip_path, historical["sha256"]):
            raise RuntimeError("El SHA-256 del ZIP histórico no coincide con su manifest.")
        if zip_path.stat().st_size != historical["size"]:
            raise RuntimeError("El tamaño del ZIP histórico no coincide con su manifest.")
        validate_zip(zip_path)

        filename = version_upload_zip_key(world_name, new_version, uuid.uuid4().hex)
        manifest = build_manifest(zip_path, world_name, new_version, player, filename)
        archive_current_version_conditionally(storage, world_name, current)
        try:
            storage.upload_file(zip_path, filename)
        except Exception:
            # La publicación no se intentó: una subida parcial no puede ser la vigente.
            try:
                storage.delete(filename)
            except Exception:
                pass
            raise

        state = updated_world_state(snapshot, manifest=manifest, world_lock=None)
        try:
            commit_world_state(storage, world_name, snapshot, state)
        except ConcurrentUpdateError as error:
            # Solo una precondición fallida confirma que este candidato no se publicó.
            try:
                storage.delete(filename)
            except Exception:
                raise ConcurrentUpdateError(
                    "El estado remoto cambió; no se publicó la restauración. "
                    "No se pudo eliminar su ZIP candidato."
                ) from error
            raise
        except Exception as error:
            # Una respuesta perdida puede ocurrir después del commit: conserva el ZIP.
            raise RuntimeError(
                "No se pudo confirmar la publicación. Consultá el estado remoto antes de "
                "reintentar; se conservó el ZIP candidato."
            ) from error

    try:
        record_published_version_if_absent(storage, world_name, manifest)
    except Exception:
        return RestorationResult(
            manifest,
            warnings=("La restauración se publicó, pero no se pudo registrar su historial.",),
        )
    try:
        # Esta lectura es solo para mantenimiento: nunca renueva el ETag del commit.
        latest = read_world_state(storage, world_name)
        latest_manifest = validate_manifest(world_name, latest.value["manifest"])
        if latest_manifest["version"] < new_version:
            raise RuntimeError("El estado remoto no refleja la publicación confirmada.")
        removed = prune_remote_versions(
            storage,
            world_name,
            keep=MAX_PREVIOUS_REMOTE_VERSIONS + 1,
            current_version=latest_manifest["version"],
        )
    except Exception:
        return RestorationResult(
            manifest,
            warnings=("La restauración se publicó, pero no se pudo completar la retención.",),
        )
    return RestorationResult(manifest, removed_versions=tuple(removed))
