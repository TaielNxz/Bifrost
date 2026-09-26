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

Un lock contiene jugador, máquina, fecha de adquisición y vencimiento. Su duración actual es de 12 horas.
