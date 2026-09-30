from dataclasses import dataclass
from typing import cast

from .models import Manifest, WorldLock, WorldState
from .paths import lock_key, manifest_key, state_key
from .storage import R2Storage

STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StateSnapshot:
    """Representa un estado remoto junto con la versión condicional leída."""

    value: WorldState
    etag: str | None
    legacy: bool = False


def _validate_state(world_name: str, value: object) -> WorldState:
    """Valida la estructura mínima del estado remoto autoritativo."""
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RuntimeError(f"El estado remoto de '{world_name}' no tiene un formato válido.")
    revision = value.get("revision")
    manifest = value.get("manifest")
    world_lock = value.get("lock")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RuntimeError(f"La revisión remota de '{world_name}' no es válida.")
    if manifest is not None and not isinstance(manifest, dict):
        raise RuntimeError(f"El manifest remoto de '{world_name}' no es válido.")
    if world_lock is not None and not isinstance(world_lock, dict):
        raise RuntimeError(f"El lock remoto de '{world_name}' no es válido.")
    return cast(WorldState, value)


def read_world_state(storage: R2Storage, world_name: str) -> StateSnapshot:
    """Lee state.json o construye una vista compatible desde objetos heredados."""
    if hasattr(storage, "get_json_with_etag"):
        value, etag = storage.get_json_with_etag(state_key(world_name))
    else:
        value, etag = None, None
    if value is not None:
        return StateSnapshot(_validate_state(world_name, value), etag)

    if hasattr(storage, "get_json"):
        manifest = cast(Manifest | None, storage.get_json(manifest_key(world_name)))
        world_lock = cast(WorldLock | None, storage.get_json(lock_key(world_name)))
    else:
        manifest = storage.read_manifest(world_name)
        world_lock = storage.read_lock(world_name) if hasattr(storage, "read_lock") else None
    revision = manifest["version"] if manifest is not None else 0
    legacy_state: WorldState = {
        "schema_version": STATE_SCHEMA_VERSION,
        "revision": revision,
        "manifest": manifest,
        "lock": world_lock,
    }
    return StateSnapshot(legacy_state, None, legacy=manifest is not None or world_lock is not None)


def updated_world_state(
    snapshot: StateSnapshot,
    *,
    manifest: Manifest | None,
    world_lock: WorldLock | None,
) -> WorldState:
    """Construye la siguiente revisión de un estado remoto leído."""
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "revision": snapshot.value["revision"] + 1,
        "manifest": manifest,
        "lock": world_lock,
    }


def commit_world_state(
    storage: R2Storage, world_name: str, snapshot: StateSnapshot, value: WorldState
) -> StateSnapshot:
    """Publica un nuevo estado mediante compare-and-swap por ETag."""
    etag = storage.put_json_conditional(state_key(world_name), value, snapshot.etag)
    return StateSnapshot(value, etag)


