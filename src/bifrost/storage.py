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


class R2Storage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
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
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._is_not_found(error):
                return None
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def put_json(self, key: str, value: dict[str, Any]) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(value, indent=4, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def upload_file(self, local_path: str | os.PathLike[str], key: str) -> None:
        with Path(local_path).open("rb") as file:
            self.client.upload_fileobj(file, self.bucket, key)

    def download_file(self, key: str, destination: str | os.PathLike[str]) -> Path:
        path = Path(destination)
        with path.open("wb") as file:
            self.client.download_fileobj(self.bucket, key, file)
        return path

    def read_manifest(self, world_name: str) -> Manifest | None:
        value = self.get_json(manifest_key(world_name))
        return value  # type: ignore[return-value]

    def write_manifest(self, world_name: str, manifest: Manifest) -> None:
        self.put_json(manifest_key(world_name), manifest)

    def read_lock(self, world_name: str) -> WorldLock | None:
        value = self.get_json(lock_key(world_name))
        return value  # type: ignore[return-value]

    def write_lock(self, world_name: str, world_lock: WorldLock) -> None:
        self.put_json(lock_key(world_name), world_lock)

    def delete_lock(self, world_name: str) -> None:
        self.delete(lock_key(world_name))

    def list_worlds(self) -> list[str]:
        response = self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=f"{WORLDS_PREFIX}/", Delimiter="/"
        )
        names = [
            item["Prefix"].rstrip("/").split("/")[-1]
            for item in response.get("CommonPrefixes", [])
        ]
        return sorted(names, key=str.lower)

