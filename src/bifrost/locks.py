import socket
from datetime import datetime, timedelta, timezone

from .manifests import parse_iso_datetime
from .models import WorldLock
from .storage import R2Storage

LOCK_DURATION_HOURS = 12


def is_expired(world_lock: WorldLock, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(timezone.utc)
    return current_time > parse_iso_datetime(world_lock["expires_at"])


def build_lock(
    player: str,
    machine: str | None = None,
    now: datetime | None = None,
    duration_hours: int = LOCK_DURATION_HOURS,
) -> WorldLock:
    acquired_at = now or datetime.now(timezone.utc)
    expires_at = acquired_at + timedelta(hours=duration_hours)
    return {
        "player": player,
        "machine": machine or socket.gethostname(),
        "acquired_at": acquired_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def active_lock(storage: R2Storage, world_name: str) -> WorldLock | None:
    world_lock = storage.read_lock(world_name)
    if world_lock is None or is_expired(world_lock):
        return None
    return world_lock


def acquire_lock(storage: R2Storage, world_name: str, player: str) -> WorldLock:
    world_lock = build_lock(player)
    storage.write_lock(world_name, world_lock)
    return world_lock


def release_lock(storage: R2Storage, world_name: str) -> None:
    storage.delete_lock(world_name)

