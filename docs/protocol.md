# Protocolo remoto

Cada mundo usa estas claves en R2:

```text
worlds/<nombre>/state.json
worlds/<nombre>/versions/<versión>/<upload-id>/world.zip
worlds/<nombre>/versions/<versión>/manifest.json
worlds/<nombre>/backups/<fecha>.zip
```

`state.json` es la fuente de verdad y contiene revisión, manifest vigente y lock. Para migrar instalaciones existentes, Bifröst todavía puede leer `manifest.json`, `lock.json` y `current/world.zip` heredados cuando `state.json` no existe.

La clave de backups fechados está reservada. El historial automático utiliza `versions/` y conserva la versión vigente más cinco versiones anteriores.

Cada ZIP nuevo se sube a una clave única e inmutable. Después se publica `state.json` con `If-Match` sobre el ETag leído, o `If-None-Match: *` para crear el primer estado. El manifest incluido en el estado es el puntero oficial y contiene versión, mundo, clave del ZIP, tamaño, SHA-256, autor y fecha UTC.

Push valida una vez el manifest y el lock del snapshot leído. El commit condicional falla con conflicto si cualquier otro cliente modifica ese estado durante la preparación. Un push exitoso publica el manifest nuevo y libera el lock en la misma escritura.

Los datos publicados permanecen bajo `versions/<versión>/`; el manifest auxiliar facilita inspeccionar el historial. Una publicación fallida por concurrencia elimina su ZIP candidato. Después del commit se eliminan las versiones que excedan la vigente más cinco anteriores.

Un lock contiene jugador, máquina, fecha de adquisición y vencimiento. Su duración actual es de 12 horas.

## Versión base local

Cada pull y push exitoso registra en `.bifrost-state.json` la versión y el SHA-256 que pasan a ser la base del mundo local. Antes de publicar, ambos valores deben coincidir con el manifest remoto vigente. Una discrepancia o la ausencia del registro cuando ya existe un manifest bloquea la subida; este control evita que una copia derivada de una versión anterior reemplace progreso más reciente.

Una descarga para hostear también registra el `session_id` aleatorio del lock. Aunque dos máquinas usen el mismo `PLAYER_NAME`, solamente la sesión que adquirió ese lock puede publicarlo y liberarlo mediante push.

El archivo de estado es local, vive directamente en `VALHEIM_WORLDS_PATH` y no se publica en R2 ni se incluye en los ZIP.

## Tipos de descarga

La descarga para hostear verifica y extrae el ZIP, reemplaza el mundo local de forma recuperable, registra la versión base y adquiere el lock remoto. La descarga de copia solamente verifica y guarda el ZIP en `.bifrost-copies`; no reemplaza el mundo activo, no registra una base y no adquiere ni modifica locks.
