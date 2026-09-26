WORLDS_PREFIX = "worlds"


def manifest_key(world_name: str) -> str:
    return f"{WORLDS_PREFIX}/{world_name}/manifest.json"


def lock_key(world_name: str) -> str:
    return f"{WORLDS_PREFIX}/{world_name}/lock.json"


def current_zip_key(world_name: str) -> str:
    return f"{WORLDS_PREFIX}/{world_name}/current/world.zip"


def backup_key(world_name: str, date: str) -> str:
    return f"{WORLDS_PREFIX}/{world_name}/backups/{date}.zip"


def world_prefix(world_name: str) -> str:
    return f"{WORLDS_PREFIX}/{world_name}/"
