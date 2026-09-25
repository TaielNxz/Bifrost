import hashlib


def calcular_sha256(ruta_archivo: str, bloque: int = 1024 * 1024) -> str:
    """
    Calcula el SHA-256 de un archivo leyéndolo por bloques de 1 MB.

    Devuelve el hash en formato hexadecimal (64 caracteres).
    """
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()