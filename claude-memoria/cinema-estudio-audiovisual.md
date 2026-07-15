---
name: cinema-estudio-audiovisual
description: "Rama 'cinema' de TruebalanceComic: extensión a estudio audiovisual multi-proyecto con biblias y consistencia. Decisiones de diseño, estado y setup. 2026-07-15"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8ca37473-6332-4f21-8e36-26e506008ac6
---

Rama **cinema** (commit c239c71, pusheada a origin 2026-07-15): convierte TruebalanceComic de
generador lineal en un **estudio audiovisual multi-proyecto** con biblias (personajes,
localizaciones, objetos, voces) e imagen de referencia aprobada como fuente de verdad. Docs en el
repo: `PLAN.md` (plan completo), `pendientes/PENDIENTES.md` (fuera de alcance), `HELPME.md` (setup).

**8 decisiones de diseño cerradas con el usuario (fuente de verdad, NO re-litigar):**
1. Character/Location Lock = imagen de referencia aprobada; se puede subir imagen o generar por prompt.
2. Multi-personaje en un plano: anclar en una imagen de conjunto y encadenar; etiquetado por posición.
3. Localizaciones = misma mecánica que personajes.
4. La IMAGEN manda siempre sobre el texto de la ficha.
5. Plano aprobado = independiente; cambiar una referencia base NO toca planos previos (sin cascadas/grafo).
6. Continuidad narrativa A MANO (sin motor de estado automático).
7. Modelo elegible en cada paso + coste real por paso + contador total (sin confirmación forzada).
8. SIN QC automático (`config.QC_ENABLED=False`): el sistema genera y muestra, el humano aprueba a ojo.
Prompts automáticos = núcleo, se mantienen. Edición = Nano Banana conversacional (`edit_image` tipado da 404).

**Construido y verificado (Vertex real + navegador):** biblias con CRUD y crear-por-prompt
(`services/bible.py`); `_scene_ref_parts` inyecta personaje+localización+objetos (`services/images.py`);
`edit_active_image` (edición conversacional que preserva identidad); voces con muestra (`audio.py`);
exportador JSON+ZIP (`exporter.py`); UI de estudio con menú lateral y selectores de modelo con precio.

**Why:** trabajo mayor en curso; las 8 decisiones condicionan todo el diseño y no se derivan del código.
**How to apply:** consistencia por REFERENCIA, no por texto; respetar las 8 decisiones. Relacionado:
[[vertex-ai-brainrot-walloop]] (edit_image 404, modelos, auth), [[orquestador-inteligente]].
