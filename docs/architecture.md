# Arquitectura

El código instalable vive en `src/bifrost`. La terminal depende de los módulos funcionales; los módulos funcionales nunca importan la terminal.

- `cli.py`: menús, confirmaciones y coordinación de push/pull.
- `config.py`: carga y validación de configuración.
- `models.py`: tipos compartidos.
- `local_worlds.py`: detección, backup y reemplazo local.
- `archives.py`: ZIP, SHA-256 y extracción segura.
- `storage.py`: operaciones de bajo nivel contra R2/S3.
- `manifests.py`: metadata, fechas y versiones.
- `locks.py`: creación, vencimiento y persistencia de locks.
- `paths.py`: claves del protocolo remoto.

La conexión R2 se crea al iniciar la aplicación, no al importar el paquete. Esto permite ejecutar pruebas locales sin credenciales ni acceso a red.
