import json
import tempfile
from pathlib import Path
from typing import Any

from .models import LocalBase

STATE_FILENAME = ".bifrost-state.json"
STATE_SCHEMA_VERSION = 1


def _state_path(worlds_path: str | Path) -> Path:
    """Devuelve la ruta del archivo que registra las versiones base locales."""
    return Path(worlds_path) / STATE_FILENAME


def _empty_state() -> dict[str, Any]:
    """Construye un documento de estado local vacío."""
    return {"schema_version": STATE_SCHEMA_VERSION, "worlds": {}}


def _validate_base(world_name: str, value: object) -> LocalBase:
    """Valida la versión, el hash y la sesión opcional de una base local.

    Devuelve la base con el hash en minúsculas.
    """
    # Rechaza una estructura inválida antes de consultar los campos de la base.
    if not isinstance(value, dict):
        raise RuntimeError(f"El estado local de '{world_name}' no es válido.")
    version = value.get("version")
    sha256 = value.get("sha256")
    session_id = value.get("session_id")

    # Exige una versión positiva y un SHA-256 hexadecimal completo.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RuntimeError(f"La versión base local de '{world_name}' no es válida.")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        raise RuntimeError(f"El SHA-256 base local de '{world_name}' no es válido.")

    # Una sesión ausente es válida; una sesión presente debe tener un identificador no vacío.
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        raise RuntimeError(f"La sesión local de '{world_name}' no es válida.")

    # Normaliza la base sin agregar una sesión que no estaba registrada.
    base: LocalBase = {"version": version, "sha256": sha256.lower()}
    if session_id is not None:
        base["session_id"] = session_id
    return base


def _load_state(worlds_path: str | Path) -> dict[str, Any]:
    """Carga y valida el estado local, o devuelve uno vacío si el archivo no existe."""
    path = _state_path(worlds_path)

    # Caso 1: No existe un estado local; permite iniciar el registro de bases.
    if not path.exists():
        return _empty_state()

    # Caso 2: Existe un estado local; lo lee y valida antes de permitir su uso.
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        # Error de lectura: no trata un estado ilegible como si fuera un registro vacío.
        raise RuntimeError(f"No se pudo leer el estado local de Bifröst: {path}") from error

    # Comprueba el esquema y la lista de mundos antes de validar cada base individual.
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RuntimeError(f"El formato del estado local de Bifröst no es válido: {path}")
    worlds = value.get("worlds")
    if not isinstance(worlds, dict) or any(not isinstance(name, str) for name in worlds):
        raise RuntimeError(f"La lista de mundos del estado local no es válida: {path}")
    for name, base in worlds.items():
        _validate_base(name, base)
    return value


def read_base_version(worlds_path: str | Path, world_name: str) -> LocalBase | None:
    """Busca la base local por nombre sin distinguir mayúsculas, incluida su sesión opcional.

    Devuelve None si el mundo no tiene una base registrada.
    """
    worlds = _load_state(worlds_path)["worlds"]
    for stored_name, value in worlds.items():
        # Caso 1: Encuentra el mundo; devuelve su base validada y normalizada.
        if stored_name.casefold() == world_name.casefold():
            return _validate_base(stored_name, value)

    # Caso 2: No hay una base para ese mundo; informa su ausencia.
    return None


def save_base_version(
    worlds_path: str | Path,
    world_name: str,
    version: int,
    sha256: str,
    session_id: str | None = None,
) -> LocalBase:
    """Guarda atómicamente la base de un mundo y su sesión opcional.

    Conserva las bases de los demás mundos y devuelve la base normalizada.
    """
    # Valida la nueva base antes de cargar y modificar el registro existente.
    value = {"version": version, "sha256": sha256}
    if session_id is not None:
        value["session_id"] = session_id
    base = _validate_base(world_name, value)
    state = _load_state(worlds_path)
    worlds = state["worlds"]

    # Reemplaza entradas equivalentes para evitar duplicados por diferencias de mayúsculas.
    for stored_name in list(worlds):
        if stored_name.casefold() == world_name.casefold():
            del worlds[stored_name]
    worlds[world_name] = base

    state_path = _state_path(worlds_path)
    temporary_path: Path | None = None
    try:
        # Escribe un temporal junto al estado para reemplazarlo solo cuando esté completo.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f"{STATE_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(state, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(state_path)
    finally:
        # Limpia el temporal restante tanto al completar el guardado como ante un fallo.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return base
