# Configuración de R2

Copiá `.env.example` como `.env` y completá:

- `R2_ENDPOINT`: endpoint S3 del bucket de Cloudflare R2.
- `R2_ACCESS_KEY_ID`: identificador de la credencial.
- `R2_SECRET_ACCESS_KEY`: secreto de la credencial.
- `R2_BUCKET`: nombre del bucket.
- `VALHEIM_WORLDS_PATH`: carpeta `worlds_local` de Valheim.
- `PLAYER_NAME`: nombre que aparecerá en locks y manifests.

La credencial necesita permisos para listar, leer, escribir y eliminar objetos del bucket. No compartas `.env` ni pegues secretos en logs o incidencias.
