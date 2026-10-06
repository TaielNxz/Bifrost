import hashlib
import os
import zipfile
from pathlib import Path


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

    Reemplaza el ZIP de destino si ya existe y devuelve su ruta.
    """
    source = Path(source_dir)
    destination_path = Path(destination)

    # Valida el origen antes de crear o reemplazar el ZIP de destino.
    if not source.is_dir():
        raise FileNotFoundError(f"No existe la carpeta a comprimir: {source}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.unlink(missing_ok=True)

    # Recorre también las subcarpetas, sin filtrar extensiones ni incluir rutas absolutas.
    with zipfile.ZipFile(destination_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(path for path in source.rglob("*") if path.is_file()):
            archive.write(file_path, arcname=file_path.relative_to(source))
    return destination_path


def verify_zip(file_path: str | os.PathLike[str], expected_sha256: str) -> bool:
    """Comprueba si el SHA-256 del ZIP coincide con el esperado."""
    return calculate_sha256(file_path) == expected_sha256


def extract_zip(zip_path: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Extrae un ZIP rechazando rutas que escaparían de la carpeta destino."""
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination_path.resolve()

    # Revisa todas las rutas antes de extraer el primer archivo.
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            member_path = (destination_path / member.filename).resolve()

            # Error de ruta: rechaza el ZIP si un miembro escaparía del destino.
            if destination_resolved not in member_path.parents and member_path != destination_resolved:
                raise ValueError(f"Ruta insegura dentro del ZIP: {member.filename}")

        # La extracción comienza solo después de validar el conjunto de rutas.
        archive.extractall(destination_path)
    return destination_path

