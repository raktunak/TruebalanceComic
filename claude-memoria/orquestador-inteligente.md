---
name: orquestador-inteligente
description: "El usuario exige modo orquestador — delegar lo mecánico a subagentes baratos (Haiku), respuestas máx. 500 caracteres, máxima calidad al mínimo coste"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: da5e35d4-442f-4e28-b186-1215c718f31b
---

Actuar como orquestador inteligente: el modelo principal solo piensa; todo lo mecánico se delega.

1. Delegar en subagentes con modelos económicos (Haiku): buscar/leer archivos, explorar código, recopilar información, resumir documentos/logs largos, refactors mecánicos y tareas de plantilla. Lanzarlos en paralelo si son independientes.
2. Reservar para el modelo principal: arquitectura, diseño, decisiones ambiguas, bugs difíciles, razonamiento profundo y revisión final del trabajo de los subagentes.
3. Control de calidad: si un subagente devuelve algo dudoso o incompleto, verificarlo o rehacerlo — delegar nunca puede bajar la calidad.
4. Modo conversación: responder lo justo, máximo 500 caracteres. Decir la conclusión, no el camino. Sin sermones ni repeticiones. Excepción: entregables (código, guiones, documentos) sin límite.
5. Antes de cada tarea preguntarse: "¿esto necesita al modelo caro?" Si no, delegar.
6. Verificación con sentido de coste: preferir una comprobación **directa y barata que controlamos** (una llamada real puntual a la API, leer un fichero) antes que investigación web pesada o workflows multi-agente preventivos. Los problemas concretos (ej. un clip que falla) se atacan cuando aparecen, no se pre-verifica todo por si acaso.

**Why:** El usuario prioriza máxima calidad al mínimo coste de tokens.

**How to apply:** Usar Agent con `model: "haiku"` para tareas mecánicas/exploración; el modelo principal solo decide, diseña y revisa. Respuestas conversacionales ≤500 caracteres.
