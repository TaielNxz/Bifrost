import os
import socket
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    r2_endpoint: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    worlds_path: Path
    player_name: str

    def validate_r2(self) -> None:
        missing = [
            name
            for name, value in (
                ("R2_ENDPOINT", self.r2_endpoint),
                ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
                ("R2_BUCKET", self.r2_bucket),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Faltan variables de R2 en .env: {', '.join(missing)}")

    def validate_worlds_path(self) -> None:
        if not self.worlds_path.is_dir():
            raise RuntimeError(
                "La carpeta de mundos no existe:\n"
                f"  {self.worlds_path}\n"
                "Revisá VALHEIM_WORLDS_PATH en el archivo .env."
            )


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    load_dotenv(dotenv_path=env_file)
    raw_path = os.getenv("VALHEIM_WORLDS_PATH", "")
    expanded_path = os.path.expandvars(os.path.expanduser(raw_path))
    return Settings(
        r2_endpoint=os.getenv("R2_ENDPOINT", ""),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", ""),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", ""),
        r2_bucket=os.getenv("R2_BUCKET", ""),
        worlds_path=Path(expanded_path) if expanded_path else Path("__ruta_no_configurada__"),
        player_name=os.getenv("PLAYER_NAME") or socket.gethostname(),
    )
