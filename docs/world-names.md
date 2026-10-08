# Nombres de mundos y destinos seguros

Bifröst aplica una regla compartida a los nombres de carpetas locales, los prefijos de mundos en R2 y los nombres declarados en los manifests. Las comprobaciones se aplican también al ejecutar fuera de Windows.

## Reglas aceptadas

Un nombre debe ser una cadena de texto no vacía y representar una sola carpeta. Se rechazan:

- `.` y `..`, rutas absolutas, unidades y rutas relativas a una unidad como `C:Asgard`.
- Los separadores `/` y `\`, incluidos los intentos de recorrer directorios como `../Asgard`.
- Caracteres de control Unicode de categoría `Cc`, incluidos NUL, tabulaciones y saltos de línea.
- Los caracteres `<`, `>`, `:`, `"`, `|`, `?` y `*`.
- Nombres terminados en punto o espacio.
- Los dispositivos reservados `CON`, `PRN`, `AUX`, `NUL`, `CONIN$`, `CONOUT$`, `COM1` a `COM9` y `LPT1` a `LPT9`. También se rechazan `COM` y `LPT` con los dígitos en superíndice `¹`, `²` o `³`. La comparación ignora mayúsculas y reconoce dispositivos con extensión o espacios antes del primer punto: `nul.txt` y `CON .zip` también son inválidos.
- Los nombres `.bifrost-copies` y `.bifrost-state.json`, y cualquier nombre que contenga `_backup_` o `_pre_pull_`, sin distinguir mayúsculas. Están reservados para copias, estado y backups de Bifröst.

Los espacios interiores, acentos y otros caracteres Unicode válidos se conservan. Ejemplos aceptados: `Asgard`, `Mi mundo`, `Peña del Dragón`, `Bifröst`, `Mundo.v2` y `世界`. Puntos interiores como los de `Asgard..v2` no son referencias al directorio padre.

Bifröst no recorta espacios, no sustituye caracteres, no trunca nombres ni normaliza Unicode. El nombre original se mantiene en carpetas, claves remotas y manifests; las copias y backups agregan sus propios sufijos.

## Mayúsculas y conflictos

Para comparar nombres, Bifröst utiliza `casefold()` sin normalización Unicode. Si dos nombres distintos tienen la misma clave de comparación, todos los miembros del grupo se bloquean. Repetir exactamente un nombre en un listado remoto no crea un conflicto.

Por ejemplo, `Asgard` y `asgard` no se ofrecen como mundos independientes. La detección remota reúne todas las páginas del listado antes de habilitar mundos. La comparación es conservadora y no reproduce exactamente todas las reglas del sistema de archivos de Windows.

Antes de subir, también se revisa si el nombre local coincide con un nombre remoto escrito de otra forma. Antes de descargar para hostear, se comprueba lo mismo respecto de la carpeta local existente. Esos conflictos se bloquean sin renombrar carpetas ni elegir una identidad remota distinta. Una entrada única de la base local puede buscarse sin distinguir mayúsculas y se conserva con su escritura original; varias entradas coincidentes son ambiguas y bloquean las operaciones de ese mundo que necesitan registrar una base.

El listado previo de R2 detecta conflictos existentes, pero no reserva nombres atómicamente entre claves de mundos distintos. Dos primeras publicaciones simultáneas de variantes como `Asgard` y `asgard` pueden crear un conflicto que se bloqueará en los siguientes listados. Los commits condicionales de `state.json` protegen cada clave exacta de mundo.

## Destinos locales

Las rutas del mundo, sus backups, las copias y el registro de bases deben permanecer bajo la carpeta local prevista. Se rechazan enlaces simbólicos y junctions bajo esa raíz, incluso cuando apuntan a otra ubicación dentro de ella. La revisión del contenido de los mundos y de las carpetas preparadas también rechaza enlaces antes de empaquetar o reemplazar datos.

Cada componente local se comprueba contra un máximo de 255 unidades UTF-16. Esto incluye los nombres generados para backups y copias. Un nombre puede ser válido por sí solo y exceder el límite al agregar el sufijo de una operación; Bifröst lo informa sin truncarlo. Las restricciones adicionales del sistema de archivos, los permisos o la longitud total de una ruta pueden causar errores operativos.

Antes de adquirir un lock para hostear se revisan el destino, el futuro backup y el registro de base local. Antes de descargar una copia se revisa su nombre y destino en `.bifrost-copies`. Las funciones que guardan o instalan vuelven a comprobar sus destinos al realizar la operación.

Las carpetas locales con marcadores de backup y `.bifrost-copies` se omiten de la detección de mundos. Los demás nombres inválidos o conflictivos se identifican y se excluyen, permitiendo operar sobre mundos válidos.

## Identidad y ubicación remota

El campo `world` de cada manifest debe ser un nombre válido y coincidir exactamente con el nombre del prefijo remoto consultado, incluidos acentos y mayúsculas. Su versión debe ser un entero positivo, excluyendo booleanos.

El campo `filename` debe corresponder a una de estas claves para ese mismo mundo:

```text
worlds/<nombre>/current/world.zip
worlds/<nombre>/versions/<versión>/world.zip
worlds/<nombre>/versions/<versión>/<upload-id>/world.zip
```

Las dos primeras formas conservan compatibilidad con ZIP heredados. En las claves versionadas, la versión debe coincidir con el manifest y escribirse como el entero, sin ceros iniciales. El identificador de subida debe ser un único componente válido; las nuevas publicaciones usan un UUID hexadecimal. Las claves se comparan literalmente, sin decodificar porcentajes ni interpretar rutas.

La identidad se valida al leer el estado canónico o heredado y antes de publicarlo. El historial valida también que la versión del manifest corresponda a la clave consultada. Un manifest con un nombre distinto o un ZIP situado en otro mundo se bloquea antes de descargar, copiar objetos o cambiar el estado por esa operación. Un estado canónico inválido no provoca una vuelta a la metadata heredada.

Los menús informan el motivo de exclusión de un mundo con metadata inválida y mantienen visibles los demás. Estas comprobaciones validan la identidad y la ubicación; no constituyen una validación completa de todos los esquemas JSON remotos.

## Verificación local

Las pruebas usan carpetas temporales, archivos ficticios y clientes de almacenamiento simulados. Cubren reglas de nombres, conflictos entre páginas y entre mundos locales y remotos, manifests incompatibles, destinos inseguros y rechazo antes de mutaciones. El flujo completo comprueba que espacios y acentos se conserven al subir, descargar una copia, hostear y publicar progreso, incluida la compatibilidad heredada.

Desde la raíz del repositorio, con las dependencias de desarrollo instaladas:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Estas pruebas no cargan `.env`, no necesitan credenciales y no consultan R2 ni mundos reales. No reemplazan una verificación de integración con infraestructura compartida, que requiere autorización explícita.
