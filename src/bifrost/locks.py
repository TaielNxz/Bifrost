import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import cast

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


def ensure_restore_unlocked(world_lock: object, now: datetime | None = None) -> None:
    """Impide restaurar con cualquier lock activo o con datos de lock inválidos.

    Admite locks heredados sin sesión ni versión base, pero valida los campos presentes.
    La propiedad del lock no habilita una excepción para la restauración global.
    """
    
    # Si no hay lock remoto, no hay bloqueo que impediría la restauración.
    if world_lock is None:
        return

    invalid_message = "El lock remoto no es válido; no se puede restaurar el mundo."
    
    # Si el lock remoto no es un diccionario, no se puede validar ni usar.
    if not isinstance(world_lock, dict):
        raise RuntimeError(invalid_message)
    
    # Si el lock remoto no tiene los campos de jugador y máquina, no se puede validar ni usar.
    for field in ("player", "machine"):
        value = world_lock.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(invalid_message)

    # Almacena las fechas de adquisición y vencimiento para compararlas después.
    dates = []
    for field in ("acquired_at", "expires_at"):
        
        # Verifica que las fechas sean cadenas ISO 8601 válidas y que la fecha de vencimiento sea posterior a la de adquisición.
        value = world_lock.get(field)
        try:
            date = parse_iso_datetime(value) if isinstance(value, str) else None
        except ValueError as error:
            raise RuntimeError(invalid_message) from error
        
        # Verifica que la fecha sea UTC y no tenga desplazamiento horario.
        if date is None or date.utcoffset() != timezone.utc.utcoffset(None):
            raise RuntimeError(invalid_message)
        
        dates.append(date)
    
    # Verifica que la fecha de vencimiento sea posterior a la de adquisición.
    if dates[1] < dates[0]:
        raise RuntimeError(invalid_message)

    # Verifica que el ID de sesión sea una cadena no vacía.
    if "session_id" in world_lock:
        session_id = world_lock["session_id"]
        if not isinstance(session_id, str) or not session_id.strip():
            raise RuntimeError(invalid_message)
    
    # Verifica que la versión base sea un entero positivo si está presente.
    if "base_version" in world_lock:
        version = world_lock["base_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise RuntimeError(invalid_message)

    # Si el lock remoto no expiró, no se puede restaurar el mundo.
    if not is_expired(cast(WorldLock, world_lock), now):
        raise RuntimeError("Hay un lock de hosting activo; no se puede restaurar el mundo.")
