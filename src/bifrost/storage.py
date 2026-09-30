import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import Settings
from .models import Manifest, WorldLock
from .paths import WORLDS_PREFIX, lock_key, manifest_key


class ConcurrentUpdateError(RuntimeError):
    """Indica que una escritura condicional perdió una carrera remota."""


class R2Storage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        """Inicializa el acceso a R2 con un cliente provisto o uno nuevo de boto3."""
        settings.validate_r2()
        self.bucket = settings.r2_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version="s3v4"),
        )

    @staticmethod
    def _is_not_found(error: ClientError) -> bool:
        """Indica si un error S3 representa un objeto inexistente."""
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    def get_json(self, key: str) -> dict[str, Any] | None:
        """Lee un objeto JSON o devuelve None cuando la clave no existe."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._is_not_found(error):
                return None
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def get_json_with_etag(self, key: str) -> tuple[dict[str, Any] | None, str | None]:
        """Lee un JSON junto con su ETag o devuelve dos valores None si no existe."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._is_not_found(error):
                return None, None
            raise
        value = json.loads(response["Body"].read().decode("utf-8"))
        return value, response["ETag"]

    def put_json(self, key: str, value: dict[str, Any]) -> None:
        """Serializa y guarda un diccionario como objeto JSON en R2."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(value, indent=4, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

    def put_json_conditional(
        self, key: str, value: dict[str, Any], expected_etag: str | None
    ) -> str:
        """Escribe un JSON solo si el objeto conserva el ETag esperado."""
        condition = {"IfNoneMatch": "*"} if expected_etag is None else {"IfMatch": expected_etag}
        try:
            response = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(value, indent=4, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
                **condition,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"PreconditionFailed", "412"} or status == 412:
                raise ConcurrentUpdateError("El estado remoto cambió durante la operación.") from error
            raise
        return response["ETag"]

    def delete(self, key: str) -> None:
        """Elimina de R2 el objeto correspondiente a una clave."""
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def copy(self, source_key: str, destination_key: str) -> None:
        """Copia un objeto dentro del mismo bucket sin descargarlo."""
        self.client.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            Key=destination_key,
        )

    def list_keys(self, prefix: str) -> list[str]:
        """Lista todas las claves existentes bajo un prefijo, incluida la paginación."""
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
        return [item["Key"] for page in pages for item in page.get("Contents", [])]

    def upload_file(self, local_path: str | os.PathLike[str], key: str) -> None:
        """Sube un archivo local a la clave remota indicada."""
        with Path(local_path).open("rb") as file:
            self.client.upload_fileobj(file, self.bucket, key)

    def download_file(self, key: str, destination: str | os.PathLike[str]) -> Path:
        """Descarga un objeto remoto y devuelve su ruta local de destino."""
        path = Path(destination)
        with path.open("wb") as file:
            self.client.download_fileobj(self.bucket, key, file)
        return path

    def read_manifest(self, world_name: str) -> Manifest | None:
        """Lee el manifest remoto de un mundo si existe."""
        value = self.get_json(manifest_key(world_name))
        return value  # type: ignore[return-value]

    def read_lock(self, world_name: str) -> WorldLock | None:
        """Lee el lock remoto de un mundo si existe."""
        value = self.get_json(lock_key(world_name))
        return value  # type: ignore[return-value]

    def list_worlds(self) -> list[str]:
        """Lista alfabéticamente los mundos presentes bajo el prefijo remoto."""
        response = self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=f"{WORLDS_PREFIX}/", Delimiter="/"
        )
        names = [
            item["Prefix"].rstrip("/").split("/")[-1]
            for item in response.get("CommonPrefixes", [])
        ]
        return sorted(names, key=str.lower)

