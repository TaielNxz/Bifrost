"""
menu.py — Interfaz de terminal para Valheim Sync.

Opciones:
    1. Subir un mundo      (push)
    2. Descargar un mundo  (pull)
    3. Salir

Ambos flujos comparten tres pasos que se extraen como helpers:
    - pedir_mundo()          → mostrar una lista y pedir elección
    - mostrar_comparacion()  → imprimir fechas local vs remoto
    - confirmar()            → [s/N] genérico
"""

import os
import shutil
from datetime import datetime

from local_valheim import listar_mundos, buscar_mundo, RUTA_MUNDOS
from main import (
    crear_zip,
    crear_manifest,
    subir_zip,
    subir_manifest,
    leer_manifest_remoto,
    parsear_fecha_iso,
    listar_mundos_remotos,
    descargar_zip,
    verificar_zip,
    descomprimir_zip,
)
from paths import key_current_zip, key_manifest


# ==========================================================================
# Helpers genéricos
# ==========================================================================

def confirmar(pregunta: str) -> bool:
    """Pide confirmación [s/N]. Devuelve True solo si la respuesta es 's'."""
    respuesta = input(f"{pregunta} [s/N]: ").strip().lower()
    return respuesta == "s"


def pedir_mundo(items: list, formatear, prompt: str = "Elegí un mundo"):
    """
    Muestra los items numerados (1..N) más una opción '0) Volver',
    pide al usuario que elija, y devuelve el item correspondiente.

    Parámetros:
        items:      lista de elementos a mostrar.
        formatear:  función que recibe un item y devuelve un string.
        prompt:     texto que se muestra al pedir la elección.

    Devuelve el item elegido, o None si el usuario elige volver o
    ingresa una opción inválida.
    """
    for i, item in enumerate(items, 1):
        print(f"  {i}) {formatear(item)}")
    print("  0) Volver")

    eleccion = input(f"\n{prompt}: ").strip()
    if eleccion == "0":
        return None

    try:
        indice = int(eleccion) - 1
        return items[indice]
    except (ValueError, IndexError):
        print("\nOpción inválida.")
        return None


def mostrar_comparacion(mundo_local, manifest_remoto: dict):
    """
    Imprime la comparación de fechas local vs remoto.

    Devuelve (fecha_remota, fecha_local) como datetimes aware, para que
    el llamador decida qué advertencia mostrar.
    """
    fecha_remota = parsear_fecha_iso(manifest_remoto["uploaded_at"])
    fecha_local = mundo_local.modificado.astimezone()

    print(f"\n[INFO] Comparando versiones...")
    print(f"       Remoto: versión {manifest_remoto['version']}, "
          f"fecha {fecha_remota:%Y-%m-%d %H:%M} UTC" 
          f" subido por {manifest_remoto['uploaded_by']}")
    print(f"       Local:  modificado {fecha_local:%Y-%m-%d %H:%M %Z}")

    return fecha_remota, fecha_local


# ==========================================================================
# Menú principal
# ==========================================================================

def menu_principal():
    while True:
        print("\n=== Valheim Sync ===")
        print("  1) Subir un mundo")
        print("  2) Descargar un mundo")
        print("  3) Salir")

        opcion = input("\nElegí una opción: ").strip()

        if opcion == "1":
            push_menu()
        elif opcion == "2":
            pull_menu()
        elif opcion == "3":
            print("\n¡Chau!")
            return
        else:
            print("\nOpción inválida.")


# ==========================================================================
# Chequeos de frescura
# ==========================================================================

def chequear_frescura_push(mundo, manifest_remoto: dict | None) -> int | None:
    """
    Compara la fecha del mundo local con la del manifest remoto antes
    de subir.

    Devuelve el número de versión nueva a usar, o None si el usuario
    cancela la operación.
    """
    if manifest_remoto is None:
        print(f"\n[INFO] No hay versión previa de '{mundo.nombre}' en la nube.")
        print("       Este será el primer push.")
        return 1

    fecha_remota, fecha_local = mostrar_comparacion(mundo, manifest_remoto)

    if fecha_remota > fecha_local:
        print(f"\n[!] La versión remota es MÁS NUEVA que tu versión local.")
        print(f"    Alguien jugó y subió después de tu última sesión.")
        print(f"    Si subís ahora, VAS A SOBRESCRIBIR ese progreso.")
        if not confirmar("\n¿Continuar igual?"):
            return None
    else:
        print(f"\n[OK] Tu versión local es igual o más nueva que la remota.")

    return manifest_remoto["version"] + 1


def chequear_frescura_pull(nombre: str, manifest_remoto: dict) -> bool:
    """
    Compara la fecha del mundo local con la del manifest remoto antes
    de bajar.

    Devuelve True si es seguro proceder, False si el usuario cancela.
    """
    mundo_local = buscar_mundo(nombre)

    # No hay mundo local: no hay nada que perder.
    if mundo_local is None:
        print(f"\n[INFO] No tenés '{nombre}' localmente. Se va a crear.")
        return True

    fecha_remota, fecha_local = mostrar_comparacion(mundo_local, manifest_remoto)

    if fecha_local > fecha_remota:
        print(f"\n[!] Tu versión local es MÁS NUEVA que la de la nube.")
        print(f"    Si descargás, VAS A PERDER los cambios locales.")
        if not confirmar("\n¿Continuar igual?"):
            return False
    else:
        print(f"\n[OK] La versión remota es igual o más nueva. Seguro bajar.")

    return True


# ==========================================================================
# Push (subir un mundo)
# ==========================================================================

def push_menu():
    print("\n=== Subir un mundo ===\n")

    mundos = listar_mundos()
    if not mundos:
        print("No hay mundos locales.")
        return

    def formatear(m):
        return (f"{m.nombre:<15} "
                f"({m.tamano_mb} MB, mod. {m.modificado:%Y-%m-%d %H:%M})")

    mundo = pedir_mundo(mundos, formatear)
    if mundo is None:
        return

    if not confirmar(f"\n¿Confirmás subir '{mundo.nombre}' a la nube?"):
        print("\nOperación cancelada.")
        return

    print(f"\n[INFO] Iniciando subida de '{mundo.nombre}'...")

    manifest_remoto = leer_manifest_remoto(mundo.nombre)
    version_nueva = chequear_frescura_push(mundo, manifest_remoto)
    if version_nueva is None:
        print("\nOperación cancelada.")
        return

    print()
    zip_path = crear_zip(mundo.nombre)
    manifest_path = crear_manifest(
        ruta_zip=zip_path,
        nombre_mundo=mundo.nombre,
        ruta_manifest=f"manifest_{mundo.nombre}.json",
        version=version_nueva,
    )

    subir_zip(zip_path, key_current_zip(mundo.nombre))
    subir_manifest(manifest_path, key_manifest(mundo.nombre))

    print(f"\n[OK] '{mundo.nombre}' subido correctamente (versión {version_nueva}).")


# ==========================================================================
# Pull (descargar un mundo)
# ==========================================================================

def hacer_backup_local(nombre: str) -> str | None:
    """
    Renombra la carpeta local del mundo a '<nombre>_pre_pull_<timestamp>'.

    Devuelve la ruta del backup, o None si el mundo no existía localmente.
    """
    mundo = buscar_mundo(nombre)
    if mundo is None:
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = os.path.join(RUTA_MUNDOS, f"{nombre}_pre_pull_{timestamp}")
    shutil.move(mundo.ruta, destino)
    print(f"[backup_local] '{nombre}' → '{destino}'")
    return destino


def pull_menu():
    print("\n=== Descargar un mundo ===\n")

    nombres = listar_mundos_remotos()
    if not nombres:
        print("No hay mundos en la nube todavía.")
        return

    # Armamos (nombre, manifest) solo para los que tienen manifest legible.
    info_mundos = []
    for nombre in nombres:
        manifest = leer_manifest_remoto(nombre)
        if manifest is not None:
            info_mundos.append((nombre, manifest))

    if not info_mundos:
        print("No se pudo leer el manifest de ningún mundo.")
        return

    def formatear(item):
        nombre, m = item
        fecha = parsear_fecha_iso(m["uploaded_at"])
        return (f"{nombre:<15} "
                f"(versión {m['version']}, fecha {fecha:%Y-%m-%d %H:%M} UTC, subido por {m['uploaded_by']})")

    elegido = pedir_mundo(info_mundos, formatear)
    if elegido is None:
        return

    nombre, manifest_remoto = elegido

    if not confirmar(f"\n¿Descargar '{nombre}' y reemplazar tu copia local?"):
        print("\nOperación cancelada.")
        return

    if not chequear_frescura_pull(nombre, manifest_remoto):
        return

    backup = hacer_backup_local(nombre)

    zip_temporal = f"pull_{nombre}.zip"
    try:
        descargar_zip(key_current_zip(nombre), zip_temporal)
    except Exception as e:
        print(f"\n[ERROR] Falló la descarga: {e}")
        if backup:
            print(f"[INFO] Tu mundo original sigue intacto en '{backup}'.")
        return

    if not verificar_zip(zip_temporal, manifest_remoto):
        print(f"\n[!] El ZIP descargado no coincide con el manifest.")
        if backup:
            print(f"    Tu mundo original sigue intacto en '{backup}'.")
        os.remove(zip_temporal)
        return

    destino = os.path.join(RUTA_MUNDOS, nombre)
    descomprimir_zip(zip_temporal, destino)

    os.remove(zip_temporal)

    print(f"\n[OK] '{nombre}' descargado y verificado.")
    if backup:
        print(f"[INFO] Tu versión anterior está en '{backup}'.")
        print(f"       Podés borrarla cuando confirmes que todo está bien.")


# ==========================================================================
# Entrypoint
# ==========================================================================

if __name__ == "__main__":
    menu_principal()