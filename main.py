import os
import shutil

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from local_valheim import imprimir_mundos

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

# Chusmea la carpeta local de mundos y muestra los mundos detectados (sin backups)
imprimir_mundos()