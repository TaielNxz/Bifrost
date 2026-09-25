import os
import json
import socket
import hashlib
import zipfile

import boto3
from botocore.client import Config
from dotenv import load_dotenv
from datetime import datetime, timezone

from local_valheim import buscar_mundo, imprimir_mundos


# ==========================================================================
# Configuración
# ==========================================================================

load_dotenv()

endpoint   = os.getenv("R2_ENDPOINT")
access_key = os.getenv("R2_ACCESS_KEY_ID")
secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
bucket     = os.getenv("R2_BUCKET")
world_name = os.getenv("VALHEIM_WORLD_NAME")

s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
)


# ==========================================================================
# Utilidades
# ==========================================================================

def calcular_sha256(ruta_archivo: str, bloque: int = 1024 * 1024) -> str:
    """Calcula el SHA-256 de un archivo leyéndolo por bloques de 1 MB."""
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


# ==========================================================================
# Comprimir el mundo
# ==========================================================================

def crear_zip(destino_zip: str = "world.zip") -> str:
    nombre = os.getenv("VALHEIM_WORLD_NAME")
    if not nombre:
        raise RuntimeError("Falta VALHEIM_WORLD_NAME en el archivo .env")

    mundo = buscar_mundo(nombre)
    if mundo is None:
        raise RuntimeError(f"No se encontró el mundo '{nombre}' en worlds_local")

    if os.path.exists(destino_zip):
        os.remove(destino_zip)

    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta_actual, _, archivos in os.walk(mundo.ruta):
            for archivo in archivos:
                ruta_completa = os.path.join(ruta_actual, archivo)
                ruta_relativa = os.path.relpath(ruta_completa, mundo.ruta)
                zf.write(ruta_completa, arcname=ruta_relativa)

    print(f"[crear_zip] '{nombre}' comprimido → '{destino_zip}' "
          f"({os.path.getsize(destino_zip)} bytes)")
    return destino_zip


# ==========================================================================
# Manifest
# ==========================================================================

def crear_manifest(
    ruta_zip: str,
    nombre_mundo: str,
    ruta_manifest: str = "manifest.json",
    version: int = 1,
    uploaded_by: str | None = None,
) -> str:
    if uploaded_by is None:
        uploaded_by = socket.gethostname()

    manifest = {
        "version":     version,
        "world":       nombre_mundo,
        "filename":    "current/world.zip",
        "size":        os.path.getsize(ruta_zip),
        "sha256":      calcular_sha256(ruta_zip),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(ruta_manifest, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=4, ensure_ascii=False)

    print(f"[crear_manifest] versión {version}, sha256={manifest['sha256'][:16]}...")
    return ruta_manifest


# ==========================================================================
# Subida a R2
# ==========================================================================

def subir_zip(ruta_local: str, ruta_bucket: str = "world.zip") -> None:
    if not os.path.isfile(ruta_local):
        raise FileNotFoundError(f"No existe el ZIP: {ruta_local}")

    tamano = os.path.getsize(ruta_local)
    print(f"[subir_zip] Subiendo '{ruta_local}' ({tamano} bytes) "
          f"→ s3://{bucket}/{ruta_bucket}")

    with open(ruta_local, "rb") as f:
        s3.upload_fileobj(f, bucket, ruta_bucket)

    print(f"[subir_zip] OK")



def subir_manifest(ruta_local: str, ruta_bucket: str = "manifest.json") -> None:
    if not os.path.isfile(ruta_local):
        raise FileNotFoundError(f"No existe el manifest: {ruta_local}")

    with open(ruta_local, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    tamano = os.path.getsize(ruta_local)
    print(f"[subir_manifest] Subiendo '{ruta_local}' "
          f"(versión {manifest['version']}, {tamano} bytes) "
          f"→ s3://{bucket}/{ruta_bucket}")

    cuerpo = json.dumps(manifest, indent=4, ensure_ascii=False).encode("utf-8")
    s3.put_object(
        Bucket=bucket,
        Key=ruta_bucket,
        Body=cuerpo,
        ContentType="application/json",
    )

    print(f"[subir_manifest] OK")


# ==========================================================================
# Main
# ==========================================================================

if __name__ == "__main__":
    if not world_name:
        raise RuntimeError("Falta VALHEIM_WORLD_NAME en el archivo .env")

    imprimir_mundos()

    zip_path = crear_zip()
    manifest_path = crear_manifest(
        ruta_zip=zip_path,
        ruta_manifest="manifest.json",
        nombre_mundo=world_name,
        version=1,
    )

    subir_zip(zip_path)
    subir_manifest(manifest_path)