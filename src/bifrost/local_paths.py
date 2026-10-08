import os
import stat
from collections.abc import Iterator
from pathlib import Path


def ensure_local_path(
    root: str | os.PathLike[str], path: str | os.PathLike[str]
) -> Path:
    """Valida una ruta descendiente de la raíz y devuelve su ubicación original.

    Rechaza enlaces y junctions bajo esa raíz, incluso si apuntan a su interior.
    Permite rutas todavía inexistentes sin crearlas.
    """
    root_path = Path(root)
    candidate = Path(path)

    # Exige una ruta descendiente, sin referencias al directorio padre.
    try:
        relative = candidate.absolute().relative_to(root_path.absolute())
    except ValueError as error:
        raise RuntimeError(f"Ruta local fuera de la carpeta prevista: {str(candidate)!r}.") from error
    if not relative.parts or ".." in relative.parts:
        raise RuntimeError(f"Ruta local insegura: {str(candidate)!r}.")

    # Revisa los componentes bajo la raíz sin seguir enlaces ni junctions.
    current = root_path
    for component in relative.parts:
        # Aplica el límite de Windows también a nombres generados para backups y copias.
        if len(component.encode("utf-16-le")) > 510:
            raise RuntimeError(f"El componente de la ruta local supera 255 unidades UTF-16: {component!r}.")
        current = current / component

        # Permite componentes inexistentes para preparar futuros destinos.
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        tag = getattr(metadata, "st_reparse_tag", None)
        if stat.S_ISLNK(metadata.st_mode) or (
            tag is not None and tag in {
                getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None),
                getattr(stat, "IO_REPARSE_TAG_SYMLINK", None),
            }
        ):
            raise RuntimeError(f"La ruta local contiene un enlace o junction: {str(current)!r}.")

    # Confirma que la ubicación resuelta también permanezca dentro de la raíz.
    if not candidate.resolve().is_relative_to(root_path.resolve()):
        raise RuntimeError(f"Ruta local fuera de la carpeta prevista: {str(candidate)!r}.")
    return candidate


def iter_local_files(directory: str | os.PathLike[str]) -> Iterator[Path]:
    """Recorre recursivamente los archivos de una carpeta, rechazando enlaces y junctions."""
    root = Path(directory)
    absolute_root = root.absolute()
    ensure_local_path(absolute_root.parent, absolute_root)

    for current_dir, directories, files in os.walk(root):
        # Valida subcarpetas antes de que el recorrido pueda entrar en ellas.
        for name in directories:
            ensure_local_path(root, Path(current_dir) / name)

        for name in files:
            yield ensure_local_path(root, Path(current_dir) / name)
