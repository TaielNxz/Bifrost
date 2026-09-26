import os
import json
import socket
import hashlib
import zipfile

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError 
from dotenv import load_dotenv
from datetime import datetime, timezone

from local_valheim import buscar_mundo, imprimir_mundos
from paths import key_current_zip, key_manifest


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
    """
    Calcula el SHA-256 de un archivo leyéndolo por bloques de 1 MB.
    """
    h = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()

def leer_manifest_remoto(nombre_mundo: str) -> dict | None:
    """
    Lee el manifest de un mundo desde R2. \n
    Devuelve None si no existe (primer push).
    """
    try:
        resp = s3.get_object(Bucket=bucket, Key=key_manifest(nombre_mundo))
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError:
        return None

def listar_mundos_remotos() -> list[str]:
    """
    Lista los nombres de mundos que existen en la nube.
    Usa Delimiter='/' para obtener solo las 'carpetas' de primer nivel
    dentro de worlds/, no todos los objetos anidados.
    """
    resp = s3.list_objects_v2(
        Bucket=bucket,
        Prefix="worlds/",
        Delimiter="/",
    )
    prefijos = resp.get("CommonPrefixes", [])
    nombres = [p["Prefix"].rstrip("/").split("/")[-1] for p in prefijos]
    return sorted(nombres, key=str.lower)

def parsear_fecha_iso(fecha: str) -> datetime:
    """
    Convierte la fecha ISO 8601 a un datetime aware en UTC. \n
    ej: '2026-09-24T22:30:00Z' -> datetime.datetime(2026, 9, 24, 22, 30, tzinfo=datetime.timezone.utc) \n
    El 'replace' es porque fromisoformat no acepta la 'Z' directamente
    en algunas versiones de Python.
    """
    return datetime.fromisoformat(fecha.replace("Z", "+00:00"))

# ==========================================================================
# Funciones para el PUSH
# ==========================================================================

def crear_zip(nombre_mundo: str, destino_zip: str | None = None) -> str:
    if destino_zip is None:
        destino_zip = f"world_{nombre_mundo}.zip"

    mundo = buscar_mundo(nombre_mundo)
    if mundo is None:
        raise RuntimeError(f"No se encontró el mundo '{nombre_mundo}' en worlds_local")

    if os.path.exists(destino_zip):
        os.remove(destino_zip)

    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta_actual, _, archivos in os.walk(mundo.ruta):
            for archivo in archivos:
                ruta_completa = os.path.join(ruta_actual, archivo)
                ruta_relativa = os.path.relpath(ruta_completa, mundo.ruta)
                zf.write(ruta_completa, arcname=ruta_relativa)

    print(f"[crear_zip] '{nombre_mundo}' comprimido → '{destino_zip}' "
          f"({os.path.getsize(destino_zip)} bytes)")
    return destino_zip


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
        "filename":    key_current_zip(nombre_mundo),
        "size":        os.path.getsize(ruta_zip),
        "sha256":      calcular_sha256(ruta_zip),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(ruta_manifest, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=4, ensure_ascii=False)

    print(f"[crear_manifest] versión {version}, sha256={manifest['sha256'][:16]}...")
    return ruta_manifest


def subir_zip(ruta_local: str, ruta_bucket: str) -> None:
    if not os.path.isfile(ruta_local):
        raise FileNotFoundError(f"No existe el ZIP: {ruta_local}")

    tamano = os.path.getsize(ruta_local)
    print(f"[subir_zip] Subiendo '{ruta_local}' ({tamano} bytes) "
          f"→ s3://{bucket}/{ruta_bucket}")

    with open(ruta_local, "rb") as f:
        s3.upload_fileobj(f, bucket, ruta_bucket)

    print(f"[subir_zip] OK")


def subir_manifest(ruta_local: str, ruta_bucket: str) -> None:
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
# Funciones para el PULL
# ==========================================================================
def descargar_zip(ruta_bucket: str, destino: str) -> str:
    """
    Descarga un ZIP desde R2 a la ruta local destino.
    """
    
    print(f"[descargar_zip] Bajando s3://{bucket}/{ruta_bucket} → '{destino}'")
    
    with open(destino, "wb") as f:
        s3.download_fileobj(bucket, ruta_bucket, f) # 'download_fileobj' maneja archivos grandes y multipart automáticamente
        
    print(f"[descargar_zip] OK ({os.path.getsize(destino)} bytes)")
    return destino


def verificar_zip(ruta_local: str, manifest: dict) -> bool:
    """
    Compara el SHA-256 del archivo local con el que dice el manifest.
    """
    hash_local = calcular_sha256(ruta_local)
    hash_esperado = manifest["sha256"]
    
    if hash_local == hash_esperado:
        print(f"[verificar] OK — sha256 coincide")
        return True
    
    print(f"[verificar] ERROR — sha256 NO coincide")
    print(f"            esperado: {hash_esperado}")
    print(f"            obtenido: {hash_local}")
    return False


def descomprimir_zip(ruta_zip: str, carpeta_destino: str) -> None:
    """
    Descomprime un ZIP en la carpeta destino. \n
    Crea la carpeta destino si no existe.
    """
    os.makedirs(carpeta_destino, exist_ok=True)
    with zipfile.ZipFile(ruta_zip, "r") as zf:
        zf.extractall(carpeta_destino)
    print(f"[descomprimir] '{ruta_zip}' → '{carpeta_destino}'")


# ==========================================================================
# Main
# ==========================================================================

# if __name__ == "__main__":
#     if not world_name:
#         raise RuntimeError("Falta VALHEIM_WORLD_NAME en el archivo .env")

#     imprimir_mundos()

#     # zip_path = crear_zip(world_name)
#     # manifest_path = crear_manifest(
#     #     ruta_zip=zip_path,
#     #     ruta_manifest="manifest.json",
#     #     nombre_mundo=world_name,
#     #     version=1,
#     # )

#     # subir_zip(zip_path, key_current_zip(world_name))
#     # subir_manifest(manifest_path, key_manifest(world_name))