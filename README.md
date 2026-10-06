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
6) Salir
```

Si el grupo todavía no subió ningún mundo, quien tenga el original debe elegir **Subir un mundo** para compartirlo por primera vez.

Para las siguientes partidas, usá **Descargar para hostear** antes de jugar y **Subir un mundo** al terminar. Para volver a abrir Bifröst otro día, repetí el comando de este paso.
