from dataclasses import dataclass
from typing import cast

from .manifests import validate_manifest_identity
from .models import Manifest, WorldLock, WorldState
from .paths import lock_key, manifest_key, state_key
from .storage import R2Storage
from .world_names import validate_world_name

STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StateSnapshot:
    """Reúne el estado remoto leído, su ETag y si proviene de metadata heredada."""

    value: WorldState
    etag: str | None
    legacy: bool = False


def _validate_state(world_name: str, value: object) -> WorldState:
    """Valida la estructura mínima del estado remoto autoritativo."""
    # Rechaza un documento cuyo esquema no permita interpretar el estado canónico.
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RuntimeError(f"El estado remoto de '{world_name}' no tiene un formato válido.")
    revision = value.get("revision")
    manifest = value.get("manifest")
    world_lock = value.get("lock")
    
    # La revisión debe ser un entero no negativo; los booleanos no representan revisiones.
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise RuntimeError(f"La revisión remota de '{world_name}' no es válida.")
    
    # Comprueba que el manifest presente pertenezca al mundo y use una clave de ZIP admitida.
    if manifest is not None:
        validate_manifest_identity(world_name, manifest)
    
    # Comprueba la estructura del lock remoto, sin validar sus campos internos.
    if world_lock is not None and not isinstance(world_lock, dict):
        raise RuntimeError(f"El lock remoto de '{world_name}' no es válido.")
    
    return cast(WorldState, value)


def read_world_state(storage: R2Storage, world_name: str) -> StateSnapshot:
    """Lee el estado canónico y su ETag, o reconstruye el estado desde metadata heredada.

    La reconstrucción no escribe ni migra objetos remotos.
    """
    validate_world_name(world_name)

    # Consulta el estado canónico si el almacenamiento permite leer JSON con ETag.
    if hasattr(storage, "get_json_with_etag"):
        value, etag = storage.get_json_with_etag(state_key(world_name))
    else:
        value, etag = None, None

    # Caso 1: Existe estado canónico; lo valida y lo usa como fuente autoritativa.
    if value is not None:
        return StateSnapshot(_validate_state(world_name, value), etag)

    # Caso 2: No hay estado canónico disponible; conserva la lectura del protocolo heredado.
    # Caso 2.1: Hay lectura genérica de JSON; consulta las claves heredadas directamente.
    if hasattr(storage, "get_json"):
        manifest = cast(Manifest | None, storage.get_json(manifest_key(world_name)))
        world_lock = cast(WorldLock | None, storage.get_json(lock_key(world_name)))
    # Caso 2.2: Usa los lectores específicos de manifest y lock disponibles.
    else:
        manifest = storage.read_manifest(world_name)
        world_lock = storage.read_lock(world_name) if hasattr(storage, "read_lock") else None

    # Revisa la identidad del manifest heredado antes de usar su versión como revisión.
    if manifest is not None:
        validate_manifest_identity(world_name, manifest)

    # Construye una vista inicial; el primer commit condicional creará el estado canónico.
    revision = manifest["version"] if manifest is not None else 0
    legacy_state: WorldState = {
        "schema_version": STATE_SCHEMA_VERSION,
        "revision": revision,
        "manifest": manifest,
        "lock": world_lock,
    }
    return StateSnapshot(
        _validate_state(world_name, legacy_state), None,
        legacy=manifest is not None or world_lock is not None,
    )


def updated_world_state(
    snapshot: StateSnapshot,
    *,
    manifest: Manifest | None,
    world_lock: WorldLock | None,
) -> WorldState:
    """Construye la siguiente revisión con el manifest y el lock elegidos, sin publicarla."""
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "revision": snapshot.value["revision"] + 1,
        "manifest": manifest,
        "lock": world_lock,
    }


def commit_world_state(
    storage: R2Storage, world_name: str, snapshot: StateSnapshot, value: WorldState
) -> StateSnapshot:
    """Publica el estado solo si la lectura sigue vigente o aún no existe estado canónico.

    Devuelve el estado publicado con su nuevo ETag.
    """
    # Valida el nombre y ambos estados antes de intentar la escritura remota.
    validate_world_name(world_name)
    _validate_state(world_name, snapshot.value)
    _validate_state(world_name, value)

    # Usa el ETag leído para publicar manifest y lock en una misma escritura condicional.
    etag = storage.put_json_conditional(state_key(world_name), value, snapshot.etag)
    return StateSnapshot(value, etag)


