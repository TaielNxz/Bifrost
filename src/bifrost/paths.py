WORLDS_PREFIX = "worlds"


def manifest_key(world_name: str) -> str:
    """Construye la clave remota del manifest de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/manifest.json"


def lock_key(world_name: str) -> str:
    """Construye la clave remota del lock de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/lock.json"


def current_zip_key(world_name: str) -> str:
    """Construye la clave remota del ZIP vigente de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/current/world.zip"


def backup_key(world_name: str, date: str) -> str:
    """Construye la clave remota de un backup fechado de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/backups/{date}.zip"


def world_prefix(world_name: str) -> str:
    """Construye el prefijo remoto que agrupa los objetos de un mundo."""
    return f"{WORLDS_PREFIX}/{world_name}/"
