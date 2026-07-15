"""TruebalanceComic — web local: guion → slides promo / cómic / vídeo (Vertex AI).

Arranque: .\\run.ps1   (obtiene el token y lanza uvicorn en el mismo comando)
"""
import io
import json
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

import config
import db
from services import assemble, audio, bible, exporter, images, qc, storyboard, video, vertex, costs

app = FastAPI(title="TruebalanceComic")
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache"  # el navegador revalida el JS/CSS siempre
    return resp
templates = Jinja2Templates(directory=BASE / "templates")

db.init()


# ---------- jobs en background ----------

def _job(pid, name, fn):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404)
    if p["busy"]:
        raise HTTPException(409, "ya hay una tarea en marcha en este proyecto")

    def runner():
        db.set_status(pid, busy=True, msg=f"{name}…")
        try:
            fn()
            db.set_status(pid, busy=False)
        except vertex.TokenError as e:
            db.set_status(pid, status="error", msg=str(e), busy=False)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            db.set_status(pid, status="error", msg=f"{name}: {vertex.scrub(e)[:300]}", busy=False)

    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True}


# ---------- páginas ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "projects": db.list_projects(),
        "registry": config.MODEL_REGISTRY,
        "modes": config.MODES,
        "formats": config.FORMATS,
        "voices": config.VOICES,
        "tasks": {t: config.models_for(t) for t in ("storyboard", "image", "video", "tts", "music")},
        "defaults": {t: config.default_model(t) for t in ("storyboard", "image", "video", "tts", "music")},
    })


@app.get("/project/{pid}", response_class=HTMLResponse)
def project_page(request: Request, pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404)
    _tasks = ("storyboard", "image", "video", "tts", "music")
    return templates.TemplateResponse(request, "project.html", {
        "p": p,
        "registry": config.MODEL_REGISTRY,
        "voices": config.VOICES,
        "tasks": {t: config.models_for(t) for t in _tasks},
        "defaults": {t: config.default_model(t) for t in _tasks},
    })


@app.get("/files/{pid}/{rel:path}")
def files(pid: int, rel: str):
    f = (db.project_dir(pid) / rel).resolve()
    if not str(f).startswith(str(db.project_dir(pid).resolve())) or not f.exists():
        raise HTTPException(404)
    # no-cache: el navegador revalida (ETag/mtime), así un asset regenerado se ve al instante
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


# ---------- API ----------

@app.post("/api/projects")
async def create_project(req: Request):
    d = await req.json()
    if not d.get("script", "").strip():
        raise HTTPException(400, "el guion no puede estar vacío")
    models = {t: d.get("models", {}).get(t) or config.default_model(t)
              for t in ("storyboard", "image", "video", "tts", "music")}
    pid = db.create_project(
        title=d.get("title") or "Proyecto sin título",
        mode=d.get("mode", "video"),
        formats=d.get("formats") or ["9:16"],
        script=d["script"].strip(),
        models=models,
        audio_first=bool(d.get("audio_first")),
        voice=d.get("voice", "Kore"),
    )
    return {"id": pid}


@app.get("/api/project/{pid}/state")
def state(pid: int):
    p = db.get_project(pid)
    if not p:
        raise HTTPException(404)
    scenes = db.get_scenes(pid)
    for s in scenes:
        s["assets"] = db.get_assets(pid, scene_id=s["id"])
    return {
        "project": p,
        "characters": db.get_characters(pid),
        "locations": db.get_entities(pid, "location"),
        "props": db.get_entities(pid, "prop"),
        "voices": db.get_entities(pid, "voice"),
        "scenes": scenes,
        "project_assets": db.get_assets(pid, scene_id=None),
        "costs": db.get_costs(pid)[:30],
    }


@app.post("/api/project/{pid}/storyboard")
def gen_storyboard(pid: int):
    def work():
        storyboard.generate(pid)
        for ch in db.get_characters(pid):
            images.gen_character_ref(pid, ch["id"])
        db.set_status(pid, status="storyboard", msg="Storyboard y fichas de personajes listos. Revisa y aprueba.")
    return _job(pid, "Storyboard + personajes", work)


@app.post("/api/character/{cid}/regen")
async def regen_character(cid: int, req: Request):
    d = await req.json()
    chs = None
    for pid_row in db.list_projects():
        for c in db.get_characters(pid_row["id"]):
            if c["id"] == cid:
                chs, pid = c, pid_row["id"]
                break
        if chs:
            break
    if not chs:
        raise HTTPException(404)
    if d.get("description"):
        db.update_character(cid, description=d["description"])
    return _job(pid, f"Regenerar {chs['name']}", lambda: images.gen_character_ref(pid, cid))


@app.post("/api/character/{cid}/voice")
async def set_character_voice(cid: int, req: Request):
    d = await req.json()
    if d.get("voice") not in config.VOICES:
        raise HTTPException(400, "voz desconocida")
    db.update_character(cid, voice=d["voice"])
    return {"ok": True}


# ---------- biblias: personajes, localizaciones, objetos, voces ----------
# Prefijos /api/project/{pid}/bible/{entity} y /api/bible/{entity}/{eid} para no colisionar
# con las rutas existentes (/api/scene/..., /api/project/{pid}/storyboard, etc.).

_IMAGE_ENTITIES = {"character", "location", "prop"}
_BIBLE_ENTITIES = {"character", "location", "prop", "voice"}
_ENTITY_FIELDS = ("name", "description", "type", "category", "gender",
                  "base_voice", "instruction", "owner_character_id", "voice_id",
                  "approved", "library")


async def _maybe_json(req: Request) -> dict:
    try:
        return await req.json()
    except Exception:
        return {}


def _entity_or_404(entity, eid):
    if entity not in _BIBLE_ENTITIES:
        raise HTTPException(404, "entidad desconocida")
    ent = db.get_entity(entity, eid)
    if not ent:
        raise HTTPException(404)
    return ent


@app.post("/api/project/{pid}/bible/{entity}")
async def create_entity(pid: int, entity: str, req: Request):
    """Crea una entidad de biblia. Con {prompt} la IA rellena la ficha (y opcionalmente genera su
    imagen de referencia); sin prompt, se crea con los campos manuales indicados."""
    if entity not in _BIBLE_ENTITIES:
        raise HTTPException(404, "entidad desconocida")
    if not db.get_project(pid):
        raise HTTPException(404)
    d = await _maybe_json(req)
    prompt = (d.get("prompt") or "").strip()
    model = d.get("model") or ""

    if prompt and entity in _IMAGE_ENTITIES:
        gen_image = bool(d.get("gen_image", True))

        def work():
            eid = bible.fill_entity(pid, entity, prompt)
            if gen_image:
                db.set_status(pid, msg=f"Generando referencia de {entity}…")
                images.gen_entity_ref(pid, entity, eid, model_key=model)
            db.set_status(pid, msg=f"{entity.capitalize()} creado")
        return _job(pid, f"Crear {entity}", work)

    fields = {k: d[k] for k in _ENTITY_FIELDS if k in d}
    eid = db.add_entity(pid, entity, **fields)
    return {"id": eid}


@app.post("/api/bible/{entity}/{eid}/update")
async def update_entity_ep(entity: str, eid: int, req: Request):
    _entity_or_404(entity, eid)
    d = await _maybe_json(req)
    allowed = {k: d[k] for k in _ENTITY_FIELDS if k in d}
    if allowed:
        db.update_entity(entity, eid, **allowed)
    return {"ok": True}


@app.post("/api/bible/{entity}/{eid}/approve")
def approve_entity_ep(entity: str, eid: int):
    _entity_or_404(entity, eid)
    db.update_entity(entity, eid, approved=1)
    return {"ok": True}


@app.delete("/api/bible/{entity}/{eid}")
def delete_entity_ep(entity: str, eid: int):
    _entity_or_404(entity, eid)
    db.delete_entity(entity, eid)
    return {"ok": True}


@app.post("/api/bible/{entity}/{eid}/gen_ref")
async def gen_entity_ref_ep(entity: str, eid: int, req: Request):
    if entity not in _IMAGE_ENTITIES:
        raise HTTPException(400, "esta entidad no tiene imagen de referencia")
    ent = _entity_or_404(entity, eid)
    pid = ent["project_id"]
    model = (await _maybe_json(req)).get("model") or ""
    return _job(pid, f"Referencia {entity}", lambda: images.gen_entity_ref(pid, entity, eid, model_key=model))


@app.post("/api/bible/{entity}/{eid}/upload_ref")
async def upload_ref_ep(entity: str, eid: int, file: UploadFile = File(...)):
    if entity not in _IMAGE_ENTITIES:
        raise HTTPException(400, "esta entidad no admite imagen de referencia")
    ent = _entity_or_404(entity, eid)
    pid = ent["project_id"]
    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(400, "el archivo no es una imagen válida")
    rel = f"{images._ENTITY_FOLDER[entity]}/{eid}.png"
    out = db.project_dir(pid) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    db.update_entity(entity, eid, ref_image=rel)
    return {"ok": True, "ref_image": rel}


@app.post("/api/bible/voice/{eid}/sample")
async def voice_sample_ep(eid: int, req: Request):
    v = _entity_or_404("voice", eid)
    pid = v["project_id"]
    d = await _maybe_json(req)
    return _job(pid, "Muestra de voz",
                lambda: audio.gen_voice_sample(pid, eid, text=d.get("text") or "", model_key=d.get("model") or ""))


# ---------- exportaciones ----------

@app.get("/api/project/{pid}/export.json")
def export_json_ep(pid: int):
    if not db.get_project(pid):
        raise HTTPException(404)
    out = exporter.export_json(pid)
    return FileResponse(out, filename=f"project_{pid}.json", media_type="application/json",
                        headers={"Cache-Control": "no-cache"})


@app.post("/api/project/{pid}/export_zip")
def export_zip_ep(pid: int):
    if not db.get_project(pid):
        raise HTTPException(404)
    return _job(pid, "Exportar ZIP",
                lambda: db.set_status(pid, msg=f"ZIP listo: final/{exporter.export_zip(pid).name}"))


# ---------- enlace escena <-> entidades ----------

@app.post("/api/scene/{sid}/link")
async def link_scene(sid: int, req: Request):
    if not db.get_scene(sid):
        raise HTTPException(404)
    d = await _maybe_json(req)
    upd = {}
    if "char_ids" in d:
        upd["char_ids"] = json.dumps([int(x) for x in d["char_ids"]])
    if "prop_ids" in d:
        upd["prop_ids"] = json.dumps([int(x) for x in d["prop_ids"]])
    if "location_id" in d:
        upd["location_id"] = int(d["location_id"]) if d["location_id"] else None
    if upd:
        db.update_scene(sid, **upd)
    return {"ok": True}


# ---------- edición conversacional de la imagen de una escena ----------

@app.post("/api/scene/{sid}/edit_image")
async def edit_scene_image(sid: int, req: Request):
    scene = db.get_scene(sid)
    if not scene:
        raise HTTPException(404)
    d = await _maybe_json(req)
    instruction = (d.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(400, "instrucción vacía")
    pid = scene["project_id"]
    p = db.get_project(pid)
    model = d.get("model") or ""

    def work():
        for fmt in p["formats"]:
            images.edit_active_image(pid, sid, instruction, fmt=fmt, model_key=model)
        db.set_status(pid, msg=f"Escena {scene['ord'] + 1}: imagen editada")
    return _job(pid, "Editar imagen", work)


@app.post("/api/scene/{sid}/update")
async def update_scene(sid: int, req: Request):
    d = await req.json()
    allowed = {k: d[k] for k in ("visual", "dialogue", "camera", "emotion", "duration_s", "transition") if k in d}
    if allowed:
        db.update_scene(sid, **allowed)
    return {"ok": True}


def _has_active(pid, scene_id, kind, fmt):
    return any(a["format"] == fmt for a in db.get_assets(pid, scene_id=scene_id, kind=kind))


def _gen_images_for_scene(pid, p, scene, fmt, expects_text, model_key=""):
    # una imagen por escena: keyframe (vídeo) o slide (promo/cómic)
    kinds = ["keyframe_first"] if p["mode"] == "video" else ["slide"]
    for kind in kinds:
        if _has_active(pid, scene["id"], kind, fmt):
            continue  # ya generada: el job es reanudable sin repagar
        images.gen_scene_image(pid, scene["id"], kind, fmt, model_key=model_key)
        if not config.QC_ENABLED:
            continue  # decisión de diseño: sin QC automático; el humano aprueba a ojo
        for attempt in range(2):
            asset = db.get_assets(pid, scene_id=scene["id"], kind=kind)[-1]
            verdict = qc.review(pid, Path(asset["path"]), scene,
                                expects_text=expects_text if kind == "slide" else "")
            if verdict.get("ok", True):
                break
            fb = "; ".join(verdict.get("problems", []))[:400]
            db.set_status(pid, msg=f"QC escena {scene['ord'] + 1}: reintento ({fb[:120]})")
            images.gen_scene_image(pid, scene["id"], kind, fmt, feedback=fb, model_key=model_key)


@app.post("/api/project/{pid}/images")
async def gen_images(pid: int, req: Request):
    p = db.get_project(pid)
    model = (await _maybe_json(req)).get("model") or ""

    def work():
        scenes = db.get_scenes(pid)
        fails = []
        for fmt in p["formats"]:
            for s in scenes:
                db.set_status(pid, msg=f"Generando imagen escena {s['ord'] + 1}/{len(scenes)} ({fmt})")
                expects = images.balloon_spec(s["dialogue"])[1] if p["mode"] == "comic" else ""
                try:
                    _gen_images_for_scene(pid, p, s, fmt, expects, model_key=model)
                except Exception as e:  # una escena fallida no aborta las demás
                    fails.append(f"escena {s['ord'] + 1} ({fmt}): {vertex.scrub(e)[:120]}")
        if fails:
            db.set_status(pid, status="imagenes",
                          msg="⚠️ Terminado con fallos → " + " | ".join(fails[:4]) +
                              " — edita el texto de esas escenas y pulsa Regenerar")
        else:
            db.set_status(pid, status="imagenes", msg="Imágenes generadas. Revisa, corrige y aprueba escenas.")
    return _job(pid, "Imágenes", work)


@app.post("/api/scene/{sid}/regen")
async def regen_scene(sid: int, req: Request):
    d = await req.json()
    scene = db.get_scene(sid)
    if not scene:
        raise HTTPException(404)
    pid = scene["project_id"]
    p = db.get_project(pid)
    fb = d.get("feedback", "")
    model = d.get("model") or ""

    def work():
        for fmt in p["formats"]:
            kinds = ["keyframe_first"] if p["mode"] == "video" else ["slide"]
            for kind in kinds:
                images.gen_scene_image(pid, sid, kind, fmt, feedback=fb, model_key=model)
        db.set_status(pid, msg=f"Escena {scene['ord'] + 1} regenerada")
    return _job(pid, "Regenerar escena", work)


@app.post("/api/scene/{sid}/approve")
def approve_scene(sid: int):
    db.update_scene(sid, approved=1, status="aprobada")
    return {"ok": True}


@app.post("/api/project/{pid}/approve_all")
def approve_all(pid: int):
    for s in db.get_scenes(pid):
        db.update_scene(s["id"], approved=1, status="aprobada")
    return {"ok": True}


@app.post("/api/project/{pid}/audio")
def gen_audio(pid: int):
    p = db.get_project(pid)

    def work():
        scenes = db.get_scenes(pid)
        for s in scenes:
            db.set_status(pid, msg=f"Voz escena {s['ord'] + 1}/{len(scenes)}")
            audio.gen_voice(pid, s["id"])
            # si la escena ya tiene clip, refrescar su preview AV con la voz nueva
            for fmt in p["formats"]:
                if [a for a in db.get_assets(pid, scene_id=s["id"], kind="clip") if a["format"] == fmt]:
                    assemble.mux_scene_preview(pid, db.get_scene(s["id"]), fmt)
        if not db.get_assets(pid, scene_id=None, kind="music"):
            db.set_status(pid, msg="Generando música…")
            audio.gen_music(pid)
        db.set_status(pid, status="audio", msg="Audio listo" + (" (duraciones ajustadas a la voz)" if p["audio_first"] else ""))
    return _job(pid, "Audio", work)


@app.post("/api/scene/{sid}/reedit_video")
async def reedit_video(sid: int, req: Request):
    d = await req.json()
    scene = db.get_scene(sid)
    if not scene:
        raise HTTPException(404)
    pid = scene["project_id"]
    p = db.get_project(pid)

    def work():
        for fmt in p["formats"]:
            video.animate_scene(pid, sid, fmt, extra_prompt=d.get("prompt", ""))
            assemble.mux_scene_preview(pid, db.get_scene(sid), fmt)
        db.set_status(pid, msg=f"Escena {scene['ord'] + 1}: vídeo reeditado")
    return _job(pid, "Reeditar vídeo", work)


@app.post("/api/scene/{sid}/reedit_voice")
async def reedit_voice(sid: int, req: Request):
    d = await req.json()
    scene = db.get_scene(sid)
    if not scene:
        raise HTTPException(404)
    pid = scene["project_id"]
    p = db.get_project(pid)

    def work():
        audio.gen_voice(pid, sid, instruction=d.get("prompt", ""))
        for fmt in p["formats"]:
            if [a for a in db.get_assets(pid, scene_id=sid, kind="clip") if a["format"] == fmt]:
                assemble.mux_scene_preview(pid, db.get_scene(sid), fmt)
        db.set_status(pid, msg=f"Escena {scene['ord'] + 1}: voz reeditada")
    return _job(pid, "Reeditar voz", work)


@app.get("/api/project/{pid}/estimate_video")
def estimate_video(pid: int):
    p = db.get_project(pid)
    scenes = [s for s in db.get_scenes(pid) if s["approved"]]
    usd, secs = costs.estimate_video_phase(scenes, p["models"]["video"])
    return {"scenes": len(scenes), "seconds": secs, "usd": usd * len(p["formats"]),
            "formats": p["formats"], "model": p["models"]["video"]}


@app.post("/api/project/{pid}/animate")
def animate(pid: int):
    p = db.get_project(pid)
    scenes = [s for s in db.get_scenes(pid) if s["approved"]]
    if not scenes:
        raise HTTPException(400, "no hay escenas aprobadas")

    def work():
        fails = []
        for fmt in p["formats"]:
            for s in scenes:
                already = [a for a in db.get_assets(pid, scene_id=s["id"], kind="clip") if a["format"] == fmt]
                if already:
                    continue  # clip ya generado: no se repaga
                db.set_status(pid, msg=f"Animando escena {s['ord'] + 1}/{len(scenes)} ({fmt})… los clips tardan 1-5 min cada uno")
                try:
                    video.animate_scene(pid, s["id"], fmt)
                    assemble.mux_scene_preview(pid, db.get_scene(s["id"]), fmt)  # clip AV con su voz
                except Exception as e:
                    fails.append(f"escena {s['ord'] + 1} ({fmt}): {vertex.scrub(e)[:120]}")
        if fails:
            db.set_status(pid, status="video", msg="⚠️ Animación con fallos → " + " | ".join(fails[:3]))
        else:
            db.set_status(pid, status="video", msg="Clips generados. Pasa al montaje.")
    return _job(pid, "Animación", work)


@app.post("/api/project/{pid}/assemble")
def do_assemble(pid: int):
    p = db.get_project(pid)

    def work():
        outs = []
        for fmt in p["formats"]:
            db.set_status(pid, msg=f"Montando {fmt}…")
            if p["mode"] == "video":
                outs.append(assemble.assemble_video(pid, fmt))
            else:
                outs.append(str(assemble.export_stills(pid, fmt)))
        db.set_status(pid, status="listo", msg=f"¡Listo! {len(outs)} salida(s) en la sección Descargas.")
    return _job(pid, "Montaje", work)


@app.exception_handler(Exception)
async def err_handler(request, exc):
    return JSONResponse(status_code=500, content={"error": vertex.scrub(exc)})
