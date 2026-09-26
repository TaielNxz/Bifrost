"""Comprueba configuración y listado de mundos sin modificar R2."""

from bifrost.config import load_settings
from bifrost.storage import R2Storage


def main() -> None:
    settings = load_settings()
    storage = R2Storage(settings)
    worlds = storage.list_worlds()
    print("Conexión con R2 correcta.")
    print(f"Mundos remotos: {len(worlds)}")
    for world in worlds:
        print(f"- {world}")


if __name__ == "__main__":
    main()
