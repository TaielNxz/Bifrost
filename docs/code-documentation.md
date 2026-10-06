# Criterios de documentación y organización del código

Guía para una IA que revise docstrings, comentarios y secciones de Bifröst. El objetivo es código mantenible, escalable y fácil de entender para humanos. Aplicá también el `AGENTS.md` vigente; el código ejecutable es la fuente de verdad.

Para usarla en otro chat: «Leé `docs/code-documentation.md` y revisá `<archivo>` siguiendo sus criterios. Presentame los cambios propuestos antes de implementarlos».

## Alcance y aprobación

- Revisá docstrings, comentarios, nombres de secciones y ubicación de funciones. Conservá lógica, firmas, nombres de funciones, mensajes al usuario y protocolo.
- Antes de proponer cambios, leé las funciones completas y recorré el flujo afectado, incluidos los helpers que determinan su comportamiento.
- Presentá propuestas concretas y su motivo. Cada cambio requiere confirmación explícita del usuario; una aprobación puede abarcar el conjunto presentado. No vuelvas a pedir aprobación para ese mismo alcance.
- Si detectás un error ejecutable, informalo y solicitá aprobación separada para corregirlo. No lo corrijas dentro de una tarea de documentación sin autorización.
- Conservá los cambios previos del usuario. No agregues refactors, abstracciones ni mediciones de rendimiento ajenos al alcance aprobado.

## Docstrings

- Todas las funciones deben tener docstring, incluidas las privadas y las funciones internas definidas con `def`.
- Escribí en español, con una a tres oraciones según lo necesario. La primera debe explicar el propósito por sí sola, para entenderlo desde la descripción del IDE.
- Explicá qué hace la función, sin describir toda su implementación ni enumerar parámetros o tipos que ya se leen en la firma.
- Agregá otra oración cuando aclare un resultado relevante, una confirmación, una restricción o un efecto importante. Por ejemplo, cuándo devuelve `None` o si reemplaza el mundo local.
- Describí el alcance real: comprobación, presentación y modificación son responsabilidades diferentes. Incluí excepciones relevantes a la regla general, como permitir una primera publicación sin base previa.
- No prometas validaciones, garantías o restricciones que el código no aplica. Evitá frases vagas como «Gestiona el mundo».
- Usá triple comilla doble. En docstrings de varias líneas, separá el resumen del detalle con una línea vacía y usá saltos reales, sin `\n` explícitos.

## Comentarios internos

Comentá bloques significativos, decisiones y motivos. Preferí una línea breve, colocada junto al bloque que describe, con redacción uniforme y punto final. Podés ampliar una explicación cuando sea necesaria para comprender una decisión importante.

### A. Funciones organizadas por escenarios

- Usá `# Caso 1: Condición; consecuencia.` y numeración consecutiva en el orden de lectura.
- Numerá escenarios funcionales, no cada `if`. No es obligatorio que exista un escenario principal.
- Usá subcasos (`1.1`, `1.2`) cuando pertenecen a un mismo escenario. Preferí una estructura plana si evita jerarquías innecesarias.
- Incluí el escenario final implícito tras retornos anticipados cuando ayude a entender el resultado.
- La numeración existente puede corregirse; debe representar las condiciones actuales.

### B. Funciones con una secuencia principal

- Comentá las etapas relevantes sin exigir numeración: consulta, selección, confirmación, validación, preparación, publicación e información final, según corresponda.
- Distinguí resultados normales (por ejemplo, una lista vacía), cancelaciones del usuario, conflictos y errores. Una salida anticipada no convierte automáticamente toda la función en una función por escenarios.
- Usá etiquetas como `# Cancelación: ...`, `# Conflicto: ...` o `# Error de integridad: ...` cuando aclaren la respuesta del sistema. Un caso de error no implica necesariamente una excepción de Python.
- Si una etapa contiene decisiones locales importantes, puede tener casos numerados. Ambas formas de comentar pueden coexistir.

### Precisión y cantidad

- Explicá intención y motivos que el código no hace evidentes: usar temporales, proteger progreso, conservar backups o subir el ZIP antes del commit.
- Evitá traducir instrucciones obvias, como «Muestra el nombre» encima de `print(world_name)`. Las funciones triviales pueden quedar claras con su docstring solamente.
- No repitas el docstring, los mensajes de consola ni los números visibles del menú sin aportar información.
- Describí hechos comprobados: ausencia de manifest no demuestra borrado; comparar fechas no demuestra quién modificó el mundo ni ausencia de cambios. El `mtime` de la carpeta es una advertencia secundaria; versión y hash base controlan el conflicto.
- Respetá el orden real de los efectos. Si el commit ya liberó el lock, un `print` posterior solo informa esa liberación.
- Corregí o eliminá comentarios incorrectos, redundantes o desactualizados. No alteres el código para hacer verdadero un comentario.

## Secciones y ubicación

Las secciones son opcionales. Usalas cuando haya grupos de funciones con responsabilidades distintas y los separadores faciliten la lectura. Un archivo pequeño que encapsula una responsabilidad clara, generalmente expresada en su nombre, puede no necesitar ninguna sección. No agregues separadores para envolver todo el archivo ni para cada función.

Cuando correspondan, agrupá por responsabilidad, usá nombres concretos y conservá separadores uniformes de tres líneas:

```python
# ======================================================================================= #
# Interacción con el usuario
# ======================================================================================= #
```

En `cli.py`, la organización acordada es:

| Orden | Sección | Funciones |
| --- | --- | --- |
| 1 | Formato y presentación | `_format_size`, `show_world_comparison` |
| 2 | Interacción con el usuario | `confirm`, `choose` |
| 3 | Consulta de mundos remotos | `_remote_worlds` |
| 4 | Validaciones y confirmaciones | `allow_push`, `allow_pull`, `_allow_lock_override`, `_allow_push_lock` |
| 5 | Acciones del menú | `status_menu`, `push_menu`, `pull_menu`, `copy_menu`, `lock_menu` |
| 6 | Menú principal e inicio | `run_menu`, `main` |

Dejá imports y declaraciones comunes al inicio. Conservá `format_lock` dentro de `lock_menu`, donde se utiliza. En otros archivos, adaptá las secciones a sus responsabilidades; no copies esta lista mecánicamente. Reordená definiciones solo cuando preserve su comportamiento y mantené separadas UI, dominio, filesystem y R2.

## Ejemplos de estilo

Fragmentos ilustrativos; no son cambios pendientes ni instrucciones para agregarlos al proyecto.

```python
def allow_replacement(local_date, remote_date):
    """Determina si se puede reemplazar la copia local.

    Pide confirmación cuando la fecha local es posterior a la remota.
    """
    # Caso 1: No existe una copia local; permite crearla.
    if local_date is None:
        return True

    # Caso 2: La fecha local es posterior; requiere confirmación.
    if local_date > remote_date:
        return confirm("¿Reemplazar la copia local?")

    # Caso 3: La fecha remota es igual o posterior; permite continuar.
    return True
```

```python
# Descarga a un temporal para verificar el ZIP antes de guardarlo como copia.
with tempfile.TemporaryDirectory() as temporary_dir:
    zip_path = storage.download_file(key, Path(temporary_dir) / "world.zip")

    # Error de integridad: descarta la descarga sin guardar una copia.
    if not verify_zip(zip_path, expected_hash):
        print("El ZIP descargado no coincide con el manifest.")
        return

    # Guarda la copia verificada en su destino.
    shutil.copyfile(zip_path, destination)
```

## Verificación y entrega

- Comprobá cobertura de docstrings, exactitud de comentarios, numeración, ubicación de funciones y formato del diff.
- Verificá que solo cambien documentación y ubicación de definiciones. Una comparación del AST puede ignorar docstrings y reordenamientos autorizados, pero debe conservar instrucciones, condiciones y llamadas.
- Ejecutá las pruebas locales aplicables con `python -m unittest discover -s tests -v` o `python -m pytest`. Para `unittest` en un proyecto con layout `src`, incluí `src` en la ruta de importación si no está instalado.
- No leas `.env` ni uses credenciales, mundos reales o buckets compartidos. No ejecutes integraciones remotas sin autorización explícita.
- Informá qué cambió, qué se verificó y cualquier error previo o limitación pendiente. No presentes como exitosas pruebas que fallaron o no se ejecutaron.
