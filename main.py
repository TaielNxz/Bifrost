import os
import shutil
import zipfile

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from local_valheim import buscar_mundo, imprimir_mundos

# Cargamos las variables del archivo .env
load_dotenv()
endpoint    = os.getenv("R2_ENDPOINT")
access_key  = os.getenv("R2_ACCESS_KEY_ID")
secret_key  = os.getenv("R2_SECRET_ACCESS_KEY")
bucket      = os.getenv("R2_BUCKET")
worlds_path = os.getenv("VALHEIM_WORLDS_PATH")
world_name = os.getenv("VALHEIM_WORLD_NAME")

# Creamos un cliente S3 para interactuar con el bucket de R2
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
)

def comprimir_mundo(destino_zip: str = "world.zip"):
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

if __name__ == "__main__":
    imprimir_mundos()
    comprimir_mundo()