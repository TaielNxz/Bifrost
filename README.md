# Bifröst

## 1. ¿Qué es y cómo se usa?

Bifröst permite compartir un mundo de Valheim entre amigos para que cualquiera pueda abrir la partida cuando el anfitrión habitual no esté disponible.

El mundo se guarda en un almacenamiento compartido en la nube. Antes de jugar, quien va a abrir la partida descarga el mundo con Bifröst. Al terminar, lo sube para que el siguiente jugador continúe desde ese punto.

La rutina es sencilla:

1. Elegí **Descargar para hostear** antes de abrir el mundo en Valheim.
2. Jugá normalmente.
3. Cerrá el mundo en Valheim y elegí **Subir un mundo** para compartir el progreso.

Bifröst conserva una copia de seguridad antes de reemplazar tu mundo y marca quién lo está usando para ayudar a evitar partidas simultáneas. Si tu copia quedó desactualizada, bloquea la subida para proteger el progreso compartido.

También podés consultar el **Estado de los mundos** o **Descargar una copia**. Esta última opción guarda un ZIP sin reemplazar tu mundo ni reservarlo para jugar.

Coordinen quién va a abrir la partida. Si un mundo aparece en uso, hablá con ese jugador antes de forzar o liberar su bloqueo.

### Restaurar una versión anterior

Si el mundo compartido tiene un problema, elegí **Restaurar una versión anterior** para recuperar contenido del historial.

1. Elegí el mundo y una de sus versiones anteriores publicadas. La lista muestra número, fecha UTC, autor y tamaño; los ZIP de subidas interrumpidas no aparecen como versiones.
2. Revisá la confirmación: el contenido elegido pasará a ser el mundo vigente **para todo el grupo**.
3. Confirmá con `s`. Restaurar la versión 5 cuando la vigente es la 8 crea la **versión 9**, con tu nombre y la fecha de la restauración. Los números siguen aumentando.
4. Antes de jugar o subir progreso, usá **Descargar para hostear** para recibir la nueva vigente.

La restauración conserva tus mundos locales, sus registros de base y las copias independientes existentes. Una base anterior bloquea el push; **Descargar una copia** guarda un ZIP de la nueva vigente y tampoco habilita a publicar desde esa base.

Para restaurar no puede haber ninguna sesión de hosting activa, incluida la tuya. Los datos de bloqueo inválidos también impiden continuar. Coordiná con el grupo la finalización de cualquier sesión en curso.

Podés elegir `0` en cualquiera de los listados o rechazar la confirmación para cancelar sin cambiar archivos locales, bases, locks ni estado compartido. Bifröst verifica el archivo histórico antes de publicarlo; un archivo ausente, metadata inválida, rutas inseguras o un fallo de integridad bloquean la restauración y conservan la versión vigente. Si otro jugador publica o cambia el lock durante la operación, volvé a consultar las versiones.

Si aparece **«No se pudo confirmar la publicación»**, consultá **Estado de los mundos** antes de reintentar: la respuesta remota pudo perderse después de publicar. Una **[ADVERTENCIA]** de historial o retención después de **[OK]** indica que la nueva versión ya fue publicada y quedó mantenimiento incompleto.

La restauración recupera el mundo compartido. Para jugar se descarga la nueva vigente; el menú no instala ni guarda una copia independiente de la versión histórica elegida.

### Nombres de los mundos

El nombre de cada mundo es el de su carpeta. Podés usar espacios y acentos, por ejemplo `Peña del Dragón`; Bifröst conserva el nombre tal como está escrito.

Evitá nombres que sean rutas, caracteres prohibidos por Windows, nombres de dispositivos como `CON` o `NUL`, y nombres terminados en punto o espacio. Tampoco uses dos mundos cuyos nombres difieran solo en mayúsculas, como `Asgard` y `asgard`. La escritura del nombre local debe coincidir con la remota para subir o descargar para hostear.

Si Bifröst muestra `[BLOQUEADO]`, el mensaje identifica el nombre o conflicto y su motivo. Los demás mundos válidos siguen disponibles. Bifröst no renombra ni migra mundos automáticamente; coordiná con el grupo cualquier corrección de un mundo compartido antes de volver a intentar.

Consultá [las reglas completas de nombres y destinos](docs/world-names.md) para conocer las reservas de Bifröst, los límites de longitud y las comprobaciones de metadata remota.

## 2. Descargar, instalar y ejecutar

Los siguientes pasos están pensados para Windows.

### Paso 1: Instalá Python

Necesitás **Python 3.11 o posterior**. Podés descargarlo desde [python.org](https://www.python.org/downloads/).

Durante la instalación, activá la opción **Add Python to PATH**.

### Paso 2: Descargá Bifröst

Dentro del [repositorio de Bifröst](https://github.com/TaielNxz/Bifrost), seleccioná **Code → Download ZIP** y descomprimilo.

Abrí la carpeta descomprimida en una terminal de **PowerShell**.

### Paso 3: Instalá la aplicación

Ejecutá estos comandos, uno por uno:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
Copy-Item .env-example .env
```

### Paso 4: Configurá tu acceso

Abrí el archivo `.env` con un editor de texto y completá:

- `PLAYER_NAME`: tu nombre de jugador (este nombre se verá en Bifröst, NO es el nombre de tu personaje).
- `VALHEIM_WORLDS_PATH`: la carpeta donde Valheim guarda tus mundos locales.
- `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` y `R2_BUCKET`: los datos del almacenamiento compartido.

La ruta incluida usa `%USERPROFILE%` para apuntar a tu carpeta de usuario en Windows. Comprobá que corresponda a la ubicación de tu mundo.

Todos los integrantes deben conectarse al mismo almacenamiento. Pedile los datos a quien lo haya configurado; si todavía no existe, consultá [la guía de configuración de R2](docs/r2-setup.md).

El archivo `.env` contiene credenciales: mantenelo privado.

### Paso 5: Ejecutá Bifröst

Desde la carpeta de la aplicación, ejecutá:

```powershell
.\.venv\Scripts\python.exe -m bifrost
```

Vas a encontrar estas opciones:

```text
1) Estado de los mundos
2) Subir un mundo
3) Descargar para hostear
4) Descargar una copia
5) Ver/liberar lock
6) Restaurar una versión anterior
7) Salir
```

Si el grupo todavía no subió ningún mundo, quien tenga el original debe elegir **Subir un mundo** para compartirlo por primera vez.

Para las siguientes partidas, usá **Descargar para hostear** antes de jugar y **Subir un mundo** al terminar. Para volver a abrir Bifröst otro día, repetí el comando de este paso.
