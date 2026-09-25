"""
test_push.py — Documentación de referencia del push completo a R2.

Este archivo NO es el programa final. Simula el ciclo completo:

    ZIP local  →  SHA-256  →  manifest  →  subir ZIP  →  subir manifest

Usa un ZIP de prueba (no toca Valheim) para que puedas verificar que
el flujo de subida funciona y que el orden ZIP → manifest es correcto.

Los tres conceptos que ilustra:

    1. upload_fileobj para archivos grandes (multipart automático).
    2. put_object para archivos chicos (el manifest JSON).
    3. head_object para verificar que un objeto llegó antes de seguir.
"""

import json
import os
import zipfile

from sync import (
    construir_manifest,
    guardar_manifest,
    subir_zip,
    subir_manifest,
    verificar_objeto,
    KEY_ZIP,
    KEY_MANIFEST,
    _BUCKET,
)


# ---------------------------------------------------------------------------
# 1. Crear un ZIP de prueba
# ---------------------------------------------------------------------------
# No usamos Valheim para que puedas probar el push sin riesgo de subir
# tu mundo real por accidente mientras hacés pruebas.
# ---------------------------------------------------------------------------

def crear_zip_de_prueba(ruta_zip: str = "mundo_prueba.zip") -> str:
    if os.path.exists(ruta_zip):
        os.remove(ruta_zip)

    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MiMundo.fwl2",   b"metadata del mundo de prueba")
        zf.writestr("MiMundo.db2",    b"base de datos de prueba")
        zf.writestr("MiMundo.chunks", b"chunks de prueba")
        zf.writestr("MiMundo.ok",     b"")

    print(f"[crear] ZIP de prueba: '{ruta_zip}' ({os.path.getsize(ruta_zip)} bytes)")
    return ruta_zip


# ---------------------------------------------------------------------------
# 2. Flujo completo de push
# ---------------------------------------------------------------------------
# Este es el orden que va a usar el comando `valheim-sync push`:
#
#   1. Comprimir (acá lo simulamos con crear_zip_de_prueba)
#   2. Calcular hash y armar manifest
#   3. Subir el ZIP y verificar que llegó
#   4. Subir el manifest
#
# Si algo falla en el paso 3, el manifest viejo sigue siendo válido.
# ---------------------------------------------------------------------------

def push_de_prueba(version: int = 1) -> None:
    print(f"\n=== Push de prueba (versión {version}) ===\n")

    # --- Paso 1: ZIP listo ---
    ruta_zip = crear_zip_de_prueba()

    # --- Paso 2: manifest ---
    manifest = construir_manifest(
        ruta_zip=ruta_zip,
        nombre_mundo="MundoPrueba",
        version=version,
        uploaded_by="PC-TEST",
    )
    print(f"[manifest] sha256={manifest['sha256'][:16]}...")

    # Lo guardamos a disco solo para inspeccionarlo.
    guardar_manifest(manifest, "manifest_prueba.json")

    # --- Paso 3: subir ZIP ---
    subir_zip(ruta_zip)

    # --- Paso 4: verificar que llegó ---
    meta = verificar_objeto(KEY_ZIP)
    if meta is None:
        print("[verificar] ERROR — el ZIP no llegó")
        return
    print(f"[verificar] ZIP en R2: {meta['ContentLength']} bytes, "
          f"{meta['LastModified']}")

    # --- Paso 5: subir manifest ---
    subir_manifest(manifest)

    # --- Paso 6: verificar manifest ---
    meta_m = verificar_objeto(KEY_MANIFEST)
    if meta_m is None:
        print("[verificar] ERROR — el manifest no llegó")
        return
    print(f"[verificar] Manifest en R2: {meta_m['ContentLength']} bytes")

    print("\n[push] Completado.")


# ---------------------------------------------------------------------------
# 3. Leer el manifest que está en R2
# ---------------------------------------------------------------------------
# Útil para confirmar que el JSON llegó bien y para el próximo paso
# (status y pull).
# ---------------------------------------------------------------------------

def leer_manifest_remoto() -> dict:
    from sync import _s3
    resp = _s3.get_object(Bucket=_BUCKET, Key=KEY_MANIFEST)
    contenido = resp["Body"].read().decode("utf-8")
    return json.loads(contenido)


# ---------------------------------------------------------------------------
# 4. Ejemplo de uso
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    push_de_prueba(version=1)

    print("\n=== Manifest leído desde R2 ===")
    manifest_remoto = leer_manifest_remoto()
    print(json.dumps(manifest_remoto, indent=4, ensure_ascii=False))

    # Limpieza local
    if os.path.exists("mundo_prueba.zip"):
        os.remove("mundo_prueba.zip")
    if os.path.exists("manifest_prueba.json"):
        os.remove("manifest_prueba.json")
    print("\n[limpieza] Archivos locales de prueba eliminados")