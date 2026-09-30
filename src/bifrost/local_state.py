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
    """Valida y normaliza la versión base registrada para un mundo."""
    if not isinstance(value, dict):
        raise RuntimeError(f"El estado local de '{world_name}' no es válido.")
    version = value.get("version")
    sha256 = value.get("sha256")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RuntimeError(f"La versión base local de '{world_name}' no es válida.")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        raise RuntimeError(f"El SHA-256 base local de '{world_name}' no es válido.")
    return {"version": version, "sha256": sha256.lower()}


def _load_state(worlds_path: str | Path) -> dict[str, Any]:
    """Carga y valida el documento completo de estado local."""
    path = _state_path(worlds_path)
    if not path.exists():
        return _empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"No se pudo leer el estado local de Bifröst: {path}") from error
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RuntimeError(f"El formato del estado local de Bifröst no es válido: {path}")
    worlds = value.get("worlds")
    if not isinstance(worlds, dict) or any(not isinstance(name, str) for name in worlds):
        raise RuntimeError(f"La lista de mundos del estado local no es válida: {path}")
    for name, base in worlds.items():
        _validate_base(name, base)
    return value


def read_base_version(worlds_path: str | Path, world_name: str) -> LocalBase | None:
    """Lee la versión y el hash desde los que parte un mundo local."""
    worlds = _load_state(worlds_path)["worlds"]
    for stored_name, value in worlds.items():
        if stored_name.casefold() == world_name.casefold():
            return _validate_base(stored_name, value)
    return None


def save_base_version(
    worlds_path: str | Path, world_name: str, version: int, sha256: str
) -> LocalBase:
    """Guarda atómicamente la versión base local de un mundo."""
    base = _validate_base(world_name, {"version": version, "sha256": sha256})
    state = _load_state(worlds_path)
    worlds = state["worlds"]
    for stored_name in list(worlds):
        if stored_name.casefold() == world_name.casefold():
            del worlds[stored_name]
    worlds[world_name] = base

    state_path = _state_path(worlds_path)
    temporary_path: Path | None = None
    try:
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
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return base
