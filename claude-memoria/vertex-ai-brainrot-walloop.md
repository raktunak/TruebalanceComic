---
name: vertex-ai-brainrot-walloop
description: "Conexión Vertex AI (proyecto GCP brainrot-walloop) — auth, location global, SDK google.genai, modelos de imagen y costes. Verificada 2026-07-14 (200 OK)"
metadata: 
  node_type: memory
  type: project
  originSessionId: da5e35d4-442f-4e28-b186-1215c718f31b
---

Configuración Vertex AI usada en los proyectos del usuario (verificada 2026-07-10 por el usuario y 2026-07-14 por Claude con llamada real 200 OK).

- **Proyecto GCP:** `brainrot-walloop`. Solo la cuenta `out.brainrot@gmail.com` tiene acceso (apalanko@ y raktunak@ emiten token pero dan "caller does not have permission").
- **Auth (PowerShell):** `$env:VXTOKEN = (gcloud auth print-access-token --account=out.brainrot@gmail.com)`. NUNCA imprimir el token. Shell state no persiste entre llamadas: obtener token y ejecutar script en el MISMO comando. Los access tokens de Google caducan a la ~1h: para procesos largos (servidores), renovar vía subprocess gcloud cada ~50 min y ante 401 (patrón implementado y verificado en TruebalanceComic `services/vertex.py` 2026-07-14).
- **Service account `appvoz-voice@brainrot-walloop.iam.gserviceaccount.com`: ELIMINADA.** No usarla ni recrearla.
- **Location:** `"global"` (NO us-central1: los Nano Banana 3.x ahí dan 404 que parece fallo de conexión y no lo es).
- **SDK:** el nuevo `google.genai` (NO `google.generativeai`), instalado v2.10.0:
  ```python
  from google import genai
  from google.oauth2.credentials import Credentials
  creds = Credentials(token=os.environ["VXTOKEN"].strip())
  client = genai.Client(vertexai=True, project="brainrot-walloop", location="global", credentials=creds)
  ```
- **Sin Files API en Vertex:** archivos como inline bytes con `types.Part.from_bytes(data=..., mime_type=...)`.
- **Modelos imagen:**
  - Default/iteración: `gemini-3.1-flash-lite-image` ($0.034/img).
  - Reserva/calidad: `gemini-3-pro-image` ($0.134/img; prohibirle en el prompt asteriscos visibles y frases repetidas).
  - NO usar `gemini-2.5-flash-image` (erratas).
- **Config imagen:** `response_modalities=["IMAGE"]`, `image_config=types.ImageConfig(aspect_ratio="9:16")`. Los bytes vuelven en `r.candidates[0].content.parts[i].inline_data.data`.
- **Errores:** 401/403 = auth (cuenta equivocada), 404 = modelo/location equivocados.
- **VÍDEO (Veo): location `us-central1`, NO global** (probado 2026-07-14: en global los Veo dan 404; en us-central1 existen). Imagen/texto = global, vídeo = us-central1.
- **Modelos vídeo disponibles en el proyecto** (IDs con puntos, verificados por API): `veo-3.1-generate-001` (~$0.40/s, máx calidad, 720p/1080p/4K), `veo-3.1-fast-generate-001` (~$0.10-0.15/s, default recomendado), `veo-3.1-lite-generate-001` (~$0.03-0.05/s, preview, para iterar barato), `veo-3.0-generate-001`/`veo-3.0-fast-generate-001` (obsoletos, retiro jun 2026), `veo-2.0-generate-001` (retirado, sin audio). Todos: clips máx 8s, text-to-video e image-to-video; Veo 3.1 añade reference images y first+last frame (clave para continuidad entre keyframes). Precios de Fast/Lite son rangos de blogs oficiales Google (abr 2026), no confirmados en página de pricing.
- **`gemini-omni-flash-preview`** (disponible en global Y us-central1, verificado por API 2026-07-14): vídeo multimodal de Google, public preview jul 2026. $0.10/s de vídeo output (720p con audio nativo). Genera vídeo desde texto/imágenes/frames y permite **edición conversacional** (cambiar personajes, iluminación, perspectiva en lenguaje natural). Input $1.50/1M tokens; 5.792 tokens/s de vídeo. Fuente: blog oficial Google Cloud. Aún no probado con llamada real en el proyecto.
- **Lyria 3** música: `lyria-3-clip-preview` y `lyria-3-pro-preview` (también `lyria-002`) disponibles en el proyecto — para bandas sonoras.
- **No hay modelos de vídeo de terceros en Vertex Model Garden** (jul 2026): ni Runway, Kling, Luma, Sora, Wan, etc. Solo familia Veo + Gemini Omni Flash. Precio Veo 3.1 Lite confirmado por blog: $0.05/s.
- **Metadata calls (models.list/get) necesitan header quota project:** `http_options=types.HttpOptions(headers={"X-Goog-User-Project": "brainrot-walloop"})` — sin él dan 403 engañoso aunque generate_content funcione.
- **EDICIÓN de imagen — probado real 2026-07-15:** `client.models.edit_image()` (Imagen-capability: `SubjectReferenceImage`, `MaskReferenceImage`, `ControlReferenceImage`/FACE_MESH, `EditMode.BGSWAP`, etc.) da **404 en el proyecto** — no hay modelo Imagen-capability habilitado (probados `imagen-3.0-capability-001`, `-preview-0606`, `gemini-3.1-flash-image`, `gemini-3-pro-image`, todos 404). El esquema existe en el SDK pero el proyecto no lo sirve. **La vía de edición que SÍ funciona es Nano Banana conversacional:** `generate_content` con la imagen de entrada como `Part.from_bytes` + instrucción ("mantén la misma cara y pelo, cambia solo X"); preserva identidad completa y aplica el cambio dirigido sin máscara. Para máscara de píxel real haría falta que un admin habilite un Imagen-capability. No re-testear esto sin motivo.
- **Modelos nuevos vistos en `models.list` 2026-07-15 (además de los de arriba):** texto `gemini-3.5-flash`, `gemini-3.1-pro-preview`, `gemini-3-flash-preview`; imagen `gemini-3.1-flash-image`, `gemini-3-pro-image-preview`; TTS nativo `gemini-2.5-flash-tts`/`gemini-2.5-pro-tts`/`gemini-3.1-flash-tts-preview`; STT `chirp-2`/`chirp-3`/`video-speech-transcription`; traducción `text-translation`/`translate-llm`/`translategemma`; y utilidades relevantes para consistencia: `virtual-try-on-001` (probar vestuario), `multimodalembedding` (QC de deriva por similitud), `image-segmentation-001`, `recontext_image`/`segment_image`/`upscale_image` (métodos SDK, sujetos al mismo 404 de capability).

**Why:** Config compartida entre proyectos del usuario; los errores 404/403 aquí son confusos y ya están diagnosticados.

**How to apply:** Copiar el patrón de cliente tal cual; token siempre vía env var en el mismo comando que el script. Relacionado: [[orquestador-inteligente]].
