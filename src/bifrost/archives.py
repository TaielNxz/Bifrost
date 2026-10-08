import hashlib
import os
import stat
import unicodedata
import zipfile
from pathlib import Path, PureWindowsPath

from .local_paths import iter_local_files


_WINDOWS_ZIP_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"}
)


def calculate_sha256(file_path: str | os.PathLike[str], block_size: int = 1024 * 1024) -> str:
    """Calcula el SHA-256 de un archivo."""
    digest = hashlib.sha256()

    # Procesa bloques sucesivos para limitar la memoria utilizada durante el cálculo.
    with Path(file_path).open("rb") as file:
        while block := file.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def create_zip(source_dir: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Comprime todos los archivos de una carpeta conservando sus rutas relativas.

    Rechaza enlaces y junctions en el origen.
    Reemplaza el ZIP de destino si ya existe y devuelve su ruta.
    """
    source = Path(source_dir)
    destination_path = Path(destination)

    # Valida el origen antes de crear o reemplazar el ZIP de destino.
    if not source.is_dir():
        raise FileNotFoundError(f"No existe la carpeta a comprimir: {source}")

    # Revisa todo el árbol y rechaza enlaces antes de modificar el ZIP de destino.
    files = sorted(path for path in iter_local_files(source) if path.is_file())

    # Prepara el destino una vez completada la revisión del origen.
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.unlink(missing_ok=True)

    # Guarda los archivos de cualquier extensión usando rutas relativas al origen.
    with zipfile.ZipFile(destination_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, arcname=file_path.relative_to(source))
    return destination_path


def verify_zip(file_path: str | os.PathLike[str], expected_sha256: str) -> bool:
    """Comprueba si el SHA-256 del ZIP coincide con el esperado."""
    return calculate_sha256(file_path) == expected_sha256


def _validate_zip_paths(archive: zipfile.ZipFile) -> None:
    """Revisa todas las entradas del ZIP con reglas de rutas relativas portables.

    Rechaza enlaces, dispositivos y destinos ambiguos antes de extraer o publicar el archivo.
    """
    paths: dict[tuple[str, ...], tuple[tuple[str, ...], bool]] = {}
    for member in archive.infolist():
        
        # Verifica que la ruta sea relativa, no contenga barras invertidas ni comience con una barra.
        name = member.orig_filename
        if not name or "\\" in name or name.startswith("/") or PureWindowsPath(name).drive:
            raise ValueError(f"Ruta insegura dentro del ZIP: {name!r}")
        
        # Para cada componente de la ruta, rechaza nombres reservados, caracteres inválidos y colisiones de mayúsculas.
        parts = tuple(name.removesuffix("/").split("/"))
        for component in parts:
            device_name = component.partition(".")[0].rstrip(" ").upper()
            if (
                component in {"", ".", ".."}
                or component.endswith((".", " "))
                or len(component.encode("utf-16-le")) > 510
                or device_name in _WINDOWS_ZIP_DEVICES
                or any(
                    character in '<>:"|?*' or unicodedata.category(character) == "Cc"
                    for character in component
                )
            ):
                raise ValueError(f"Ruta no portable dentro del ZIP: {name!r}")

        # Los ZIP de mundos solo pueden declarar archivos regulares y directorios.
        file_type = stat.S_IFMT(member.external_attr >> 16)
        if (
            file_type not in {0, stat.S_IFREG, stat.S_IFDIR}
            or (file_type == stat.S_IFDIR and not member.is_dir())
            or (file_type == stat.S_IFREG and member.is_dir())
        ):
            raise ValueError(f"Tipo de entrada inseguro dentro del ZIP: {name!r}")

        # Detecta colisiones de mayúsculas, archivos duplicados y conflictos archivo/directorio.
        for depth in range(1, len(parts) + 1):
            original = parts[:depth]
            key = tuple(component.casefold() for component in original)
            directory = depth < len(parts) or member.is_dir()
            previous = paths.get(key)
            if previous is not None and (
                previous != (original, directory) or not directory
            ):
                raise ValueError(f"Rutas en conflicto dentro del ZIP: {name!r}")
            paths[key] = (original, directory)


def validate_zip(zip_path: str | os.PathLike[str]) -> None:
    """Comprueba que un ZIP sea legible y contenga rutas relativas seguras y portables.

    Verifica el CRC de sus entradas sin extraerlas ni modificar los bytes del archivo.
    """
    with zipfile.ZipFile(zip_path, "r") as archive:
        _validate_zip_paths(archive)
        bad_member = archive.testzip()
        if bad_member is not None:
            raise zipfile.BadZipFile(f"CRC inválido dentro del ZIP: {bad_member!r}")


def extract_zip(zip_path: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Extrae un ZIP con rutas portables y rechaza destinos fuera de la carpeta prevista.

    Revisa todas las rutas antes de crear el destino o extraer el primer archivo.
    """
    destination_path = Path(destination)
    destination_resolved = destination_path.resolve()

    with zipfile.ZipFile(zip_path, "r") as archive:
        _validate_zip_paths(archive)

        # Conserva la contención local frente a enlaces existentes en el destino.
        for member in archive.infolist():
            member_path = (destination_path / member.filename).resolve()
            if destination_resolved not in member_path.parents and member_path != destination_resolved:
                raise ValueError(f"Ruta insegura dentro del ZIP: {member.filename!r}")

        # La extracción comienza solo después de validar el conjunto de rutas.
        destination_path.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination_path)
    return destination_path

