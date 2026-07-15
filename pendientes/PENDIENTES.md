# PENDIENTES

Funcionalidad del proyecto (estudio audiovisual con IA) que **NO** implementamos en la primera
fase, con el motivo y un plan provisional. Todo lo que está aquí es porque hoy no se puede hacer
limpio con Vertex AI, requiere una integración/decisión aparte, o es una fase posterior del propio
diseño. Lo que SÍ se puede hacer no vive en este fichero: se implementa.

> Fuente: inventario real de Vertex consultado en vivo el 2026-07-15 (`models.list`, proyecto
> `brainrot-walloop`) + auditoría de capacidades. Revisar este fichero cada vez que se amplíe el
> catálogo de modelos de Vertex, porque varias de estas entradas pueden desbloquearse solas.

Leyenda de estado:
- 🔴 **Límite del modelo / estado del arte** — no depende de nuestro código.
- 🟠 **Sin endpoint nativo en Vertex** — se puede aproximar con un workaround, no hay botón directo.
- 🟡 **API de Google separada** — existe, pero fuera de `aiplatform` y con integración/legal extra.
- 🔵 **Decisión de arquitectura aplazada** — se puede, pero lo dejamos para no sobre-construir.
- ⚪ **Fase posterior del spec** — funcionalidad que el propio plan situaba en fase 2/3.

---

## 🔴 Límites del modelo (no dependen de nosotros)

### 1. Lip-sync a una pista de audio concreta
- **Qué es:** sincronizar el movimiento de labios del personaje con un diálogo/voz TTS específico.
- **Por qué pende:** Vertex NO tiene modelo de lip-sync (confirmado por ausencia en `models.list`).
  Veo hace image-to-video pero no clava labios a un audio dado.
- **Workaround provisional:** planos cortos donde el diálogo no exige boca en primer pláno; probar
  `gemini-omni-flash-preview` (edición conversacional de vídeo) como aproximación; dejar el hueco
  marcado para un proveedor externo si algún día se abre la arquitectura multi-proveedor (ver §7 aquí).
- **Desbloquea si:** aparece un modelo de lip-sync en Vertex, o Omni Flash demuestra sincronía usable.

### 2. Geometría estable de localizaciones
- **Qué es:** que "ventana a la derecha, puerta al fondo, mesa junto a la pared" se conserve exacto
  entre escenas.
- **Por qué pende:** ningún modelo de imagen respeta layout espacial desde texto de forma fiable.
- **Workaround provisional:** *plate* de referencia por localización (imagen aprobada) + encadenar
  keyframes; aceptar que la geometría fina puede bailar. Diseñar la UI para "degradar con elegancia"
  (avisar, no prometer precisión milimétrica).
- **Desbloquea si:** modelos con control de layout / referencia espacial fuerte.

### 3. Multi-personaje bloqueado en el mismo plano (caso difícil, 3+)
- **Qué es:** varios personajes con Character Lock en el mismo frame sin que se contaminen las caras.
- **Por qué pende:** los modelos mezclan identidades con 3+ sujetos.
- **Workaround provisional (ya acordado):** subir/aprobar UNA imagen de conjunto como ancla y
  encadenar desde ella; prompt etiquetado por posición; QC por rostro; composición por capas solo
  como plan B. Con 1-2 personajes no es problema.
- **Desbloquea si:** mejora la fidelidad multi-referencia de los modelos de imagen.

---

## 🟠 Máscara/edición tipada: NO disponible hoy en el proyecto (verificado)

> Actualizado 2026-07-15. El esquema del SDK `google.genai` v2.10.0 SÍ define `edit_image` con
> subject/mask/control references, PERO una prueba REAL (2026-07-15) demostró que el proyecto
> `brainrot-walloop` no puede llamarlo: **404 NOT_FOUND** en los 4 modelos candidatos
> (`imagen-3.0-capability-001`, `imagen-3.0-capability-preview-0606`, `gemini-3.1-flash-image`,
> `gemini-3-pro-image`) en location global. No hay ningún modelo Imagen-capability habilitado.

### 4. Inpainting por máscara / referencias tipadas (subject, face-mesh, BGSWAP)
- **Qué es:** máscara de píxel precisa, `SubjectReferenceImage(PERSON)`, `CONTROL_TYPE_FACE_MESH`,
  `EDIT_MODE_BGSWAP`, etc. Es el §10 del spec en su versión "de estudio".
- **Estado real (verificado):** `edit_image` da 404 en el proyecto → esta vía NO se puede usar hoy.
- **Vía que SÍ funciona (verificada con imagen real):** edición **conversacional** de Nano Banana
  (`generate_content` con la imagen de entrada como `Part.from_bytes` + instrucción tipo
  "mantén la misma cara y pelo, cambia solo la chaqueta a cuero rojo"). Preservó identidad completa
  y aplicó el cambio pedido. Cubre por instrucción la mayoría de §10 (cambiar vestuario, expresión,
  objeto, fondo), aunque SIN máscara de píxel exacta.
- **Desbloquea si:** un admin habilita un modelo Imagen-capability en el proyecto (Model Garden).
  Mientras tanto, todo el pipeline de edición va por la vía Nano Banana conversacional.

---

## 🟡 API de Google separada (fuera de aiplatform)

### 5. Clonación de voz autorizada
- **Qué es:** clonar la voz de una persona (con su consentimiento) para un personaje.
- **Por qué pende:** no está en `models.list` de Vertex; vive en `texttospeech.googleapis.com`
  (Instant Custom Voice) y exige **registro de consentimiento**, no solo un checkbox.
- **Workaround provisional:** para el MVP usar las voces TTS nativas de Vertex
  (`gemini-2.5-flash-tts`, `gemini-2.5-pro-tts`, `gemini-3.1-flash-tts-preview`) con control de
  estilo/emoción; la clonación se integra después con su flujo legal de consentimiento.
- **Desbloquea si:** integramos la API de Text-to-Speech + un módulo de consentimiento verificable.

---

## 🔵 Decisiones de arquitectura aplazadas

### 6. Motor de continuidad como estado por escena + grafo de dependencias
- **Qué es:** estado narrativo que hereda de la escena anterior (heridas, edad, objetos que se llevan,
  ropa) + propagación de "desactualizado" cuando se re-aprueba un elemento base.
- **Por qué pende (parcial):** el modelo de datos completo (estado/diff + grafo biblia→plano→imagen→clip)
  es el diferenciador real y hay que diseñarlo con cuidado. En el MVP se implementa la versión mínima
  (referencias aprobadas + bloqueos); la cascada completa de obsolescencia se añade por capas.
- **Nota:** `multimodalembedding` (ya disponible en Vertex) permite QC de deriva por similitud de
  vector — usarlo como primera red del motor de consistencia.

### 7. Abstracción multi-proveedor (§15 del spec)
- **Qué es:** poder conectar otros proveedores de IA además de Google y elegir por coste/calidad.
- **Por qué pende:** el proyecto es solo-Google hoy. Construir la abstracción completa ahora es coste
  sin retorno.
- **Plan:** dejar la **interfaz de adaptador** en el código desde el día 1 (el `MODEL_REGISTRY` de
  `config.py` ya es data-driven) pero implementar únicamente Vertex. Sería el punto de entrada natural
  para un lip-sync externo (ver §1).

### 8. Cola de jobs durable
- **Qué es:** ejecución de generaciones largas a escala de una serie entera (episodios × escenas ×
  planos × versiones).
- **Por qué pende:** hoy los jobs corren en threads + SQLite; vale para un proyecto pequeño. Una serie
  completa puede necesitar cola durable con reintentos.
- **Plan:** mantener el modelo actual para el MVP; migrar a cola cuando el volumen lo exija.

---

## ⚪ Fases posteriores del spec

### 9. Montaje avanzado (§18)
- Línea de tiempo con recorte fino, transiciones, capas. El MVP hace animatic / primer montaje con
  ffmpeg (ya existe base en `services/assemble.py`); el editor pro llega después.

### 10. Paisaje sonoro / efectos ambientales generativos (§8)
- Generación de foley/ambiente por texto. **Verificar** si Lyria o algún modelo cubre SFX; música sí
  (`lyria-3-*`). Sonido ambiental sincronizado a escena queda para fase 2.

### 11. Colaboración y roles (§19)
- Propietario/director/guionista/editor/cliente con permisos y comentarios por escena. Fase posterior.

### 12. Storyboard como *animatic* reproducible (§9)
- Vistas cuadrícula/lista sí en MVP; el animatic navegable con timing es fase posterior.

---

## Oportunidades descubiertas (esto SÍ se puede, no es pendiente)

Se anotan aquí solo para no olvidarlas al planificar; van a implementación, no a este parking.

Del inventario (`models.list`):
- `virtual-try-on-001` → probar **vestuario** sobre un personaje conservando identidad. Encaja directo
  con la biblia de vestuario.
- `multimodalembedding` → QC de identidad automático por similitud de embedding (más barato y objetivo
  que pedir a un LLM que "mire").
- TTS + Chirp (STT) + traducción, todo dentro de Google → guion multilingüe, subtítulos y doblaje base
  sin salir de Vertex.

Verificado que SÍ funciona hoy (prueba real 2026-07-15):
- **Edición conversacional Nano Banana** (`gemini-3.1-flash-lite-image` vía `generate_content` con
  imagen de entrada + instrucción) → preserva identidad y aplica cambios dirigidos (vestuario, fondo,
  objeto, expresión) SIN máscara. Es la base real del Character Lock y de la edición del §10.
- Veo (`GenerateVideosConfig`): `reference_images`, `last_frame`, `mask`, `resolution` 720p/1080p,
  `generate_audio`, `negative_prompt` — parámetros presentes en el SDK (pendiente prueba real de
  vídeo, pero el inventario confirma los modelos `veo-3.1-*` activos).

OJO — NO disponibles hoy en el proyecto (dan 404, requieren habilitar Imagen-capability):
`edit_image`, `SubjectReferenceImage`, `ControlReferenceImage`/`FACE_MESH`, `StyleReferenceImage`,
`MaskReferenceImage`, `EditMode.BGSWAP`, y por tanto `recontext_image`/`segment_image`/`upscale_image`
por esa vía. Existen en el SDK pero el proyecto no los sirve. No planificar sobre ellos hasta habilitarlos.

---

## Por confirmar (lo que queda)
- **[RESUELTO 2026-07-15]** ¿Qué modelo sirve `edit_image`? → Ninguno en el proyecto (404). Se usa la
  vía Nano Banana conversacional. Para máscara de píxel: habilitar un Imagen-capability (acción admin).
- **[Pendiente]** Prueba real de vídeo Veo con `reference_images` + `last_frame` (confirmar que
  respetan identidad en movimiento, no solo que el parámetro existe).
- **[Pendiente]** Flujo exacto de consentimiento de Instant Custom Voice (clonación de voz), API aparte.
- **[Pendiente]** Confirmar SFX/foley (música sí con `lyria-3-*`; efectos ambientales por texto, sin confirmar).
