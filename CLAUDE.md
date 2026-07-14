# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Web local (FastAPI + Jinja + JS vanilla, sin build) que convierte un guion en **slides promocionales, cómic o vídeo** usando solo modelos Google de Vertex AI. Pipeline: guion → storyboard estructurado (Gemini) → biblia visual (fichas de personaje reutilizadas como referencia en cada imagen) → imágenes/keyframes con QC de visión y reintento → aprobación humana → (vídeo) TTS + Lyria + clips Veo con first/last frame → montaje ffmpeg con subtítulos → entregables en `projects/<id>/final/`.

## Comandos

- **Arrancar**: `.\run.ps1` (lanza uvicorn en http://127.0.0.1:8010). El token se **auto-renueva**: `services/vertex.py` llama a gcloud cada ~50 min y ante cualquier 401 (verificado con llamada real sin token inicial). No hay tests ni linter configurados.
- Smoke test rápido: `python -c "import app"`.
- La DB es `truebalance.db` (SQLite, WAL); los assets viven en `projects/<id>/` (fuera de git idealmente).

## Arquitectura (lo no obvio)

- `config.py` es la única fuente de verdad de modelos/precios/locations (`MODEL_REGISTRY`); las entradas pueden ser alias con `model_id` real (ej. el QC). Coste por llamada → `services/costs.py` → tabla `costs` + `projects.cost_total`.
- Los jobs largos corren en threads (`_job` en `app.py`) con `busy`/`status_msg` en DB; la UI hace polling de `/api/project/{id}/state` cada 3s. Los jobs de imágenes son **reanudables**: saltan escenas con asset activo (clave tras un 429).
- `services/vertex.py`: cliente por location + header `X-Goog-User-Project` + `call_with_retry` (429 espera 20s×intento) + `scrub()` para no filtrar el token en errores.
- Continuidad vídeo: **un keyframe por escena** (keyframe_first); el fotograma de la escena N se pasa como referencia al generar la N+1 (`services/images.py`). Veo anima con image-to-video desde ese único frame; `video.py` usa last_frame solo si existe (proyectos antiguos).
- En modo cómic, los diálogos "NOMBRE: frase" se convierten con `images.balloon_spec()` en globos por personaje SIN el nombre dentro del globo; el QC compara contra ese texto plano.
- `assets.active`: cada regeneración desactiva las anteriores del mismo (escena, kind, formato); la UI y el montaje usan siempre la última activa.
- Montaje (`services/assemble.py`): la unidad es el **clip audiovisual por escena** (`_scene_av`): vídeo normalizado + su audio (voz TTS > nativo Veo > silencio) en UNA pista AAC, exactamente de la duración del clip. `mux_scene_preview` guarda ese clip como asset `preview` (lo que la galería reproduce con sonido). `assemble_video` concatena esos mismos clips uniformes (`-c copy`, imposible desincronizar) y superpone música + subtítulos. Nunca mezclar clips con distinto nº de pistas en el concat demuxer; evitar `-shortest` al normalizar.
- Reedición: `POST /api/scene/{sid}/reedit_video {prompt}` regenera el clip Veo con `extra_prompt`; `/reedit_voice {prompt}` regenera la voz con `instruction` (tono/ritmo). Ambos remuxean el preview. Clips generados sin audio nativo cuando la escena tiene TTS (`video._animate_veo` → `generate_audio=False`), para no duplicar voz.
- Assets por escena: `keyframe_first` (imagen), `clip` (vídeo mudo de Veo), `voice` (TTS), `preview` (clip AV mostrado en UI). El estático se sirve versionado (`?v=N` en project.html) + middleware `no-cache`; subir N al cambiar JS/CSS.

## Vertex AI (verificado 2026-07-14, llamada real 200 OK)

- **Proyecto GCP:** `brainrot-walloop`. Solo `out.brainrot@gmail.com` tiene acceso (apalanko@ y raktunak@ emiten token pero dan "caller does not have permission").
- **Auth:** `$env:VXTOKEN = (gcloud auth print-access-token --account=out.brainrot@gmail.com)`. NUNCA imprimir el token. El shell no persiste estado: obtener token y ejecutar el script en el MISMO comando PowerShell.
- La service account `appvoz-voice@brainrot-walloop.iam.gserviceaccount.com` fue **eliminada**: no usarla ni recrearla.
- **Location:** `"global"` (NO us-central1: los Nano Banana 3.x ahí dan 404 que parece fallo de conexión y no lo es).
- **SDK:** `google.genai` (NO `google.generativeai`):
  ```python
  from google import genai
  from google.oauth2.credentials import Credentials
  creds = Credentials(token=os.environ["VXTOKEN"].strip())
  client = genai.Client(vertexai=True, project="brainrot-walloop", location="global", credentials=creds)
  ```
- En Vertex **no existe Files API**: archivos como inline bytes con `types.Part.from_bytes(data=..., mime_type=...)`.
- **Modelos imagen:** default `gemini-3.1-flash-lite-image` ($0.034/img, iterar con este); reserva `gemini-3-pro-image` ($0.134, prohibirle en el prompt asteriscos visibles y frases repetidas); NO usar `gemini-2.5-flash-image` (erratas).
- **Config imagen:** `response_modalities=["IMAGE"]`, `image_config=types.ImageConfig(aspect_ratio="9:16")`; los bytes vuelven en `r.candidates[0].content.parts[i].inline_data.data`.
- **Errores:** 401/403 = auth, 404 = modelo/location.
- **VÍDEO (Veo): location `us-central1`, NO global** (en global dan 404). Imagen/texto = global, vídeo = us-central1.
- **Modelos vídeo** (IDs verificados por API 2026-07-14): `veo-3.1-generate-001` (~$0.40/s, máx calidad), `veo-3.1-fast-generate-001` (~$0.10-0.15/s, default), `veo-3.1-lite-generate-001` (~$0.03-0.05/s, preview, iterar). Clips máx 8s; todos soportan image-to-video; Veo 3.1 añade reference images y first+last frame. Evitar veo-3.0/2.0 (obsoletos).
- **`gemini-omni-flash-preview`** (global y us-central1): vídeo multimodal, $0.10/s (720p+audio), edición conversacional de vídeo. Preview jul 2026, aún sin probar en el proyecto.
- **Lyria 3** (`lyria-3-clip-preview`, `lyria-3-pro-preview`): música/BSO, disponibles en el proyecto.
- No hay modelos de vídeo de terceros en Vertex (solo Veo + Omni Flash). Veo 3.1 Lite: $0.05/s confirmado.
- **models.list/get requieren** `http_options=types.HttpOptions(headers={"X-Goog-User-Project": "brainrot-walloop"})` — sin él, 403 engañoso.
