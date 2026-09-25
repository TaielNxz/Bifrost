"""
test_zip.py — Práctica de compresión y descompresión con zipfile.

El objetivo es entender cómo comprimir una carpeta completa (como el
mundo de Valheim) en un único archivo .zip, y cómo restaurarla después.

En el proyecto final:
    - push: comprime la carpeta del mundo  →  world.zip  →  sube a R2
    - pull: descarga world.zip  →  descomprime  →  carpeta del mundo
"""

import os
import shutil
import zipfile


# ---------------------------------------------------------------------------
# 1. Crear una carpeta de prueba con archivos falsos
# ---------------------------------------------------------------------------
# Simula la estructura de un mundo de Valheim: varios archivos dentro de
# subcarpetas, con contenido binario y de texto mezclados.
# ---------------------------------------------------------------------------

def crear_mundo_falso(ruta_base: str = "mundo_falso"):
    # Si ya existe, lo borramos para empezar limpio.
    if os.path.exists(ruta_base):
        shutil.rmtree(ruta_base)

    # Estructura de carpetas que simula un mundo:
    #   mundo_falso/
    #       MiMundo.fwl2
    #       MiMundo.db2
    #       MiMundo.chunks
    #       MiMundo.ok
    os.makedirs(ruta_base, exist_ok=True)

    archivos = {
        "MiMundo.fwl2":   b"\x00\x01\x02\x03 metadata del mundo",
        "MiMundo.db2":    b"\x04\x05\x06\x07 base de datos del mundo",
        "MiMundo.chunks": b"\x08\x09\x0a\x0b datos por chunks",
        "MiMundo.ok":     b"",   # archivo vacío que marca fin de guardado
    }

    for nombre, contenido in archivos.items():
        with open(os.path.join(ruta_base, nombre), "wb") as f:
            f.write(contenido)

    print(f"[crear] Carpeta '{ruta_base}' creada con {len(archivos)} archivos")


# ---------------------------------------------------------------------------
# 2. Comprimir una carpeta entera a un ZIP
# ---------------------------------------------------------------------------
# os.walk recorre la carpeta y todas sus subcarpetas. Para cada archivo
# guardamos en el ZIP la ruta relativa (no la absoluta), para que al
# descomprimir se reconstruya la misma estructura desde la raíz.
# ---------------------------------------------------------------------------

def comprimir(carpeta_origen: str, archivo_zip: str):
    if os.path.exists(archivo_zip):
        os.remove(archivo_zip)

    with zipfile.ZipFile(archivo_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta_actual, _, archivos in os.walk(carpeta_origen):
            for nombre in archivos:
                ruta_completa = os.path.join(ruta_actual, nombre)
                # arcname = ruta relativa dentro del ZIP
                ruta_relativa = os.path.relpath(ruta_completa, carpeta_origen)
                zf.write(ruta_completa, arcname=ruta_relativa)

    tamano = os.path.getsize(archivo_zip)
    print(f"[comprimir] '{archivo_zip}' creado ({tamano} bytes)")


# ---------------------------------------------------------------------------
# 3. Descomprimir un ZIP en una carpeta destino
# ---------------------------------------------------------------------------
# extractall respeta las rutas internas del ZIP, así que se reconstruye
# la estructura original automáticamente.
# ---------------------------------------------------------------------------

def descomprimir(archivo_zip: str, carpeta_destino: str):
    if os.path.exists(carpeta_destino):
        shutil.rmtree(carpeta_destino)

    os.makedirs(carpeta_destino, exist_ok=True)

    with zipfile.ZipFile(archivo_zip, "r") as zf:
        zf.extractall(carpeta_destino)

    print(f"[descomprimir] '{archivo_zip}' extraído en '{carpeta_destino}'")


# ---------------------------------------------------------------------------
# 4. Listar el contenido de un ZIP sin extraerlo
# ---------------------------------------------------------------------------
# Útil para verificar qué hay adentro antes de descomprimir.
# ---------------------------------------------------------------------------

def listar_contenido(archivo_zip: str):
    with zipfile.ZipFile(archivo_zip, "r") as zf:
        print(f"[listar] Contenido de '{archivo_zip}':")
        for info in zf.infolist():
            print(f"          {info.filename}  ({info.file_size} bytes)")


# ---------------------------------------------------------------------------
# 5. Comparar dos carpetas archivo por archivo
# ---------------------------------------------------------------------------
# Verifica que el ZIP preservó todo: mismo conjunto de archivos y mismo
# contenido byte a byte.
# ---------------------------------------------------------------------------

def comparar_carpetas(carpeta_a: str, carpeta_b: str) -> bool:
    archivos_a = set()
    archivos_b = set()

    for ruta, _, archivos in os.walk(carpeta_a):
        for nombre in archivos:
            archivos_a.add(os.path.relpath(os.path.join(ruta, nombre), carpeta_a))

    for ruta, _, archivos in os.walk(carpeta_b):
        for nombre in archivos:
            archivos_b.add(os.path.relpath(os.path.join(ruta, nombre), carpeta_b))

    if archivos_a != archivos_b:
        print(f"[comparar] Diferencia en la lista de archivos")
        print(f"           Solo en A: {archivos_a - archivos_b}")
        print(f"           Solo en B: {archivos_b - archivos_a}")
        return False

    for rel in archivos_a:
        with open(os.path.join(carpeta_a, rel), "rb") as f:
            contenido_a = f.read()
        with open(os.path.join(carpeta_b, rel), "rb") as f:
            contenido_b = f.read()

        if contenido_a != contenido_b:
            print(f"[comparar] Contenido distinto en '{rel}'")
            return False

    print("[comparar] Las carpetas son idénticas")
    return True


# ---------------------------------------------------------------------------
# 6. Ejemplo de uso
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ORIGEN   = "mundo_falso"
    ZIP      = "mundo_falso.zip"
    DESTINO  = "mundo_restaurado"

    print("=== 1. Crear mundo falso ===")
    crear_mundo_falso(ORIGEN)

    print("\n=== 2. Comprimir ===")
    comprimir(ORIGEN, ZIP)

    print("\n=== 3. Listar contenido del ZIP ===")
    listar_contenido(ZIP)

    print("\n=== 4. Descomprimir ===")
    descomprimir(ZIP, DESTINO)

    print("\n=== 5. Comparar original vs restaurado ===")
    comparar_carpetas(ORIGEN, DESTINO)