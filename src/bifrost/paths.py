from .world_names import validate_world_name

WORLDS_PREFIX = "worlds"


def state_key(world_name: str) -> str:
    """Construye la clave del estado remoto autoritativo de un mundo."""
    return f"{world_prefix(world_name)}state.json"


def manifest_key(world_name: str) -> str:
    """Construye la clave del manifest heredado, usado cuando no existe estado canónico."""
    return f"{world_prefix(world_name)}manifest.json"


def lock_key(world_name: str) -> str:
    """Construye la clave del lock heredado, usado cuando no existe estado canónico."""
    return f"{world_prefix(world_name)}lock.json"


def current_zip_key(world_name: str) -> str:
    """Construye la clave heredada del ZIP vigente, anterior al uso de claves versionadas."""
    return f"{world_prefix(world_name)}current/world.zip"


def versions_prefix(world_name: str) -> str:
    """Construye el prefijo remoto del historial de versiones de un mundo."""
    return f"{world_prefix(world_name)}versions"


def version_prefix(world_name: str, version: int) -> str:
    """Construye el prefijo remoto de una versión histórica."""
    prefix = versions_prefix(world_name)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("La versión remota debe ser un entero positivo.")
    return f"{prefix}/{version}"


def version_zip_key(world_name: str, version: int) -> str:
    """Construye la clave del ZIP de una versión histórica."""
    return f"{version_prefix(world_name, version)}/world.zip"


def version_upload_zip_key(world_name: str, version: int, upload_id: str) -> str:
    """Construye la clave de un ZIP versionado, diferenciada por identificador de subida."""
    prefix = version_prefix(world_name, version)

    # Aplica las restricciones de nombres para impedir segmentos adicionales en la clave.
    validate_world_name(upload_id)
    return f"{prefix}/{upload_id}/world.zip"


def version_manifest_key(world_name: str, version: int) -> str:
    """Construye la clave del manifest de una versión histórica."""
    return f"{version_prefix(world_name, version)}/manifest.json"


def backup_key(world_name: str, date: str) -> str:
    """Construye la clave reservada para un backup remoto fechado, sin crearlo."""
    prefix = world_prefix(world_name)

    # Usa la fecha como un único segmento de clave, sin interpretar su formato.
    validate_world_name(date)
    return f"{prefix}backups/{date}.zip"


def world_prefix(world_name: str) -> str:
    """Valida el nombre y construye el prefijo remoto que agrupa los objetos de un mundo."""
    return f"{WORLDS_PREFIX}/{validate_world_name(world_name)}/"
