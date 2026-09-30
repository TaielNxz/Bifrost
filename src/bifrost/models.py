from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict


@dataclass(frozen=True)
class World:
    name: str
    path: Path
    size_bytes: int
    modified_at: datetime

    @property
    def size_mb(self) -> float:
        """Devuelve el tamaño del mundo expresado en megabytes."""
        return round(self.size_bytes / (1024 * 1024), 2)


class Manifest(TypedDict):
    version: int
    world: str
    filename: str
    size: int
    sha256: str
    uploaded_by: str
    uploaded_at: str


class LocalBase(TypedDict):
    version: int
    sha256: str


class WorldLock(TypedDict):
    player: str
    machine: str
    acquired_at: str
    expires_at: str
