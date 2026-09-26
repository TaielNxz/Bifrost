# AGENTS.md

## Proyecto

Bifröst es una herramienta de terminal escrita en Python para compartir mundos de Valheim entre un grupo sin servidor dedicado. La persona que va a hostear descarga la versión vigente desde Cloudflare R2, reemplaza su copia local y conserva un backup; al terminar, sube el mundo actualizado para que otro integrante pueda continuar desde el mismo estado.

El objetivo central es que el traspaso sea simple y seguro: evitar intercambiar archivos manualmente por Discord, Drive u otros servicios, reducir el riesgo de sobrescribir progreso y detectar transferencias corruptas.

El idioma actual del código, los mensajes de terminal y la documentación es español. Conservá ese criterio salvo que el usuario pida cambiarlo.

## Fuente de verdad y alcance de este documento

- Para describir el comportamiento **actual**, el código ejecutable tiene prioridad sobre README, archivos didácticos, comentarios y planes expresados en conversaciones.
- No asumas que una función descrita como objetivo ya está terminada: comprobala en el flujo real.
- El paquete instalable vive en `src/bifrost`; las pruebas están en `tests`, la documentación en `docs` y las utilidades manuales en `scripts`.
- La disposición de objetos dentro de R2 forma parte del protocolo compartido y se describe más abajo; no debe confundirse con la estructura del repositorio.
- `docs/` contiene documentación, no pruebas ejecutables. La suite automatizada es `tests/`.

## Estructura del repositorio

```text
.
├── src/
│   └── bifrost/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── local_worlds.py
│       ├── storage.py
│       ├── manifests.py
│       ├── locks.py
│       ├── archives.py
│       └── paths.py
├── tests/
│   ├── test_archives.py
│   ├── test_local_worlds.py
│   ├── test_manifests.py
│   ├── test_locks.py
│   └── test_sync_flows.py
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   └── r2-setup.md
├── scripts/
│   └── check_r2_connection.py
├── pyproject.toml
├── README.md
├── AGENTS.md
├── .env.example
└── .gitignore
```

Responsabilidades y reglas de dependencia:

- `src/bifrost/` es el único paquete de aplicación. No agregues nuevos módulos Python ejecutables en la raíz.
- `__main__.py` expone `python -m bifrost`; el entrypoint de consola configurado en `pyproject.toml` apunta a `bifrost.cli:main`.
- `cli.py` contiene la interacción con el usuario y coordina push, pull y locks. Los demás módulos no deben importar la CLI ni pedir datos con `input()`.
- `config.py` carga y valida `.env`; no debe crear conexiones remotas al importarse.
- `models.py` contiene los tipos compartidos (`World`, `Manifest` y `WorldLock`).
- `local_worlds.py` concentra detección, medición, backup e instalación de mundos locales.
- `storage.py` encapsula el cliente S3/R2 y sus operaciones de bajo nivel.
- `manifests.py` construye manifests, interpreta fechas y calcula la siguiente versión.
- `locks.py` contiene creación, vencimiento, adquisición y liberación de locks; las confirmaciones pertenecen a `cli.py`.
- `archives.py` concentra compresión, SHA-256, verificación y extracción segura.
- `paths.py` define exclusivamente las claves del protocolo remoto.
- `tests/` contiene pruebas automatizadas y no debe requerir credenciales, R2 ni mundos reales.
- `docs/` explica arquitectura, protocolo y configuración. `scripts/` contiene utilidades manuales que pueden acceder a servicios reales y deben ser explícitas sobre sus efectos.
- `pyproject.toml` es la fuente de verdad para metadata, dependencias, empaquetado, entrypoints y configuración de tests.

La dirección general de dependencias es `cli → lógica especializada → filesystem/R2`. Evitá dependencias inversas e importaciones circulares.

## Modelo funcional actual

### Configuración

La aplicación carga variables desde `.env` mediante `python-dotenv`:

- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `VALHEIM_WORLDS_PATH`, con expansión de variables como `%USERPROFILE%` y `~`
- `PLAYER_NAME` es opcional; si falta, se usa el hostname

Nunca leas, muestres, copies ni confirmes al repositorio el contenido de `.env`. Usá `.env-example` para documentar configuración y mantenelo sin secretos.

### Mundos locales

- Cada subcarpeta directa de `VALHEIM_WORLDS_PATH` se considera un mundo.
- Se ignoran carpetas cuyo nombre contiene `_backup_`.
- El tamaño se calcula recursivamente.
- La fecha local usada en comparaciones es el `mtime` de la carpeta raíz del mundo.
- El ZIP incluye todos los archivos y subdirectorios con rutas relativas. Esto permite transportar la estructura moderna de Valheim (por ejemplo `.fwl2`, `.db2`, `.chunks`), sin depender de una lista fija de extensiones.

### Protocolo remoto en R2

R2 se usa mediante la API compatible con S3 (`boto3`). Las claves vigentes son:

```text
worlds/<nombre>/manifest.json
worlds/<nombre>/lock.json
worlds/<nombre>/current/world.zip
worlds/<nombre>/backups/<fecha>.zip   # helper existente, flujo aún no implementado
```

El manifest actual contiene:

- `version`: entero creciente calculado a partir del manifest remoto anterior
- `world`: nombre del mundo
- `filename`: clave completa del ZIP vigente
- `size`: tamaño del ZIP en bytes
- `sha256`: hash SHA-256 del ZIP
- `uploaded_by`: autor/máquina
- `uploaded_at`: fecha UTC en formato ISO 8601 terminada en `Z`

El push sube primero `current/world.zip` y después `manifest.json`. Este orden es una invariante de seguridad: el manifest funciona como puntero publicado a la versión vigente y debe escribirse al final.

### Flujo de push

1. Lista mundos locales y permite elegir uno.
2. Pide confirmación.
3. Lee el manifest remoto y compara `uploaded_at` con el `mtime` local.
4. Advierte y pide otra confirmación si el remoto parece más nuevo.
5. Asigna versión 1 si no hay manifest; de lo contrario usa `version + 1`.
6. Comprime el mundo, genera el manifest y sube ZIP antes que manifest.
7. Si existe un lock activo perteneciente al jugador actual, lo libera.

### Flujo de pull

1. Lista mundos remotos a partir de prefijos bajo `worlds/` y conserva los que tienen manifest legible.
2. Pide confirmación y compara frescura local/remota.
3. Comprueba el lock; un lock ajeno activo requiere confirmación para forzarlo.
4. Escribe un lock nuevo para el jugador actual, con vencimiento de 12 horas.
5. Descarga el ZIP a un directorio temporal, comprueba su SHA-256 y lo extrae en staging validando sus rutas internas.
6. Recién entonces mueve el mundo existente a `<nombre>_pre_pull_<YYYYMMDD-HHMMSS>` e instala el mundo preparado. Si falla el movimiento final, intenta restaurar el anterior.
7. El lock queda activo para representar que ese jugador va a hostear. Un push posterior del mismo jugador lo libera.

El menú también permite inspeccionar y liberar locks; liberar un lock ajeno exige confirmación.

## Invariantes que deben preservarse

- Nunca publiques el manifest nuevo antes de terminar de subir el ZIP correspondiente.
- Nunca reemplaces silenciosamente progreso local o remoto cuando la comprobación disponible detecta que el destino parece más nuevo.
- Nunca aceptes un ZIP descargado cuyo SHA-256 difiera del manifest.
- Antes de sustituir un mundo local existente, debe existir una vía clara de recuperación.
- Nunca rompas ni liberes un lock ajeno sin una confirmación explícita.
- Un push solo debe liberar un lock si pertenece al jugador actual.
- Usá tiempos UTC en metadata remota; convertí de forma consciente al comparar con tiempos locales.
- Las rutas guardadas dentro de ZIP deben ser relativas y portables.
- No registres credenciales, archivos `.env`, mundos reales, ZIP generados ni manifests temporales con información de una sesión.

## Limitaciones y discrepancias conocidas

No describas estos puntos como resueltos hasta comprobar cambios en el código:

- El push no comprueba ni adquiere el lock antes de sobrescribir la versión remota. El lock se consulta allí solamente para liberar uno propio al final.
- La frescura depende del `mtime` de la carpeta raíz, que no es un indicador robusto de la modificación más reciente de todos sus archivos.
- Hay un helper para claves de backups remotos, pero el flujo no crea ni restaura backups en R2.
- La subida no realiza una verificación posterior del objeto remoto con `head_object` ni vuelve a descargarlo para comparar hash.
- La numeración `manifest.version + 1` no es atómica; pushes concurrentes pueden colisionar.
- Los nombres de mundo se interpolan directamente en claves y nombres locales temporales; falta una política explícita de validación/sanitización.
- Las lecturas JSON remotas distinguen objetos ausentes de otros errores S3, pero todavía no validan el esquema de manifests o locks recibidos.

## Criterios para cambios futuros

- Antes de editar, recorré el flujo afectado de punta a punta; hay dependencias cruzadas y estado remoto/local.
- Preferí cambios pequeños y verificables que respeten los límites documentados en `docs/architecture.md`.
- Mantené separadas la lógica de dominio, el filesystem, R2, la configuración y la UI.
- Evitá importaciones circulares. Los helpers de UI como confirmaciones no deben ser dependencia de módulos de dominio/remotos.
- Tratá como operaciones transaccionales los reemplazos locales: descargar y validar primero, preparar en una ubicación separada y hacer el cambio final de manera recuperable.
- Validá que el mundo no esté siendo usado por Valheim antes de copiar o reemplazarlo si se implementa esa capacidad.
- Diferenciá "objeto inexistente" de otros errores S3 (`ClientError`) y mostrá fallos accionables sin filtrar secretos.
- Si modificás el formato del manifest, las claves R2 o la semántica de locks, consideralo un cambio de protocolo compartido entre todas las PCs; mantené compatibilidad o incluí una migración explícita.
- No asumas que el nombre del jugador identifica de manera única una máquina o sesión.
- Conservá la compatibilidad con Windows como plataforma principal actual, incluidas rutas con espacios, acentos y variables `%USERPROFILE%`.

## Verificación esperada

Al tocar código, realizá como mínimo las comprobaciones aplicables:

1. Compilación/importación de todos los módulos principales sin efectos destructivos.
2. Pruebas locales con un mundo falso en un directorio temporal; nunca uses un mundo real para validar cambios.
3. Round trip de compresión: mismo conjunto de rutas y mismos bytes antes y después.
4. Casos de hash correcto e incorrecto.
5. Pull sin mundo local, pull con mundo local, cancelaciones y recuperación frente a descarga/hash/descompresión fallidos.
6. Lock ausente, propio, ajeno, expirado y override cancelado/confirmado.
7. Primer push y push con manifest anterior, incluida la advertencia de frescura.
8. Para pruebas R2, usá un bucket/prefijo de prueba y credenciales provistas por el entorno; no ejecutes integraciones que puedan tocar mundos compartidos sin autorización explícita.

Si no se puede ejecutar una prueba por falta de credenciales o infraestructura, dejá constancia exacta de qué se verificó localmente y qué quedó sin validar.
