WORLDS_PREFIX = "worlds"


def state_key(world_name: str) -> str:
    """Construye la clave del estado remoto autoritativo de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/state.json"


def manifest_key(world_name: str) -> str:
    """Construye la clave remota del manifest de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/manifest.json"


def lock_key(world_name: str) -> str:
    """Construye la clave remota del lock de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/lock.json"


def current_zip_key(world_name: str) -> str:
    """Construye la clave remota del ZIP vigente de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/current/world.zip"


def versions_prefix(world_name: str) -> str:
    """Construye el prefijo remoto del historial de versiones de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/versions"


def version_prefix(world_name: str, version: int) -> str:
    """Construye el prefijo remoto de una versión histórica."""
    return f"{versions_prefix(world_name)}/{version}"


def version_zip_key(world_name: str, version: int) -> str:
    """Construye la clave del ZIP de una versión histórica."""
    return f"{version_prefix(world_name, version)}/world.zip"


def version_upload_zip_key(world_name: str, version: int, upload_id: str) -> str:
    """Construye una clave inmutable y única para un ZIP candidato."""
    return f"{version_prefix(world_name, version)}/{upload_id}/world.zip"


def version_manifest_key(world_name: str, version: int) -> str:
    """Construye la clave del manifest de una versión histórica."""
    return f"{version_prefix(world_name, version)}/manifest.json"


def backup_key(world_name: str, date: str) -> str:
    """Construye la clave remota de un backup fechado de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/backups/{date}.zip"


def world_prefix(world_name: str) -> str:
    """Construye el prefijo remoto que agrupa los objetos de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/"
