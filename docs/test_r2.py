"""
test_r2.py — Documentación de referencia del cliente S3 para Cloudflare R2.

Este archivo NO es el programa final. Es una guía de estudio que muestra
los cinco métodos básicos que vamos a usar en todo el proyecto:

    - list_objects_v2  → listar objetos del bucket
    - put_object       → subir un objeto
    - get_object       → descargar un objeto
    - head_object      → consultar metadatos sin descargar
    - delete_object    → borrar un objeto

Cada función está pensada para leerse de arriba hacia abajo y entender
cómo se conecta Python con R2 a través de boto3.
"""

import os
import shutil

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# 1. Configuración: credenciales y cliente
# ---------------------------------------------------------------------------

# Cargamos las variables del archivo .env (nunca hardcodear credenciales).
load_dotenv()

endpoint    = os.getenv("R2_ENDPOINT")
access_key  = os.getenv("R2_ACCESS_KEY_ID")
secret_key  = os.getenv("R2_SECRET_ACCESS_KEY")
bucket      = os.getenv("R2_BUCKET")

# El "cliente" es un intermediario que sabe hablar el protocolo S3
# contra el endpoint de R2. No es una conexión abierta: se reutiliza.
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
)

# Clave fija de prueba que usamos en todos los ejemplos.
KEY_PRUEBA = "prueba.txt"


# ---------------------------------------------------------------------------
# 2. Listar objetos: list_objects_v2
# ---------------------------------------------------------------------------
# Devuelve un diccionario con la clave "Contents", que es una lista de
# objetos. Si el bucket está vacío, "Contents" no existe; por eso usamos
# .get("Contents", []) para evitar un KeyError.
# ---------------------------------------------------------------------------

def listar(prefix: str = ""):
    respuesta = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    objetos = respuesta.get("Contents", [])

    if not objetos:
        print(f"[listar] No hay objetos con prefix='{prefix}'")
        return

    for obj in objetos:
        print(f"[listar] {obj['Key']}  ({obj['Size']} bytes)")


# ---------------------------------------------------------------------------
# 3. Subir un objeto: put_object
# ---------------------------------------------------------------------------
# Body acepta bytes, un archivo abierto en "rb" o un BytesIO.
# Para el proyecto final vamos a pasar un archivo abierto en "rb"
# (el ZIP del mundo).
# ---------------------------------------------------------------------------

def subir_prueba():
    s3.put_object(
        Bucket=bucket,                  # nombre del bucket
        Key=KEY_PRUEBA,                 # "ruta" dentro del bucket
        Body=b"esta es una prueba",     # contenido en bytes
    )
    print(f"[subir] Subido '{KEY_PRUEBA}'")


# ---------------------------------------------------------------------------
# 4. Descargar un objeto: get_object
# ---------------------------------------------------------------------------
# respuesta["Body"] es un stream de bytes, no un archivo ni un string.
# Para guardarlo en disco usamos shutil.copyfileobj (funciona bien con
# archivos grandes porque copia por bloques).
# ---------------------------------------------------------------------------

def descargar_prueba(destino: str = "prueba_descargada.txt"):
    respuesta = s3.get_object(Bucket=bucket, Key=KEY_PRUEBA)
    with open(destino, "wb") as file:
        shutil.copyfileobj(respuesta["Body"], file)
    print(f"[descargar] Guardado como '{destino}'")


# ---------------------------------------------------------------------------
# 5. Consultar metadatos sin descargar: head_object
# ---------------------------------------------------------------------------
# Si el objeto no existe, head_object lanza ClientError. Eso nos sirve
# para detectar si hay lock o manifest antes de intentar bajarlos.
# ---------------------------------------------------------------------------

def verificar_existencia():
    try:
        respuesta = s3.head_object(Bucket=bucket, Key=KEY_PRUEBA)
        print(f"[head] Existe '{KEY_PRUEBA}'")
        print(f"[head] Tamaño: {respuesta['ContentLength']} bytes")
        print(f"[head] Última modificación: {respuesta['LastModified']}")
        return True
    except ClientError:
        print(f"[head] Todavía no existe '{KEY_PRUEBA}'")
        return False


# ---------------------------------------------------------------------------
# 6. Borrar un objeto: delete_object
# ---------------------------------------------------------------------------
# No falla si el objeto no existe: S3 es idempotente en el borrado.
# ---------------------------------------------------------------------------

def borrar_prueba():
    s3.delete_object(Bucket=bucket, Key=KEY_PRUEBA)
    print(f"[borrar] Eliminado '{KEY_PRUEBA}'")


# ---------------------------------------------------------------------------
# 7. Ejemplo de uso
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Estado inicial ===")
    listar()

    print("\n=== Subir ===")
    subir_prueba()

    print("\n=== Verificar existencia ===")
    verificar_existencia()

    print("\n=== Descargar ===")
    descargar_prueba()

    print("\n=== Listar con prefix ===")
    listar(prefix="prue")

    # print("\n=== Borrar ===")
    # borrar_prueba()