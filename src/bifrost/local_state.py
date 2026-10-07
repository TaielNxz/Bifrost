import json
import tempfile
from pathlib import Path
from typing import Any

from .local_paths import ensure_local_path
from .models import LocalBase
from .world_names import WorldNameConflictError, filter_world_names, validate_world_name, world_name_key

STATE_FILENAME = ".bifrost-state.json"
STATE_SCHEMA_VERSION = 1


def _state_path(worlds_path: str | Path) -> Path:
    """Obtiene la ruta del registro de bases locales y rechaza que sea un enlace o junction."""
    return ensure_local_path(worlds_path, Path(worlds_path) / STATE_FILENAME)


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
    """Carga el estado local y valida las bases de los mundos con nombres utilizables.

    Conserva las entradas con nombres inválidos o ambiguos sin validar sus bases.
    """
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

    # Comprueba el esquema y el mapa de mundos antes de validar cada base individual.
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RuntimeError(f"El formato del estado local de Bifröst no es válido: {path}")
    worlds = value.get("worlds")
    if not isinstance(worlds, dict) or any(not isinstance(name, str) for name in worlds):
        raise RuntimeError(f"La lista de mundos del estado local no es válida: {path}")

    # Valida solo las bases con nombres utilizables; conserva las demás entradas intactas.
    for name in filter_world_names(worlds):
        _validate_base(name, worlds[name])
    return value


def _stored_world_name(worlds: dict[str, Any], world_name: str) -> str | None:
    """Busca el nombre registrado de un mundo sin distinguir mayúsculas.

    Rechaza coincidencias ambiguas y devuelve None si no hay una entrada válida.
    """
    key = world_name_key(world_name)
    errors = []
    names = filter_world_names(worlds, errors=errors)

    # Solo los conflictos del mundo solicitado bloquean la búsqueda.
    for error in errors:
        if isinstance(error, WorldNameConflictError) and world_name_key(error.names[0]) == key:
            raise error

    return next((name for name in names if world_name_key(name) == key), None)


def read_base_version(worlds_path: str | Path, world_name: str) -> LocalBase | None:
    """Busca la base local por nombre sin distinguir mayúsculas, incluida su sesión opcional.

    Rechaza nombres inválidos o ambiguos; devuelve None si el mundo no tiene una base registrada.
    """
    validate_world_name(world_name)
    worlds = _load_state(worlds_path)["worlds"]
    stored_name = _stored_world_name(worlds, world_name)

    # Caso 1: Encuentra una entrada única; devuelve su base validada y normalizada.
    if stored_name is not None:
        return _validate_base(stored_name, worlds[stored_name])

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
    validate_world_name(world_name)
    value = {"version": version, "sha256": sha256}
    if session_id is not None:
        value["session_id"] = session_id
    base = _validate_base(world_name, value)
    state = _load_state(worlds_path)
    worlds = state["worlds"]

    # Actualiza una coincidencia única sin renombrarla ni fusionar entradas en conflicto.
    stored_name = _stored_world_name(worlds, world_name)
    worlds[stored_name if stored_name is not None else world_name] = base

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
            temporary_path = Path(temporary_file.name)
            json.dump(state, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")

        # Vuelve a comprobar el destino antes de sustituir el registro existente.
        ensure_local_path(worlds_path, state_path)
        temporary_path.replace(state_path)
    finally:
        # Limpia el temporal restante tanto al completar el guardado como ante un fallo.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return base
