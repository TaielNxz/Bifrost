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

Push lee una vez el estado y su ETag, y valida la identidad del manifest, la base local y el lock antes de publicar. El commit condicional falla con conflicto si cualquier otro cliente modifica ese estado durante la preparación. Un push exitoso publica el manifest nuevo y libera el lock en la misma escritura.

Los datos publicados permanecen bajo `versions/<versión>/`; el manifest auxiliar facilita inspeccionar el historial. Una publicación fallida por concurrencia elimina su ZIP candidato. Después del commit se eliminan las versiones que excedan la vigente más cinco anteriores.

Un lock contiene jugador, máquina, fecha de adquisición y vencimiento. Su duración actual es de 12 horas.

## Nombres e identidad

Los nombres se validan con las [reglas compartidas de Bifröst](world-names.md) antes de construir claves. Se preservan los espacios, acentos y mayúsculas originales. Los listados reúnen todas las páginas y bloquean nombres inválidos o grupos que coincidan al comparar con `casefold()`.

El campo `world` de un manifest debe coincidir exactamente con el nombre consultado. El ZIP debe estar en `current/world.zip`, en `versions/<versión>/world.zip` o en `versions/<versión>/<upload-id>/world.zip` bajo ese mismo mundo. Una clave versionada debe coincidir con la versión declarada, y un manifest histórico con la versión de su propia clave. La lectura canónica y heredada aplica estos controles; un estado canónico inválido no se sustituye por metadata heredada.

Antes de subir se comprueban también los conflictos entre nombres locales y remotos. Ese listado no es una reserva atómica para primeras publicaciones simultáneas de nombres que difieran solo en mayúsculas. La escritura condicional protege únicamente el `state.json` de la clave exacta consultada; el protocolo no agrega una identidad global ni migra nombres existentes.

## Versión base local

Cada pull y push exitoso registra en `.bifrost-state.json` la versión y el SHA-256 que pasan a ser la base del mundo local. Antes de publicar, ambos valores deben coincidir con el manifest remoto vigente. Una discrepancia o la ausencia del registro cuando ya existe un manifest bloquea la subida; este control evita que una copia derivada de una versión anterior reemplace progreso más reciente.

Una descarga para hostear también registra el `session_id` aleatorio del lock. Aunque dos máquinas usen el mismo `PLAYER_NAME`, solamente la sesión que adquirió ese lock puede publicarlo y liberarlo mediante push.

El archivo de estado es local, vive directamente en `VALHEIM_WORLDS_PATH` y no se publica en R2 ni se incluye en los ZIP.

## Tipos de descarga

La descarga para hostear verifica y extrae el ZIP, reemplaza el mundo local de forma recuperable, registra la versión base y adquiere el lock remoto. La descarga de copia solamente verifica y guarda el ZIP en `.bifrost-copies`; no reemplaza el mundo activo, no registra una base y no adquiere ni modifica locks.

## Restauración compartida

`restore_world_version` publica contenido histórico mediante una operación explícita, independiente del push y de la base local. La CLI conserva el `StateSnapshot` leído antes de seleccionar el mundo y confirmar; no renueva su ETag para publicar.

1. Se exige un manifest vigente válido y ausencia de locks activos, incluso del solicitante. Un lock inválido bloquea la operación aunque declare una fecha vencida. Los locks heredados sin sesión o versión base siguen siendo compatibles si sus campos presentes son válidos.
2. El listado reconoce solo claves exactas `versions/<versión>/manifest.json`, anteriores a la vigente, con metadata válida del mismo mundo y versión. Los ZIP sin registro, las claves auxiliares y los registros de versiones actuales o futuras no se ofrecen como versiones anteriores.
3. La selección requiere confirmación explícita del efecto para todo el grupo. Volver o rechazarla termina sin descargas de ZIP ni mutaciones locales o remotas.
4. Se vuelve a validar el registro elegido y se descarga su ZIP a un temporal. Se verifican SHA-256, tamaño, legibilidad, CRC y rutas relativas portables antes de preservar el historial o subir un candidato. Se admiten las ubicaciones históricas con y sin `upload-id`; un registro histórico no puede apuntar al `current/world.zip` mutable.
5. Se preserva el registro de la vigente mediante creación condicional. Si su ZIP usa la clave heredada mutable, se copia primero a una clave versionada única. Los registros existentes se conservan si describen la misma publicación; una discrepancia bloquea la operación. Un registro ya existente para la siguiente versión también impide reutilizar su número.
6. Se suben los bytes originales del ZIP verificado a `versions/<vigente + 1>/<upload-id>/world.zip`. El nuevo manifest conserva tamaño y SHA-256 del contenido histórico, declara el número siguiente y registra al jugador que restaura y una fecha UTC nueva.
7. Solo después de completar ese ZIP se publica `state.json` con el ETag original, o con `If-None-Match: *` al crear estado canónico desde metadata heredada. La revisión aumenta y el commit publica el manifest y deja el lock en `null` atómicamente. No adquiere un lock de hosting.
8. Tras confirmar el commit, el registro de la nueva versión se crea con `If-None-Match: *`, sin sobrescribir historial. Para la retención se consulta la versión vigente más reciente y se conserva esa versión y hasta cinco anteriores publicadas. Los directorios sin registro y los futuros no cuentan como publicaciones. Se eliminan todos los objetos de las versiones publicadas que exceden el límite, incluidos sus ZIP candidatos.

Por ejemplo, recuperar la versión 5 sobre la vigente 8 publica la versión 9. El ZIP histórico y los registros conservados mantienen su identidad; no se cambia el número de la publicación anterior ni se reescribe su autoría.

Un conflicto de precondición conserva el estado ganador y elimina únicamente el ZIP candidato de la restauración. Si falla ese borrado, se informa que quedó un candidato. Ante una respuesta incierta del commit se conserva el ZIP, porque podría ser el oficialmente publicado; la CLI indica consultar el estado antes de reintentar.

Un fallo del historial o de la retención después del commit se devuelve como aviso de mantenimiento pendiente junto a la publicación confirmada. No revierte el estado ni elimina su ZIP. Los fallos de acceso o conexión se distinguen de objetos ausentes sin mostrar respuestas S3, endpoints ni credenciales.

La operación no recibe una ruta de mundos, no instala contenido ni modifica `.bifrost-state.json` o `.bifrost-copies`. El push normal sigue exigiendo versión, SHA-256 y sesión base coincidentes. Después de restaurar hay que descargar la nueva vigente mediante el flujo de hosting antes de publicar progreso desde ella.

Las pruebas locales recorren la CLI, el dominio, el adaptador `R2Storage` con S3 en memoria y carpetas temporales. Cubren restauración, copia, bloqueo de una base anterior, pull con backup y sesión, push posterior, compatibilidad heredada, cancelación, corrupción y conflictos. No acceden a R2 ni usan mundos reales.
