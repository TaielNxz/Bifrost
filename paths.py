"""
paths.py — Construcción de claves (keys) dentro del bucket de R2.

En S3/R2 no existen carpetas reales: las claves son strings con barras.
Pero las tratamos como si fueran rutas para organizar el bucket así:

    worlds/
    ├── Asgard/
    │   ├── manifest.json
    │   ├── lock.json
    │   ├── current/
    │   │   └── world.zip
    │   └── backups/
    │       └── 2026-09-25_20-30.zip
    └── Mundazo/
        └── ...
"""

PREFIJO_MUNDOS = "worlds"


def key_manifest(nombre_mundo: str) -> str:
    return f"{PREFIJO_MUNDOS}/{nombre_mundo}/manifest.json"


def key_lock(nombre_mundo: str) -> str:
    return f"{PREFIJO_MUNDOS}/{nombre_mundo}/lock.json"


def key_current_zip(nombre_mundo: str) -> str:
    return f"{PREFIJO_MUNDOS}/{nombre_mundo}/current/world.zip"


def key_backup(nombre_mundo: str, fecha: str) -> str:
    return f"{PREFIJO_MUNDOS}/{nombre_mundo}/backups/{fecha}.zip"


def prefijo_mundo(nombre_mundo: str) -> str:
    """Prefijo para listar todo lo de un mundo."""
    return f"{PREFIJO_MUNDOS}/{nombre_mundo}/"