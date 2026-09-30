# AGENTS.md

## Proyecto

Bifröst es una CLI en Python que permite a un grupo compartir mundos de Valheim mediante Cloudflare R2. Quien va a hostear descarga la versión vigente, conserva un backup local y, al terminar, publica el progreso para el siguiente jugador.

El código, la interfaz y la documentación están en español. El código ejecutable es la fuente de verdad sobre el comportamiento actual.

## Repositorio y arquitectura

```text
src/bifrost/   paquete de aplicación
tests/         pruebas automatizadas locales
docs/          arquitectura, protocolo y configuración
scripts/       utilidades manuales
pyproject.toml metadata, dependencias y entrypoints
```

Módulos del paquete:

- `cli.py`: interacción y coordinación de estado, push, descargas y locks.
- `config.py`: carga y validación de `.env`.
- `models.py`: `World`, `Manifest` y `WorldLock`.
- `local_worlds.py`: detección, backup, instalación local y copias independientes.
- `local_state.py`: versión y SHA-256 base de cada mundo local.
- `storage.py`: operaciones S3/R2.
- `manifests.py`: metadata, fechas y versiones.
- `locks.py`: creación, vencimiento y persistencia de locks.
- `archives.py`: ZIP, SHA-256 y extracción segura.
- `paths.py`: claves del protocolo remoto.

Dependencias: `cli → lógica especializada → filesystem/R2`. Ningún módulo debe importar `cli.py` ni usar `input()` fuera de ella. No crees conexiones remotas al importar módulos ni agregues ejecutables Python en la raíz.

## Configuración

Variables: `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `VALHEIM_WORLDS_PATH` y `PLAYER_NAME` (opcional; usa el hostname como fallback). La ruta admite `%USERPROFILE%` y `~`.

Nunca leas, muestres ni confirmes `.env` al repositorio. Documentá variables sin secretos en `.env-example`.

## Modelo funcional y protocolo

Cada subcarpeta directa de `VALHEIM_WORLDS_PATH` es un mundo, excepto nombres con `_backup_` o `_pre_pull_`. El ZIP conserva recursivamente todas las rutas relativas; no depende de extensiones específicas de Valheim.

Claves de R2:

```text
worlds/<nombre>/manifest.json
worlds/<nombre>/lock.json
worlds/<nombre>/current/world.zip
worlds/<nombre>/backups/<fecha>.zip  # reservada; flujo no implementado
```

El manifest contiene `version`, `world`, `filename`, `size`, `sha256`, `uploaded_by` y `uploaded_at` UTC. Push asigna `1` o `version + 1`, valida el lock antes de preparar y antes de transferir, sube primero el ZIP y publica el manifest al final. Un lock ajeno o inválido bloquea la publicación; después de un push exitoso se libera solamente un lock propio.

`.bifrost-state.json` vive directamente en `VALHEIM_WORLDS_PATH` y registra versión/hash base tras cada pull o push exitoso. Si existe un manifest remoto, el push exige una base local coincidente y se bloquea ante ausencia o discrepancia. El archivo no pertenece a ningún mundo ni se incluye en ZIP/R2.

La descarga para hostear reemplaza el mundo local, registra la base y adquiere el lock. La descarga de copia guarda un ZIP verificado en `.bifrost-copies`, carpeta excluida de la detección de mundos; no reemplaza el mundo, no registra una base y no toca locks.

La opción de estado es de solo lectura: muestra por mundo la versión, fecha, autor y tamaño del manifest, además del lock activo o el estado libre.

Pull compara frescura, exige confirmación para forzar un lock ajeno y adquiere un lock de 12 horas. Descarga a un temporal, verifica SHA-256 y extrae en staging con validación de rutas. Solo entonces mueve el mundo anterior a `<nombre>_pre_pull_<timestamp>` e instala el nuevo; ante un fallo del movimiento final intenta restaurar el original. El lock permanece activo hasta el push.

## Invariantes

- Nunca publiques el manifest antes de completar el ZIP correspondiente.
- Nunca publiques sobre un manifest que no coincida con la versión y hash base locales.
- Nunca publiques mientras exista un lock ajeno activo o no se pueda interpretar el lock.
- Nunca aceptes un ZIP cuyo SHA-256 no coincida.
- No sobrescribas progreso más nuevo ni un lock ajeno sin confirmación explícita.
- Todo reemplazo local debe ser recuperable y prepararse fuera de la carpeta activa.
- Usá UTC en metadata remota y rutas relativas portables dentro de ZIP.
- No registres secretos, `.env`, mundos reales ni artefactos de una sesión.
- Cambios en manifests, claves R2 o locks son cambios de protocolo compartido: mantené compatibilidad o incluí migración.
- Conservá compatibilidad con Windows, espacios, acentos y `%USERPROFILE%`.

## Limitaciones conocidas

- La validación del lock durante push reduce carreras, pero no es atómica con la escritura remota; el lock todavía puede cambiar entre la última comprobación y la publicación.
- La advertencia secundaria de frescura usa el `mtime` de la carpeta raíz, que puede no representar el archivo más reciente; el control autoritativo de conflictos usa versión y hash base.
- Los backups remotos todavía no se crean ni restauran.
- La subida no verifica posteriormente el objeto remoto.
- `version + 1` no es atómico; pushes concurrentes pueden colisionar.
- Falta validar/sanitizar nombres de mundo y esquemas JSON remotos.
- El nombre del jugador no identifica de forma única una sesión o máquina.

## Criterios de trabajo y verificación

- Antes de editar, recorré el flujo afectado de punta a punta y mantené separadas UI, dominio, filesystem y R2.
- Diferenciá objetos S3 inexistentes de errores de permisos, red o configuración sin filtrar secretos.
- Las pruebas no deben necesitar credenciales, R2 ni mundos reales; usá temporales y mundos falsos.
- Ejecutá las pruebas aplicables con `python -m unittest discover -s tests -v` o `python -m pytest`.
- Para cambios de ZIP, pull, locks o push cubrí respectivamente round trip/hash, recuperación ante fallos, estados de lock y orden ZIP → manifest.
- No ejecutes integraciones que puedan tocar mundos o buckets compartidos sin autorización explícita. Informá qué quedó sin validar si falta infraestructura.
