# Guía de revisión del código

Procedimiento para revisar propuestas o cambios de Bifröst dentro del mismo chat de mantenimiento. Buscá problemas concretos de comportamiento, claridad, arquitectura, compatibilidad y verificación. La revisión informa hallazgos; no modifica archivos por defecto.

## Contexto y alcance

- Leé el [AGENTS.md vigente](../AGENTS.md), el código actual y la propuesta o diff. Recorré el flujo afectado, incluidos llamadores y helpers; no dependas únicamente del historial del chat.
- Aplicá los criterios de [mantenimiento](code-maintenance.md) y de [documentación](code-documentation.md) según la tarea. Consultá los documentos técnicos relevantes y contrastalos con el código ejecutable.
- Identificá qué se pidió y qué se aprobó. Diferenciá problemas introducidos por el cambio, problemas previos y oportunidades opcionales de mejora.
- Si revisás una implementación, identificá su versión o estado de trabajo y confirmá que no cambió durante la revisión. Si cambia, reevaluá las partes afectadas.

## Qué evaluar

| Aspecto | Comprobación |
| --- | --- |
| Alcance | El cambio resuelve lo aprobado sin incorporar modificaciones funcionales o de protocolo ajenas al pedido. |
| Comportamiento | Se conservan resultados, mensajes, confirmaciones, retornos, errores y orden de efectos, incluidos cancelaciones, fallos y concurrencia. |
| Arquitectura | Las responsabilidades y dependencias respetan `AGENTS.md`; las extracciones no mezclan UI, dominio, filesystem y R2. |
| Claridad | Nombres, estructura y abstracciones ayudan a entender el flujo; no hay fragmentación, duplicación ni generalización innecesarias. |
| Compatibilidad | Se actualizaron referencias y llamadores, y se conservan formatos persistidos, protocolo y compatibilidad con Windows, espacios y acentos. |
| Documentación | Docstrings, comentarios, secciones y documentos afectados describen el resultado real con el estilo acordado. |
| Pruebas | La cobertura protege comportamientos relevantes e invariantes; los resultados informados corresponden a comprobaciones realizadas. |

Los contratos e invariantes detallados viven en `AGENTS.md`; no los reemplaces por supuestos. Una mejora estética no justifica cambiar comportamiento ni sumar abstracciones.

## Verificación

- Contrastá el diff con el estado anterior y las reglas aprobadas. Para un refactor, buscá equivalencia de comportamiento, no identidad textual.
- Ejecutá las pruebas locales aplicables cuando revises código implementado. Para una propuesta todavía no implementada, evaluá su plan de verificación sin afirmar que fue probado.
- Si aparece un fallo, determiná si existía antes. No atribuyas una regresión al cambio sin evidencia ni ajustes las pruebas para obtener un resultado positivo.
- Respetá las restricciones de infraestructura de `AGENTS.md`: sin lectura de `.env`, secretos, mundos reales ni integraciones remotas no autorizadas.

## Cómo presentar hallazgos

- Ordená primero los problemas que puedan romper comportamiento o invariantes, luego los de mantenibilidad y finalmente las sugerencias opcionales.
- Para cada hallazgo, indicá **ubicación**, **condición que lo expone**, **consecuencia** y **corrección propuesta**. Para mejoras estructurales, explicá el problema de mantenimiento y el beneficio concreto.
- Sustentá las afirmaciones con código, un ejemplo o una prueba. Si falta evidencia, señalá la incertidumbre y qué permitiría resolverla; no presentes sospechas como errores confirmados.
- Evitá observaciones de gusto personal sin una regla acordada o un beneficio claro. No repitas el mismo problema en cada línea afectada.
- Si no hay hallazgos, decilo y resumí qué se revisó y las limitaciones. Eso no equivale a garantizar ausencia de errores.
- Toda corrección posterior requiere la confirmación del usuario según la guía de mantenimiento. Conservá cualquier autorización que ya cubra ese cambio.

## Uso en otro chat

«Leé `AGENTS.md` y `docs/code-review.md`. Revisá `<propuesta, archivo o diff>` y presentá hallazgos concretos y su justificación. No modifiques archivos hasta que confirme las correcciones».
