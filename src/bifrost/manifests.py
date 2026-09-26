import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .archives import calculate_sha256
from .models import Manifest
from .paths import current_zip_key


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_manifest(
    zip_path: str | os.PathLike[str], world_name: str, version: int, uploaded_by: str
) -> Manifest:
    path = Path(zip_path)
    return {
        "version": version,
        "world": world_name,
        "filename": current_zip_key(world_name),
        "size": path.stat().st_size,
        "sha256": calculate_sha256(path),
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save_manifest(manifest: Manifest, destination: str | os.PathLike[str]) -> Path:
    path = Path(destination)
    path.write_text(json.dumps(manifest, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def next_version(remote_manifest: Manifest | None) -> int:
    return 1 if remote_manifest is None else remote_manifest["version"] + 1

