import os
from dotenv import load_dotenv
import boto3
from botocore.client import Config

load_dotenv()

endpoint = os.getenv("R2_ENDPOINT")
access_key = os.getenv("R2_ACCESS_KEY_ID")
secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
bucket = os.getenv("R2_BUCKET")

s3 = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
)

def listar():
    resp = s3.list_objects_v2(Bucket=bucket)
    for obj in resp.get("Contents", []):
        print(obj["Key"], obj["Size"])

def subir():
    s3.put_object(Bucket=bucket, Key="prueba.txt", Body=b"Hola R2")

def descargar():
    resp = s3.get_object(Bucket=bucket, Key="prueba.txt")
    print(resp["Body"].read().decode())

if __name__ == "__main__":
    listar()
    subir()
    descargar()