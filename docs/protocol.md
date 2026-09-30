# Protocolo remoto

Cada mundo usa estas claves en R2:

```text
worlds/<nombre>/manifest.json
worlds/<nombre>/lock.json
worlds/<nombre>/current/world.zip
worlds/<nombre>/backups/<fecha>.zip
```

La clave de backups está reservada; el flujo actual todavía no publica backups remotos.

En un push se sube primero `current/world.zip` y luego `manifest.json`. El manifest es el puntero oficial a la versión vigente y contiene versión, mundo, clave del ZIP, tamaño, SHA-256, autor y fecha UTC.

El push consulta el lock antes de preparar la publicación y otra vez inmediatamente antes de transferir. Un lock ajeno activo o inválido bloquea la operación. Un lock propio permite publicar y se libera después del éxito; la ausencia de lock también permite continuar.

Un lock contiene jugador, máquina, fecha de adquisición y vencimiento. Su duración actual es de 12 horas.

## Versión base local

Cada pull y push exitoso registra en `.bifrost-state.json` la versión y el SHA-256 que pasan a ser la base del mundo local. Antes de publicar, ambos valores deben coincidir con el manifest remoto vigente. Una discrepancia o la ausencia del registro cuando ya existe un manifest bloquea la subida; este control evita que una copia derivada de una versión anterior reemplace progreso más reciente.

El archivo de estado es local, vive directamente en `VALHEIM_WORLDS_PATH` y no se publica en R2 ni se incluye en los ZIP.

## Tipos de descarga

La descarga para hostear verifica y extrae el ZIP, reemplaza el mundo local de forma recuperable, registra la versión base y adquiere el lock remoto. La descarga de copia solamente verifica y guarda el ZIP en `.bifrost-copies`; no reemplaza el mundo activo, no registra una base y no adquiere ni modifica locks.
