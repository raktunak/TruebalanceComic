---
name: veo-filtro-ip-terceros
description: "Veo y Nano Banana bloquean IP de terceros (logos, cajas con arte, \"multiverso\") — sanear biblia visual y no enviar diálogos a Veo si hay TTS"
metadata: 
  node_type: memory
  type: project
  originSessionId: da5e35d4-442f-4e28-b186-1215c718f31b
---

Lección de TruebalanceComic (2026-07-14): los filtros de Vertex bloquean contenido con IP de terceros en TRES puntos distintos, con errores diferentes:

1. **Imagen (Nano Banana)**: respuesta sin partes, `FinishReason.IMAGE_PROHIBITED_CONTENT` → el código debe tratar candidates/parts None (no iterar a ciegas).
2. **Veo al enviar** (`code: 3, "interests of third-party content providers"`): rechazo INMEDIATO (~30s, no cobra). Escanea el prompt Y las imágenes de entrada (keyframes/refs). Detonantes reales vistos: camiseta con logo de araña (Spider-Man), cajas de figuras con ilustraciones, palabra "multiverso" en el diálogo.
3. **La raíz suele estar en la biblia visual**: si la descripción del personaje incluye IP ("camiseta con logo de araña"), TODAS las imágenes heredan el problema y los reintentos fallan aunque el prompt de escena esté limpio.

**Why:** Perder tiempo/dinero reintentando escenas bloqueadas cuando el problema está aguas arriba (ficha del personaje o diálogo pasado a Veo).

**How to apply:** El prompt del storyboard prohíbe IP en visual Y en descripciones de personajes. Si hay locuciones TTS, NO enviar el diálogo a Veo (generate_audio=False, sin lip-sync text). Ante bloqueo repetido de una escena: revisar descripción del personaje y regenerar su ficha, no solo la escena. Relacionado: [[vertex-ai-brainrot-walloop]].
