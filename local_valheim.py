"""
local_valheim.py — Utilidades para trabajar con los mundos locales de Valheim.

Este módulo detecta la carpeta de mundos de Valheim y lista los mundos
disponibles, ignorando los backups (carpetas con "_backup_" en el nombre).

La ruta se lee del archivo .env en la variable VALHEIM_WORLDS_PATH.
"""

import os
from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv


# 1. Cargar configuración
load_dotenv()
_RUTA_RAW = os.getenv("VALHEIM_WORLDS_PATH", "")
RUTA_MUNDOS = os.path.expandvars(os.path.expanduser(_RUTA_RAW))


# 2. Modelo de datos: un mundo
@dataclass
class Mundo:
    nombre: str
    ruta: str
    tamano_bytes: int
    modificado: datetime

    @property
    def tamano_mb(self) -> float:
        return round(self.tamano_bytes / (1024 * 1024), 2)


# 3. Verificar que la carpeta de mundos existe
def verificar_ruta() -> None:
    if not RUTA_MUNDOS:
        raise RuntimeError(
            "Falta VALHEIM_WORLDS_PATH en el archivo .env"
        )
    if not os.path.isdir(RUTA_MUNDOS):
        raise RuntimeError(
            f"La carpeta de mundos no existe:\n  {RUTA_MUNDOS}\n"
            f"Verificá que Valheim esté instalado y que hayas jugado al menos una vez."
        )

# 4. Detectar si una carpeta es un backup
def es_backup(nombre_carpeta: str) -> bool:
    return "_backup_" in nombre_carpeta


# 5. Calcular el tamaño total de una carpeta
def calcular_tamano(ruta_carpeta: str) -> int:
    total = 0
    for ruta_actual, _, archivos in os.walk(ruta_carpeta):
        for nombre in archivos:
            ruta_completa = os.path.join(ruta_actual, nombre)
            try:
                total += os.path.getsize(ruta_completa)
            except OSError:
                pass
    return total


# 6. Listar mundos reales (no backups)
def listar_mundos() -> list[Mundo]:
    verificar_ruta()

    mundos: list[Mundo] = []

    for entrada in os.listdir(RUTA_MUNDOS):
        ruta_completa = os.path.join(RUTA_MUNDOS, entrada)

        # Solo nos interesan carpetas.
        if not os.path.isdir(ruta_completa):
            continue

        # Ignoramos backups.
        if es_backup(entrada):
            continue
        
        # Datos del mundo
        tamano = calcular_tamano(ruta_completa)
        modificado = datetime.fromtimestamp(os.path.getmtime(ruta_completa))

        # Lo agregamos a la lista
        mundos.append(Mundo(
            nombre=entrada,
            ruta=ruta_completa,
            tamano_bytes=tamano,
            modificado=modificado,
        ))

    mundos.sort(key=lambda m: m.nombre.lower())
    return mundos


# 7. Buscar un mundo por nombre
def buscar_mundo(nombre: str) -> Mundo | None:
    for mundo in listar_mundos():
        if mundo.nombre.lower() == nombre.lower():
            return mundo
    return None


# 8. Imprimir información de los mundos
def imprimir_mundos():
    print(f"Carpeta de mundos:\n  {RUTA_MUNDOS}\n")

    try:
        mundos = listar_mundos()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)

    if not mundos:
        print("No se encontraron mundos (solo backups o carpeta vacía).")
        raise SystemExit(0)

    print(f"Mundos encontrados: {len(mundos)}\n")
    for m in mundos:
        print(f"  • {m.nombre}")
        print(f"      Ruta:       {m.ruta}")
        print(f"      Tamaño:     {m.tamano_mb} MB")
        print(f"      Modificado: {m.modificado:%Y-%m-%d %H:%M}")
        print()

    
if __name__ == "__main__":
    imprimir_mundos()