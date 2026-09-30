import hashlib
import os
import zipfile
from pathlib import Path


def calculate_sha256(file_path: str | os.PathLike[str], block_size: int = 1024 * 1024) -> str:
    """Calcula el hash SHA256 de un archivo."""
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as file:
        while block := file.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def create_zip(source_dir: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Crea un archivo ZIP desde una carpeta, sobrescribiendo el destino si ya existe."""
    source = Path(source_dir)
    destination_path = Path(destination)
    if not source.is_dir():
        raise FileNotFoundError(f"No existe la carpeta a comprimir: {source}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.unlink(missing_ok=True)

    with zipfile.ZipFile(destination_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(path for path in source.rglob("*") if path.is_file()):
            archive.write(file_path, arcname=file_path.relative_to(source))
    return destination_path


def verify_zip(file_path: str | os.PathLike[str], expected_sha256: str) -> bool:
    """Verifica que el archivo ZIP tenga el hash SHA256 esperado."""
    return calculate_sha256(file_path) == expected_sha256


def extract_zip(zip_path: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Extrae un ZIP rechazando rutas que escaparían de la carpeta destino."""
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination_path.resolve()

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            member_path = (destination_path / member.filename).resolve()
            if destination_resolved not in member_path.parents and member_path != destination_resolved:
                raise ValueError(f"Ruta insegura dentro del ZIP: {member.filename}")
        archive.extractall(destination_path)
    return destination_path

