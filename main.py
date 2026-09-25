import os
import shutil
import zipfile
import json
import socket
import hashlib


import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from datetime import datetime, timezone
from sync import calcular_sha256

from local_valheim import buscar_mundo, imprimir_mundos
from sync2 import _BUCKET

# Cargamos las variables del archivo .env
load_dotenv()
endpoint    = os.getenv("R2_ENDPOINT")
access_key  = os.getenv("R2_ACCESS_KEY_ID")
secret_key  = os.getenv("R2_SECRET_ACCESS_KEY")
bucket      = os.getenv("R2_BUCKET")
worlds_path = os.getenv("VALHEIM_WORLDS_PATH")
world_name = os.getenv("VALHEIM_WORLD_NAME")

# Claves fijas dentro del bucket
KEY_ZIP      = "world.zip"
KEY_MANIFEST = "manifest.json"


# Creamos un cliente S3 para interactuar con el bucket de R2
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
)


def crear_zip(destino_zip: str = "world.zip") -> str:
    # Chekea que esté la variable de entorno
    nombre = os.getenv("VALHEIM_WORLD_NAME")
    if not nombre:
        raise RuntimeError("Falta VALHEIM_WORLD_NAME en el archivo .env")

    # Busca el mundo en la carpeta local de mundos
    mundo = buscar_mundo(nombre)
    if mundo is None:
        raise RuntimeError(f"No se encontró el mundo '{nombre}' en worlds_local")

    # Si existe un ZIP destino, lo borra para reemplazarlo
    if os.path.exists(destino_zip):
        os.remove(destino_zip)

    # Comprime el mundo en un ZIP, guardando rutas relativas
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for ruta_actual, _, archivos in os.walk(mundo.ruta):
            for archivo in archivos:
                ruta_completa = os.path.join(ruta_actual, archivo)
                ruta_relativa = os.path.relpath(ruta_completa, mundo.ruta)
                zf.write(ruta_completa, arcname=ruta_relativa)

    print(f"El Mundo '{nombre}' fue comprimido, el zip se encuentra en: '{destino_zip}'")
    return destino_zip


def crear_manifest(
    ruta_zip: str,
    ruta_manifest: str = "manifest.json",
    nombre_mundo: str = "MundoPrueba",
    version: int = 1,
    uploaded_by: str | None = None,
) -> str:
    
    # Función interna para calcular el SHA-256 de un archivo
    def calcular_sha256(ruta_archivo: str, bloque: int = 1024 * 1024) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(ruta_archivo, "rb") as f:
            while True:
                datos = f.read(bloque)
                if not datos:
                    break
                h.update(datos)
        return h.hexdigest()   
    
    # Si no se especifica quien subió el archivo, se usa el hostname de la máquina
    if uploaded_by is None:
        uploaded_by = socket.gethostname()

    # Crea el diccionario del manifest con la información del ZIP y del mundo
    manifest = {
        "version":     version,
        "world":       nombre_mundo,
        "filename":    "current/world.zip",
        "size":        os.path.getsize(ruta_zip),
        "sha256":      calcular_sha256(ruta_zip),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    
    # Guarda el manifest como JSON con formato legible
    with open(ruta_manifest, "w", encoding="utf-8") as file:
        json.dump(
            manifest,          # diccionario a guardar
            file,              # archivo que se va a escribir
            indent=4,          # Indentación de 4 espacios para legibilidad
            ensure_ascii=False # Evita que escape caracteres especiales (Acentos, emojis, ñ, etc.)
        )
        
    return ruta_manifest


def subir_zip(ruta_local: str, ruta_bucket: str = KEY_ZIP) -> None:
    # Chusmea que exista el archivo
    if not os.path.isfile(ruta_local):
        raise FileNotFoundError(f"No existe el ZIP: {ruta_local}")

    # Sube el ZIP a R2 usando multipart upload si es necesario
    with open(ruta_local, "rb") as f:
        s3.upload_fileobj(f, _BUCKET, ruta_bucket)

    # Feedback al usuario
    tamano = os.path.getsize(ruta_local)
    print(f"[subir_zip] Subiendo '{ruta_local}' ({tamano} bytes) → s3://{_BUCKET}/{ruta_bucket}")
    print(f"[subir_zip] OK")


def subir_manifest(ruta_local: str, ruta_bucket: str = KEY_MANIFEST) -> None:
    # Chusmea que exista el archivo
    if not os.path.isfile(ruta_local):
        raise FileNotFoundError(f"No existe el manifest: {ruta_local}")

    # Lee el archivo JSON
    with open(ruta_local, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Serializa el manifest a bytes y lo sube a R2
    cuerpo = json.dumps(manifest, indent=4, ensure_ascii=False).encode("utf-8")
    s3.put_object(
        Bucket=_BUCKET,
        Key=ruta_bucket,
        Body=cuerpo,
        ContentType="application/json",
    )

    # Feedback al usuario
    tamano = os.path.getsize(ruta_local)
    print(f"[subir_manifest] Subiendo '{ruta_local}' (versión {manifest['version']}, {tamano} bytes) → s3://{_BUCKET}/{ruta_bucket}")
    print(f"[subir_manifest] OK")


if __name__ == "__main__":
    imprimir_mundos()

    # 1. Comprimir el mundo
    zip_path = crear_zip()

    # 2. Construir el manifest (y guardarlo en disco)
    manifest_path = crear_manifest(
        ruta_zip=zip_path,
        ruta_manifest="manifest.json",
        nombre_mundo=str(world_name),
        version=1,
    )

    # 3. Subir ZIP primero
    subir_zip(zip_path)

    # 4. Subir manifest después
    subir_manifest(manifest_path)