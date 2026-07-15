# Plan de elaboración total — Estudio audiovisual IA (extensión de TruebalanceComic)

> Copia versionada del plan aprobado. Original de trabajo:
> `C:\Users\rak\.claude\plans\rosy-pondering-meerkat.md`. Estado de avance en [pendientes/PENDIENTES.md](pendientes/PENDIENTES.md).

## Contexto

El repo actual es un generador **lineal y de un solo formato** (guion → storyboard → personajes →
imágenes → audio → vídeo → montaje) sobre Vertex AI. El usuario quiere convertirlo en un **estudio
de producción audiovisual multi-proyecto** cuya prioridad absoluta es la **coherencia** (personajes,
localizaciones, objetos, vestuario y voces estables entre escenas), con el humano al mando en cada paso.

Tras 8 decisiones de diseño cerradas con el usuario y **verificación real por API**, el alcance real
es más simple que el spec maximalista: mucho ya existe y se reutiliza; lo que falta son las biblias de
entorno/objetos, la edición conversacional (ya probada) y el control de modelo+coste por paso.

Resultado buscado: pasar de idea → guion → personajes → localizaciones → storyboard → imágenes →
animación → montaje, todo **conectado, editable y consistente**, eligiendo modelo y viendo coste en
cada paso.

## Principio rector
Consistencia por **imagen de referencia aprobada** (no por texto), prompts automáticos desde lo
aprobado, **todo manual y transparente**: el sistema genera y muestra; el humano decide. Sin motores
automáticos de estado ni de QC.

## Decisiones cerradas (fuente de verdad — no re-litigar)
1. **Character Lock** = imagen de referencia aprobada. Se puede **subir imagen** o **generar por prompt**; ambas confluyen en la misma referencia. Ideal: frontal + cuerpo entero.
2. **Multi-personaje en un plano**: se ancla en UNA imagen de conjunto (subida o aprobada) y se encadena; prompt etiquetado por posición como red de seguridad. No es paso obligatorio.
3. **Localizaciones**: misma mecánica que Character Lock (subir/generar → aprobar → manda).
4. **Precedencia**: la **imagen** manda siempre sobre el texto de la ficha.
5. **Planos independientes**: una vez aprobado un plano, cambiar una referencia base **no lo toca**. Sin cascadas ni grafo de dependencias.
6. **Continuidad narrativa a mano**: sin motor de estado; el usuario elige las referencias correctas.
7. **Coste**: **selector de modelo en cada fase y cada paso**; al elegir modelo se ve el **coste real de esa edición**; **contador total** del proyecto siempre visible. Sin diálogo de confirmación forzado.
8. **Sin QC automático**: el sistema solo genera y muestra; el usuario aprueba a ojo.
- **Prompts automáticos**: se mantienen como núcleo; editables solo si el usuario lo pide.
- **Edición** = vía **Nano Banana conversacional** (verificada), NO edit_image tipado (da 404 en el proyecto).

## Qué YA existe y se reutiliza (NO reescribir)
- **Multi-proyecto + estados + busy/jobs en background**: [app.py](app.py), [db.py](db.py) tabla `projects`, polling `/api/project/{pid}/state`.
- **Personajes con `ref_image`, `approved`, `library`**: [db.py](db.py). Falta el flujo de subir imagen y de crear-por-prompt explícito.
- **Prompt automático desde referencias aprobadas**: [services/images.py](services/images.py) `_ref_parts()` inyecta las imágenes de personaje como `Part.from_bytes`; `_scene_prompt()` arma el prompt con estilo + escena. **Este es el motor de consistencia; se extiende, no se recrea.**
- **Continuidad de vídeo** (keyframe N→N+1 como referencia): [services/images.py](services/images.py).
- **Assets versionados con `active`/`gen_n`**: [db.py](db.py) `add_asset()`, `get_assets()`.
- **Auditoría de coste + total por proyecto**: [db.py](db.py) `add_cost()` (suma a `projects.cost_total`), [services/costs.py](services/costs.py), y `models_for/default_model/real_model_id` en [config.py](config.py).
- **Modelo por tarea** (project.models JSON) y **registro con precios** ya listos en [config.py](config.py).
- **Animación (Veo), audio (TTS/Lyria), montaje (ffmpeg/PDF/ZIP)**: [services/video.py](services/video.py), [services/audio.py](services/audio.py), [services/assemble.py](services/assemble.py).
- **QC existe** ([services/qc.py](services/qc.py)) pero, por decisión 8, se **desactiva por defecto** (flag), no se borra.

## Cambios en el modelo de datos ([db.py](db.py), vía `_ensure_col`/`SCHEMA`)
Añadir tablas siguiendo el patrón de `characters` (id, project_id, name, description, `ref_image`, `approved`, `library`):
- **`locations`**: + `type`, `ref_images` (JSON: varias plates por ángulo).
- **`props`** (objetos + vestuario, con `category` = objeto|vehiculo|vestuario|accesorio|mascota): + `owner_character_id` (nullable).
- **`voices`** (stock reutilizable): `name`, `base_voice` (VOICES prebuilt), `instruction` (tono/ritmo), `sample_path`, `approved`. Personaje referencia `voice_id`.
- **Enlace escena↔entidades**: columnas JSON en `scenes` (`char_ids`, `location_id`, `prop_ids`) — más simple, sin joins.
- **`characters`**: + `ref_images` (JSON para model sheet multi-vista) y `voice_id`.
- Referencias de biblia como ficheros en `projects/<id>/characters|locations|props/`, referenciados por la fila de la entidad (sin tocar `assets`).
- Migraciones idempotentes con `_ensure_col` como ya se hace en `db.init()`.

## Backend — servicios y rutas ([app.py](app.py), [services/](services))
- **Subida de referencia** (personaje/localización/objeto): `POST /api/{entity}/{id}/upload_ref` (guarda PNG en la carpeta del proyecto, marca la entidad). Reutiliza `db.project_dir()`.
- **Crear entidad por prompt**: `POST /api/project/{pid}/{entity}` con `{prompt}` → la IA rellena la ficha (Gemini, JSON-schema como [services/storyboard.py](services/storyboard.py)) y opcionalmente genera la imagen de referencia (patrón de `images.gen_character_ref`, generalizado a `gen_entity_ref`).
- **Edición conversacional (verificada)**: `images.edit_active_image(pid, scene_id, instruction)` → toma el asset activo como `types.Part.from_bytes` + instrucción ("mantén cara/pelo, cambia solo X") con `gemini-3.1-flash-lite-image` vía `generate_content`. Nuevo `POST /api/scene/{sid}/edit_image {instruction, model?}`. Es el §10 del spec por la única vía que funciona en el proyecto.
- **Override de modelo por paso**: los endpoints de generación aceptan `model?` opcional que sobreescribe el default del proyecto para esa llamada. El coste ya lo registra `costs.register`.
- **Inyección de referencias por escena**: extender `images._ref_parts()` para incluir, además de personajes, la **localización** y los **objetos** enlazados a esa escena (según `scenes.char_ids/location_id/prop_ids`). El etiquetado por posición se añade en `_scene_prompt`.
- **Estimación de coste por paso**: generalizar `GET /api/project/{pid}/estimate_video` a `GET /api/estimate?task=&model=&units=`.

## Frontend — UI de estudio ([templates/project.html](templates/project.html), [static/app.js](static/app.js))
- **Menú lateral tipo estudio**: Idea/Sinopsis · Guion · Personajes · Localizaciones · Objetos y vestuario · Voces · Storyboard · Imágenes · Animación · Montaje · Config. Cada sección lista sus entidades con estado.
- **Selector de modelo + coste por paso**: dropdown desde `config.models_for(task)` con el `label` (incluye precio) y coste estimado; **contador `cost_total` siempre visible** (ya viene en `/state`).
- **Fichas de entidad**: subir imagen o "generar por prompt"; aprobar; galería de versiones.
- **Panel de escena**: enlazar personajes/localización/objetos; generar keyframe; **editar por instrucción**; comparar versiones; aprobar; animar.
- Servir estático versionado (`?v=N`); subir N al tocar JS/CSS.

## Fases de implementación (hitos ordenados)
1. **Datos + biblias**: tablas `locations`, `props`, `voices`, enlaces en `scenes`, migraciones. Endpoints CRUD + subida de referencia + crear-por-prompt. UI de las secciones de biblia.
2. **Motor de consistencia extendido**: `_ref_parts` incluye localización/objetos por escena; etiquetado por posición.
3. **Edición conversacional**: `images.edit_active_image` + endpoint + UI de "editar por instrucción".
4. **Modelo+coste por paso**: `model?` en endpoints de generación; dropdowns + contador + estimación en UI.
5. **Voces**: stock reutilizable, probar la misma frase con varias voces, aprobar y asignar a personaje.
6. **Exportaciones**: biblias, guion PDF, storyboard, JSON del proyecto (extiende [services/assemble.py](services/assemble.py)).
7. **Pulido**: QC opcional off por defecto; estados/etiquetas de la UI; limpieza.

## Fuera de alcance (aparcado en [pendientes/PENDIENTES.md](pendientes/PENDIENTES.md))
Lip-sync a audio, máscara de píxel/edit_image tipado (404 en el proyecto), multi-proveedor completo,
cola de jobs durable, colaboración/roles, montaje avanzado, paisaje sonoro generativo, clonación de voz.
Todos con motivo y workaround anotados. No planificar sobre ellos hasta desbloquearlos.

## Verificación end-to-end
1. `.\run.ps1` → http://127.0.0.1:8010 ; smoke `python -c "import app"`.
2. Crear proyecto; crear un personaje **por prompt** y otro **subiendo imagen**; aprobar sus referencias.
3. Crear una **localización** y un **objeto**; enlazarlos a una escena.
4. Generar el keyframe de la escena y comprobar que **inyecta** personaje+localización+objeto (identidad mantenida).
5. **Editar por instrucción** ("cambia solo la chaqueta a roja") y verificar que conserva rostro/pelo.
6. Cambiar el **modelo** en un paso concreto y ver que el **coste real** y el **contador total** se actualizan.
7. Animar una escena aprobada (Veo) y montar; abrir el entregable en `projects/<id>/final/`.
8. Confirmar (decisión 5) que re-aprobar una referencia **no altera** planos ya aprobados.
