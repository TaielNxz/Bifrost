import socket
import uuid
from datetime import datetime, timedelta, timezone

from .manifests import parse_iso_datetime
from .models import WorldLock

LOCK_DURATION_HOURS = 12


def is_expired(world_lock: WorldLock, now: datetime | None = None) -> bool:
    """Indica si un lock ya superó su fecha de vencimiento."""
    current_time = now or datetime.now(timezone.utc)
    return current_time > parse_iso_datetime(world_lock["expires_at"])


def build_lock(
    player: str,
    machine: str | None = None,
    now: datetime | None = None,
    duration_hours: int = LOCK_DURATION_HOURS,
    session_id: str | None = None,
    base_version: int | None = None,
) -> WorldLock:
    """Construye un lock con jugador, sesión y vencimiento, sin guardarlo remotamente."""
    # Calcula el vencimiento desde la fecha elegida; por defecto usa la hora UTC actual.
    acquired_at = now or datetime.now(timezone.utc)
    expires_at = acquired_at + timedelta(hours=duration_hours)
    world_lock: WorldLock = {
        "player": player,
        "machine": machine or socket.gethostname(),
        "acquired_at": acquired_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id or uuid.uuid4().hex,
    }

    # Vincula el lock a una versión base solo cuando se indicó una.
    if base_version is not None:
        world_lock["base_version"] = base_version
    return world_lock


def active_lock_value(world_lock: WorldLock | None) -> WorldLock | None:
    """Devuelve el lock recibido solamente cuando existe y no expiró."""
    return None if world_lock is None or is_expired(world_lock) else world_lock

