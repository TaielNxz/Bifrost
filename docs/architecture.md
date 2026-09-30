# Arquitectura

El código instalable vive en `src/bifrost`. La terminal depende de los módulos funcionales; los módulos funcionales nunca importan la terminal.

- `cli.py`: menús, confirmaciones y coordinación de push/pull.
- `config.py`: carga y validación de configuración.
- `models.py`: tipos compartidos.
- `local_worlds.py`: detección, backup, reemplazo local y copias independientes.
- `local_state.py`: registro persistente de la versión base de cada mundo local.
- `archives.py`: ZIP, SHA-256 y extracción segura.
- `storage.py`: operaciones de bajo nivel contra R2/S3.
- `remote_state.py`: lectura compatible y commits condicionales de `state.json`.
- `manifests.py`: metadata, fechas y versiones.
- `versions.py`: snapshots remotos y política de retención del historial.
- `locks.py`: creación, vencimiento y persistencia de locks.
- `paths.py`: claves del protocolo remoto.

La conexión R2 se crea al iniciar la aplicación, no al importar el paquete. Esto permite ejecutar pruebas locales sin credenciales ni acceso a red.

El archivo `.bifrost-state.json`, ubicado directamente en `VALHEIM_WORLDS_PATH`, guarda la versión y el SHA-256 remotos desde los que parte cada mundo local. No forma parte de las carpetas de mundos ni de sus ZIP.

Las descargas de copia se guardan como ZIP en `.bifrost-copies`, también bajo `VALHEIM_WORLDS_PATH`. Esa carpeta se excluye de la detección de mundos y sus archivos no alteran el estado local ni los locks.
