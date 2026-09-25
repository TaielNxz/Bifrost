"""
test_manifest.py — Documentación de referencia para SHA-256 y manifest.json.

Este archivo NO es el programa final. Es una guía de estudio que muestra
los conceptos detrás de la verificación de integridad y la metadata de
versión del mundo. Los cuatro temas son:

    1. Calcular el SHA-256 de un archivo (hash por bloques).
    2. Construir el diccionario del manifest.
    3. Guardarlo y leerlo como JSON.
    4. Verificar que un archivo coincide con el hash del manifest.

La idea es que puedas leer este archivo de arriba hacia abajo y entender
por qué el manifest es una pieza separada del ZIP.
"""

import hashlib
import json
import os
import socket
import zipfile
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 1. Calcular el SHA-256 de un archivo
# ---------------------------------------------------------------------------
# SHA-256 toma cualquier cantidad de bytes y devuelve siempre 64 caracteres
# hexadecimales. Dos propiedades importantes:
#
#   - Si cambia un solo byte del archivo, el hash cambia por completo.
#   - No se puede "volver atrás" del hash al contenido original.
#
# Por eso sirve para verificar integridad: si el hash del archivo que
# descargamos coincide con el hash que está en el manifest, sabemos que
# llegó intacto.
#
# Leemos por bloques (1 MB por defecto) en vez de cargar todo el archivo
# en memoria. Los mundos de Valheim pueden pesar cientos de MB y no
# queremos saturar la RAM.
# ---------------------------------------------------------------------------

def calcular_sha256(ruta_archivo: str, bloque: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 2. Construir el manifest
# ---------------------------------------------------------------------------
# El manifest es la "etiqueta" de la versión actual del mundo. Describe
# qué ZIP está vigente, quién lo subió, cuándo y cuál es su hash.
#
# El ZIP es la carga útil (los bytes del mundo). El manifest es metadata
# que permite:
#
#   - Saber cuál es la última versión sin descargar el ZIP entero.
#   - Detectar si el ZIP cambió desde la última vez que lo bajamos.
#   - Verificar integridad después de descargar.
#   - Saber quién subió la versión y cuándo.
#
# Notas de formato:
#   - uploaded_at en UTC (ISO 8601 con Z al final). Así los timestamps
#     son comparables aunque el grupo tenga jugadores en husos distintos.
#   - uploaded_by por defecto es el nombre de la máquina. Si querés
#     poner el nombre del jugador, pasalo como parámetro.
# ---------------------------------------------------------------------------

def construir_manifest(
    ruta_zip: str,
    nombre_mundo: str,
    version: int,
    uploaded_by: str | None = None,
) -> dict:
    if uploaded_by is None:
        uploaded_by = socket.gethostname()

    return {
        "version":     version,
        "world":       nombre_mundo,
        "filename":    "current/world.zip",
        "size":        os.path.getsize(ruta_zip),
        "sha256":      calcular_sha256(ruta_zip),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# 3. Guardar y leer el manifest como JSON
# ---------------------------------------------------------------------------
# En el proyecto final el manifest va a vivir en R2 como un objeto más
# (metadata/manifest.json). Pero mientras desarrollamos, guardarlo en
# disco nos permite inspeccionarlo con un editor de texto y entender
# exactamente qué se va a subir.
#
# indent=4      → lo hace legible a ojo.
# ensure_ascii=False → si algún día hay acentos o emojis, no los escapa.
# ---------------------------------------------------------------------------

def guardar_manifest(manifest: dict, ruta: str = "manifest.json") -> str:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)
    return ruta


def leer_manifest(ruta: str = "manifest.json") -> dict:
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 4. Verificar integridad
# ---------------------------------------------------------------------------
# El flujo real de pull va a ser:
#
#   1. Descargar el manifest desde R2.
#   2. Descargar el ZIP indicado por el manifest.
#   3. Calcular el SHA-256 del ZIP descargado.
#   4. Comparar con el sha256 del manifest.
#
# Si coincide → el archivo llegó bien, seguir con la descompresión.
# Si no coincide → el archivo está corrupto o incompleto, abortar.
# ---------------------------------------------------------------------------

def verificar_integridad(ruta_archivo: str, manifest: dict) -> bool:
    hash_actual = calcular_sha256(ruta_archivo)
    hash_esperado = manifest["sha256"]

    if hash_actual == hash_esperado:
        print(f"[verificar] OK — el hash coincide")
        return True

    print(f"[verificar] ERROR — el hash NO coincide")
    print(f"            esperado: {hash_esperado}")
    print(f"            obtenido: {hash_actual}")
    return False


# ---------------------------------------------------------------------------
# 5. Utilidad: crear un ZIP de prueba
# ---------------------------------------------------------------------------
# Para que este archivo sea autocontenido, generamos un ZIP con un par
# de archivos. No depende de Valheim ni de R2.
# ---------------------------------------------------------------------------

def crear_zip_de_prueba(ruta_zip: str = "prueba_manifest.zip"):
    if os.path.exists(ruta_zip):
        os.remove(ruta_zip)

    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("datos/a.txt", "hola")
        zf.writestr("datos/b.txt", "mundo")

    print(f"[crear] ZIP de prueba creado: '{ruta_zip}'")
    return ruta_zip


# ---------------------------------------------------------------------------
# 6. Ejemplo de uso — el ciclo completo
# ---------------------------------------------------------------------------
# Simula lo que va a hacer el push:
#
#   ZIP listo  →  calcular hash  →  construir manifest  →  guardar
#
# Y después simula lo que va a hacer el pull:
#
#   leer manifest  →  verificar el archivo contra el hash del manifest
#
# También probamos el caso de fallo: modificamos el archivo y confirmamos
# que la verificación lo detecta.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    RUTA_ZIP       = "prueba_manifest.zip"
    RUTA_MANIFEST  = "manifest_prueba.json"

    print("=== 1. Crear ZIP de prueba ===")
    crear_zip_de_prueba(RUTA_ZIP)

    print("\n=== 2. Construir manifest ===")
    manifest = construir_manifest(
        ruta_zip=RUTA_ZIP,
        nombre_mundo="Asgard",
        version=1,
        uploaded_by="PC-TAIEL",
    )
    for clave, valor in manifest.items():
        print(f"  {clave}: {valor}")

    print("\n=== 3. Guardar y leer manifest ===")
    guardar_manifest(manifest, RUTA_MANIFEST)
    print(f"[guardar] Manifest escrito en '{RUTA_MANIFEST}'")

    manifest_leido = leer_manifest(RUTA_MANIFEST)
    assert manifest_leido == manifest, "El manifest leído difiere del original"
    print("[leer] Manifest leído y coincide con el original")

    print("\n=== 4. Verificar integridad (caso OK) ===")
    verificar_integridad(RUTA_ZIP, manifest_leido)

    print("\n=== 5. Verificar integridad (caso corrupto) ===")
    # Agregamos un byte al final del ZIP para simular corrupción.
    with open(RUTA_ZIP, "ab") as f:
        f.write(b"\x00")
    print("[simular] Se agregó un byte al ZIP para simular corrupción")
    verificar_integridad(RUTA_ZIP, manifest_leido)

    print("\n=== 6. Limpieza ===")
    os.remove(RUTA_ZIP)
    os.remove(RUTA_MANIFEST)
    print("[limpieza] Archivos de prueba eliminados")