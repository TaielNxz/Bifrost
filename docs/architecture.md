# Arquitectura

El código instalable vive en `src/bifrost`. La terminal depende de los módulos funcionales; los módulos funcionales nunca importan la terminal.

- `cli.py`: menús, confirmaciones y coordinación de push, descargas y restauración.
- `config.py`: carga y validación de configuración.
- `models.py`: tipos compartidos.
- `local_worlds.py`: detección, backup, reemplazo local y copias independientes.
- `local_state.py`: registro persistente de la versión base de cada mundo local.
- `archives.py`: ZIP, SHA-256, validación de rutas y contenido, y extracción segura.
- `storage.py`: operaciones de bajo nivel contra R2/S3.
- `remote_state.py`: lectura compatible y commits condicionales de `state.json`.
- `manifests.py`: metadata, fechas y versiones.
- `versions.py`: listado de publicaciones, snapshots remotos y retención del historial.
- `restoration.py`: recuperación de contenido histórico mediante una nueva publicación condicional.
- `locks.py`: creación, vencimiento y persistencia de locks.
- `paths.py`: claves del protocolo remoto.
- `world_names.py`: reglas compartidas de nombres, comparación y detección de conflictos.
- `local_paths.py`: contención de rutas locales y rechazo de enlaces, junctions y componentes demasiado largos.

La conexión R2 se crea al iniciar la aplicación, no al importar el paquete. Esto permite ejecutar pruebas locales sin credenciales ni acceso a red.

El archivo `.bifrost-state.json`, ubicado directamente en `VALHEIM_WORLDS_PATH`, guarda la versión y el SHA-256 remotos desde los que parte cada mundo local. No forma parte de las carpetas de mundos ni de sus ZIP.

Las descargas de copia se guardan como ZIP en `.bifrost-copies`, también bajo `VALHEIM_WORLDS_PATH`. Esa carpeta se excluye de la detección de mundos y sus archivos no alteran el estado local ni los locks.

La CLI coordina las comprobaciones previas de nombres, identidades remotas y destinos antes de subir, descargar o cambiar locks. Los módulos de dominio y persistencia también validan sus entradas al construir claves, interpretar manifests y realizar operaciones locales. Los listados excluyen mundos inválidos o ambiguos y entregan sus motivos a la UI sin ocultar mundos válidos. Las reglas y sus límites se describen en [nombres de mundos y destinos seguros](world-names.md).

La restauración combina `versions.py` (listado y registros históricos), `locks.py` (bloqueo de cualquier sesión activa o datos inválidos) y `archives.py` (verificación sin extraer). `restoration.py` recibe el snapshot elegido por la CLI, prepara el ZIP en un temporal y publica por `remote_state.py` con el ETag original. La ruta del mundo local y su base quedan fuera de esa operación.

El resultado distingue una publicación confirmada de avisos posteriores de historial o retención. El push mantiene sus controles de base y sesión: restaurar exige descargar la nueva vigente antes de hostear o subir progreso. El flujo de usuario se describe en el [README](../README.md#restaurar-una-versión-anterior) y los detalles de persistencia en el [protocolo remoto](protocol.md#restauración-compartida).
