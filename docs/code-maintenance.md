# Guía de mantenimiento del código

Procedimiento para optimización, refactorización, organización, pruebas y documentación de Bifröst. Un mismo chat completa el cambio de punta a punta. Priorizá mantenibilidad, escalabilidad y comprensión humana, conservando el comportamiento existente.

## Contexto compartido

- Leé el [AGENTS.md vigente](../AGENTS.md) y los archivos afectados. Consultá [arquitectura](architecture.md) y [protocolo](protocol.md) cuando la tarea los involucre; el código ejecutable es la fuente de verdad.
- Para el estilo de comentarios, docstrings y secciones, usá [la guía de documentación](code-documentation.md). Sus restricciones de edición corresponden a tareas limitadas a documentación; un refactor puede modificar estructura y nombres dentro del alcance aprobado.
- Usá [la guía de revisión](code-review.md) para evaluar la propuesta y el resultado. Estas guías son procedimientos del mismo chat, no requieren chats adicionales.

## Responsabilidades y límites

- Reducí complejidad, duplicación y trabajo innecesario; mejorá nombres, organización y responsabilidades de módulos y funciones.
- Revisá dependencias, código aparentemente muerto, abstracciones innecesarias y convenciones inconsistentes. Confirmá usos, imports, entrypoints y pruebas antes de eliminar o renombrar elementos.
- Mantené actualizados los comentarios, docstrings, pruebas y documentación que el cambio afecte. Son parte de terminar el trabajo, aunque el pedido principal sea un refactor.
- Conservá comportamiento observable, mensajes y confirmaciones de la CLI, manejo de errores, compatibilidad e invariantes. Las correcciones funcionales y los cambios de protocolo requieren autorización explícita separada, salvo que ya estén incluidos en el pedido aprobado.
- La medición de puntos lentos no es una responsabilidad asignada. No agregues profiling ni benchmarks por iniciativa propia; justificá las optimizaciones con trabajo redundante identificable y no afirmes mejoras de rendimiento no verificadas.

## Criterios de diseño

- Preferí la solución más simple que resuelva el problema concreto. No prepares extensiones hipotéticas ni agregues capas, clases o dependencias sin una necesidad demostrable.
- Separá UI, dominio, filesystem y R2 según `AGENTS.md`. Evitá acoplamientos circulares y efectos al importar módulos.
- Extraé helpers cuando den nombre a una responsabilidad clara o eliminen duplicación significativa. No fragmentes una secuencia legible en funciones que obliguen a saltar continuamente entre archivos.
- Unificá bloques similares solo si comparten reglas y efectos; el parecido sintáctico no alcanza. Una abstracción no debe ocultar diferencias de confirmación, locks o persistencia.
- Al reordenar o extraer código, conservá el orden de efectos y el comportamiento ante cancelaciones, fallos y concurrencia. Revisá contratos, llamadores y referencias a los nombres modificados.
- Dividí cambios grandes en unidades coherentes que puedan entenderse, aprobarse y verificarse por separado.

## Flujo de trabajo y aprobación

1. **Analizar:** inspeccioná el estado de trabajo y recorré el flujo completo, incluidos llamadores, helpers, pruebas y documentación relevante. Preservá cambios previos del usuario.
2. **Proponer:** explicá el problema, la modificación concreta, los archivos afectados, el beneficio, los riesgos relevantes y cómo comprobarás que se conserva el comportamiento.
3. **Esperar confirmación:** cada cambio necesita aprobación explícita. Una confirmación puede cubrir el conjunto presentado; no la solicites nuevamente para ese alcance. Si aparece trabajo adicional, presentalo antes de aplicarlo.
4. **Implementar:** limitate al alcance aprobado y actualizá los textos y pruebas afectados. Informá errores descubiertos fuera de alcance sin corregirlos automáticamente.
5. **Verificar:** revisá el diff y ejecutá las comprobaciones aplicables. Usá las pruebas previas como referencia cuando sea necesario distinguir errores existentes de regresiones.
6. **Entregar:** resumí qué cambió, por qué, qué se verificó y qué quedó pendiente. No hagas commits, publicaciones ni integraciones remotas por el solo hecho de terminar la edición.

## Verificación

- Ejecutá pruebas locales con `python -m unittest discover -s tests -v` o `python -m pytest`. Para `unittest`, incluí `src` en la ruta de importación si el paquete no está instalado.
- Cumplí la cobertura específica de ZIP, pull, locks y push indicada en `AGENTS.md`. Usá temporales y almacenamiento falso; no leas `.env` ni toques mundos o buckets reales sin autorización explícita.
- Agregá o ajustá pruebas cuando falte protección de un comportamiento relevante. Evitá pruebas que solo reproduzcan la implementación o cambios de pruebas que oculten una regresión.
- Para cambios exclusivamente documentales o de ubicación de definiciones, comprobá que el código ejecutable se conserve; el AST puede ayudar. Para refactors, verificá equivalencia de comportamiento: el AST normalmente cambiará.
- Cuando las pruebas aplicables pasen, ampliá la verificación solo si hay nuevos cambios, fallos o dudas concretas. Informá con precisión pruebas fallidas, no ejecutadas y limitaciones de cobertura.

## Uso en otro chat

«Leé `AGENTS.md` y `docs/code-maintenance.md`. Analizá `<archivo o flujo>` para mejorar su mantenibilidad y claridad. Presentame propuestas concretas antes de modificar y aplicá únicamente los cambios que confirme».
