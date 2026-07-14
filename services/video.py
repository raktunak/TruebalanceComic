"""Animación de clips: Veo 3.1 (LRO con polling) y Gemini Omni Flash (experimental)."""
import time
from pathlib import Path

from google.genai import types

import config
import db
from services import vertex, costs

_VEO_DURATIONS = (4, 6, 8)


def _veo_duration(seconds: float) -> int:
    for d in _VEO_DURATIONS:
        if seconds <= d:
            return d
    return 8


def _keyframe_bytes(pid, scene_id, kind, fmt):
    assets = db.get_assets(pid, scene_id=scene_id, kind=kind)
    assets = [a for a in assets if a["format"] == fmt] or assets
    if not assets:
        return None
    f = Path(assets[-1]["path"])
    return f.read_bytes() if f.exists() else None


def animate_scene(pid, scene_id, fmt, extra_prompt="") -> str:
    """Genera el clip de una escena con el modelo de vídeo del proyecto.
    extra_prompt: indicaciones de mejora del usuario (botón 'reeditar vídeo')."""
    p = db.get_project(pid)
    model_key = p["models"]["video"]
    if model_key == "gemini-omni-flash-preview":
        return _animate_omni(pid, scene_id, fmt, model_key, extra_prompt)
    return _animate_veo(pid, scene_id, fmt, model_key, extra_prompt)


def _scene_has_tts(pid, scene_id) -> bool:
    return bool(db.get_assets(pid, scene_id=scene_id, kind="voice"))


def _clip_prompt(pid, scene, include_dialogue: bool, extra=""):
    from services import storyboard
    style = storyboard.get_style(pid)
    prompt = (
        f"Estilo: {style}. Escena: {scene['visual']}. Cámara: {scene['camera']}. "
        f"Emoción: {scene['emotion']}. Movimiento natural y fluido, sin cortes internos. "
        "Sin marcas, logotipos ni personajes de franquicias reconocibles."
    )
    if include_dialogue and scene["dialogue"]:
        # solo si el clip lleva audio nativo; los personajes gesticulan como si hablaran
        prompt += f" Los personajes dicen (en español, lip-sync): {scene['dialogue']}"
    elif scene["dialogue"]:
        prompt += " Los personajes conversan gesticulando de forma natural (el audio se añade aparte)."
    if extra:
        prompt += f" Ajustes solicitados: {extra}"
    return prompt


def _save_clip(pid, scene_id, ordn, fmt, data: bytes, model_key, seconds):
    safe_fmt = fmt.replace(":", "x")
    n = len(db.get_assets(pid, scene_id=scene_id, kind="clip", active_only=False)) + 1
    rel = f"clips/{ordn:02d}_{safe_fmt}_v{n}.mp4"
    out = db.project_dir(pid) / rel
    out.write_bytes(data)
    usd = costs.video_cost(model_key, seconds)
    costs.register(pid, model_key, f"clip escena {ordn + 1} ({seconds}s)", usd)
    db.add_asset(pid, scene_id, "clip", out, model=model_key, cost=usd, fmt=fmt)
    db.update_scene(scene_id, status="animada")
    return rel


def _animate_veo(pid, scene_id, fmt, model_key, extra_prompt="") -> str:
    scene = db.get_scene(scene_id)
    p = db.get_project(pid)
    loc = config.MODEL_REGISTRY[model_key]["location"]
    dur = _veo_duration(scene["duration_s"])

    first = _keyframe_bytes(pid, scene_id, "keyframe_first", fmt)
    last = _keyframe_bytes(pid, scene_id, "keyframe_last", fmt)
    if not first:
        raise RuntimeError(f"escena {scene['ord'] + 1}: falta keyframe inicial aprobado")

    # si hay locución TTS, el clip va sin audio nativo (el montaje usa la voz TTS)
    native_audio = not p["audio_first"] and not _scene_has_tts(pid, scene_id)
    cfg_kw = dict(
        aspect_ratio=fmt,
        duration_seconds=dur,
        number_of_videos=1,
        generate_audio=native_audio,
    )
    if last:
        cfg_kw["last_frame"] = types.Image(image_bytes=last, mime_type="image/png")

    def _call():
        return vertex.client(loc).models.generate_videos(
            model=config.real_model_id(model_key),
            prompt=_clip_prompt(pid, scene, include_dialogue=native_audio, extra=extra_prompt),
            image=types.Image(image_bytes=first, mime_type="image/png"),
            config=types.GenerateVideosConfig(**cfg_kw),
        )

    op = vertex.call_with_retry(_call)
    deadline = time.time() + 15 * 60
    while not op.done:
        if time.time() > deadline:
            raise RuntimeError("Veo: timeout esperando el clip (15 min)")
        time.sleep(10)
        op = vertex.client(loc).operations.get(op)

    result = getattr(op, "result", None) or getattr(op, "response", None)
    if getattr(op, "error", None):
        raise RuntimeError(f"Veo error: {str(op.error)[:300]}")
    vids = getattr(result, "generated_videos", None)
    if not vids:
        raise RuntimeError("Veo: operación terminada sin vídeos (¿filtro de seguridad?)")
    video = vids[0].video
    data = getattr(video, "video_bytes", None)
    if not data:
        raise RuntimeError("Veo: el clip no llegó como bytes (revisa si requiere GCS)")
    return _save_clip(pid, scene_id, scene["ord"], fmt, data, model_key, dur)


def _animate_omni(pid, scene_id, fmt, model_key, extra_prompt="") -> str:
    """Omni Flash: vídeo vía generate_content (EXPERIMENTAL, validar primera llamada)."""
    scene = db.get_scene(scene_id)
    loc = config.MODEL_REGISTRY[model_key]["location"]
    first = _keyframe_bytes(pid, scene_id, "keyframe_first", fmt)

    parts = []
    if first:
        parts.append(types.Part.from_text(text="Primer fotograma del clip:"))
        parts.append(types.Part.from_bytes(data=first, mime_type="image/png"))
    dur = _veo_duration(scene["duration_s"])
    parts.append(f"Genera un vídeo de {dur} segundos, formato {fmt}. "
                 f"{_clip_prompt(pid, scene, include_dialogue=not _scene_has_tts(pid, scene_id), extra=extra_prompt)}")

    def _call():
        return vertex.client(loc).models.generate_content(
            model=config.real_model_id(model_key),
            contents=parts,
            config=types.GenerateContentConfig(response_modalities=["VIDEO"]),
        )

    r = vertex.call_with_retry(_call)
    data = None
    for part in r.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data and "video" in (inline.mime_type or ""):
            data = inline.data
            break
    if not data:
        raise RuntimeError("Omni: la respuesta no contiene vídeo")
    return _save_clip(pid, scene_id, scene["ord"], fmt, data, model_key, dur)
