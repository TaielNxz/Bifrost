import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import PureWindowsPath

_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"}
)
_BIFROST_RESERVED_NAMES = frozenset({".bifrost-copies", ".bifrost-state.json"})
_BIFROST_BACKUP_MARKERS = ("_backup_", "_pre_pull_")


class InvalidWorldNameError(ValueError):
    """Representa un nombre de mundo rechazado junto con el motivo del rechazo."""

    def __init__(self, name: object, reason: str) -> None:
        """Crea el error conservando el valor original y el motivo del rechazo."""
        self.name = name
        self.reason = reason

        # Usa repr para hacer visibles espacios y controles sin interpretarlos en la terminal.
        super().__init__(f"Nombre de mundo inválido {name!r}: {reason}.")


def validate_world_name(name: object) -> str:
    """Valida un nombre de mundo frente a rutas, caracteres prohibidos y nombres reservados.

    Devuelve el nombre intacto o lanza InvalidWorldNameError con el motivo del rechazo.
    """
    # Exige un nombre no vacío que no se refiera al directorio actual o padre.
    if not isinstance(name, str):
        raise InvalidWorldNameError(name, "debe ser una cadena de texto")
    if not name:
        raise InvalidWorldNameError(name, "no puede estar vacío")
    if name in {".", ".."}:
        raise InvalidWorldNameError(name, "no puede referirse al directorio actual o padre")

    # Detecta unidades sin acceder al disco, incluso fuera de Windows y en rutas como C:Asgard.
    if PureWindowsPath(name).drive or name.startswith(("/", "\\")):
        raise InvalidWorldNameError(name, "debe ser un nombre de carpeta, no una ruta")
    if "/" in name or "\\" in name:
        raise InvalidWorldNameError(name, "no puede contener separadores de ruta")

    # Revisa controles Unicode y caracteres prohibidos por Windows dentro del nombre.
    for character in name:
        if unicodedata.category(character) == "Cc":
            raise InvalidWorldNameError(name, "no puede contener caracteres de control")
        if character in _WINDOWS_FORBIDDEN_CHARACTERS:
            raise InvalidWorldNameError(
                name, f"contiene el carácter {character!r}, prohibido por Windows"
            )

    # Rechaza puntos y espacios finales que Windows no admite en nombres de carpeta.
    if name.endswith((".", " ")):
        raise InvalidWorldNameError(name, "no puede terminar en punto o espacio")

    # Windows reconoce dispositivos también con extensión y espacios antes del punto.
    device_name = name.partition(".")[0].rstrip(" ").upper()
    if device_name in _WINDOWS_RESERVED_NAMES:
        raise InvalidWorldNameError(name, "es un nombre de dispositivo reservado por Windows")

    # Comprueba las reservas de Bifröst sin distinguir mayúsculas del nombre recibido.
    comparison_name = name.casefold()
    if comparison_name in _BIFROST_RESERVED_NAMES:
        raise InvalidWorldNameError(name, "está reservado para archivos o carpetas de Bifröst")
    if any(marker in comparison_name for marker in _BIFROST_BACKUP_MARKERS):
        raise InvalidWorldNameError(name, "contiene un marcador reservado para backups de Bifröst")

    return name


def world_name_key(name: object) -> str:
    """Valida un nombre y obtiene una clave para compararlo sin distinguir mayúsculas.

    Usa casefold sin aplicar normalización Unicode; la clave no sustituye al nombre original.
    """
    # Este criterio no emula exactamente la comparación del sistema de archivos de Windows.
    return validate_world_name(name).casefold()


class WorldNameConflictError(ValueError):
    """Identifica nombres distintos que coinciden al comparar sin distinguir mayúsculas."""

    def __init__(self, names: Sequence[str]) -> None:
        """Conserva los nombres originales y explica por qué no pueden usarse por separado."""
        self.names = tuple(names)
        self.reason = "coinciden al comparar sin distinguir mayúsculas"
        labels = ", ".join(repr(name) for name in self.names)
        super().__init__(f"Conflicto entre nombres de mundo {labels}: {self.reason}.")


WorldNameIssue = InvalidWorldNameError | WorldNameConflictError


def filter_world_names(
    names: Iterable[object], *, errors: list[WorldNameIssue] | None = None
) -> list[str]:
    """Lista nombres válidos sin conflictos y permite recoger los motivos de exclusión.

    Excluye todos los miembros de cada conflicto, conserva los nombres originales
    y omite repeticiones exactas sin considerarlas mundos distintos.
    """
    groups: dict[str, list[str]] = {}
    issues: list[WorldNameIssue] = []

    # Valida cada nombre sin impedir que los demás se examinen.
    for name in names:
        try:
            key = world_name_key(name)
        except InvalidWorldNameError as error:
            issues.append(error)
            continue
        valid_name = validate_world_name(name)
        group = groups.setdefault(key, [])
        if valid_name not in group:
            group.append(valid_name)

    # Examina todos los grupos antes de habilitar cualquiera de sus miembros.
    valid_names = []
    for group in groups.values():
        if len(group) > 1:
            issues.append(WorldNameConflictError(group))
        else:
            valid_names.append(group[0])
    if errors is not None:
        errors.extend(issues)
    return sorted(valid_names, key=world_name_key)
