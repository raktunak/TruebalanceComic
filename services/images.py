"""Generación de imágenes: fichas de personaje, slides, viñetas y keyframes.

Consistencia: el estilo global + las imágenes de referencia de los personajes
se inyectan en cada llamada. En modo vídeo, el keyframe final de la escena N
se pasa como referencia de continuidad para la escena N+1.
"""
import re
from pathlib import Path

from google.genai import types

import config
import db
from services import vertex, costs, storyboard


def _img_config(model_key, fmt):
    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=fmt),
    )
    return cfg


def _extract_image(resp) -> bytes:
    cands = getattr(resp, "candidates", None) or []
    for cand in cands:
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            if getattr(part, "inline_data", None) and part.inline_data.data:
                return part.inline_data.data
    reason = str(getattr(cands[0], "finish_reason", "") or "") if cands else "sin candidatos"
    fb = getattr(resp, "prompt_feedback", None)
    if fb and getattr(fb, "block_reason", None):
        reason += f" / bloqueo: {fb.block_reason}"
    raise RuntimeError(
        f"imagen bloqueada o vacía ({reason}). Suele ser el filtro de contenido: "
        "quita marcas/franquicias del texto de la escena y regenera"
    )


def _generate(pid, model_key, parts, fmt, out_path: Path, units_label):
    mid = config.real_model_id(model_key)
    loc = config.MODEL_REGISTRY[model_key]["location"]

    def _call():
        return vertex.client(loc).models.generate_content(
            model=mid, contents=parts, config=_img_config(model_key, fmt),
        )

    r = vertex.call_with_retry(_call)
    data = _extract_image(r)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    usd = costs.image_cost(model_key)
    costs.register(pid, model_key, units_label, usd)
    return usd


def _ref_parts(pid, only_names=None):
    """Imágenes de referencia de personajes aprobadas, como parts."""
    parts = []
    for ch in db.get_characters(pid):
        if not ch["ref_image"]:
            continue
        if only_names and not any(n.lower() in ch["name"].lower() or ch["name"].lower() in n.lower()
                                   for n in only_names):
            continue
        f = db.project_dir(pid) / ch["ref_image"]
        if f.exists():
            parts.append(types.Part.from_text(text=f"Referencia del personaje {ch['name']} ({ch['description']}):"))
            parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/png"))
    return parts


def gen_character_ref(pid, char_id) -> str:
    """Ficha de referencia de un personaje (cuerpo entero, fondo neutro)."""
    p = db.get_project(pid)
    ch = next(c for c in db.get_characters(pid) if c["id"] == char_id)
    style = storyboard.get_style(pid)
    model_key = p["models"]["image"]
    prompt = (
        f"Ficha de referencia de personaje para producción audiovisual. Estilo: {style}. "
        f"Personaje: {ch['name']}. {ch['description']}. "
        "Cuerpo entero, pose neutra de pie, fondo gris liso, iluminación uniforme. "
        "Sin texto, sin marcas de agua." + config.MODEL_REGISTRY[model_key].get("prompt_suffix", "")
    )
    rel = f"characters/{char_id}.png"
    _generate(pid, model_key, [prompt], "9:16", db.project_dir(pid) / rel, f"ficha {ch['name']}")
    db.update_character(char_id, ref_image=rel)
    return rel


_SPEAKER_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ]{2,20}):\s*")


def balloon_spec(dialogue: str):
    """'ANA: hola LUIS: adiós' → (instrucción de globos por personaje, texto plano sin nombres)."""
    dialogue = (dialogue or "").strip()
    parts = _SPEAKER_RE.split(dialogue)
    if len(parts) < 3:
        return (f'un globo de diálogo con exactamente este texto: "{dialogue}"', dialogue)
    instr, plain = [], []
    for i in range(1, len(parts) - 1, 2):
        name, text = parts[i].title(), parts[i + 1].strip().strip('"')
        if text:
            instr.append(f'un globo saliendo de la boca de {name} con exactamente: "{text}"')
            plain.append(text)
    return ("; ".join(instr), " / ".join(plain))


def _scene_prompt(p, scene, style, kind):
    mode = p["mode"]
    base = f"Estilo visual OBLIGATORIO (idéntico en toda la serie): {style}. "
    if mode == "comic":
        speech = ""
        if scene["dialogue"]:
            instr, _ = balloon_spec(scene["dialogue"])
            speech = (
                f" Incluye {instr}. Los globos contienen SOLO las palabras dichas, bien escritas y sin erratas; "
                "NUNCA escribas el nombre del personaje dentro del globo (el globo apunta a quien habla)."
            )
        return (
            base + f"Viñeta de cómic. {scene['visual']}. Emoción: {scene['emotion']}. "
            f"Composición: {scene['camera']}.{speech} Estética de cómic profesional, líneas limpias."
        )
    if mode == "promo":
        return (
            base + f"Imagen para slide promocional. {scene['visual']}. Emoción: {scene['emotion']}. "
            "Composición limpia con tercio superior despejado para superponer texto. Sin texto en la imagen."
        )
    # video: un fotograma clave por escena (Veo lo anima con image-to-video)
    return (
        base + f"Fotograma cinematográfico que captura el momento clave de esta escena: {scene['visual']}. "
        f"Plano: {scene['camera']}. Emoción: {scene['emotion']}. "
        "Fotograma realista de vídeo, sin texto, sin subtítulos. Atrezzo genérico: "
        "sin marcas, logotipos ni personajes de franquicias reconocibles."
    )


def gen_scene_image(pid, scene_id, kind, fmt, feedback: str = ""):
    """Genera slide/viñeta/keyframe de una escena. feedback = correcciones del QC o del usuario."""
    p = db.get_project(pid)
    scene = db.get_scene(scene_id)
    style = storyboard.get_style(pid)
    model_key = p["models"]["image"]

    parts: list = []
    parts += _ref_parts(pid)

    # continuidad en vídeo: el fotograma de la escena anterior (mismo formato) como referencia
    if p["mode"] == "video":
        scenes = db.get_scenes(pid)
        prev = next((s for s in scenes if s["ord"] == scene["ord"] - 1), None)
        if prev:
            prev_kf = db.get_assets(pid, scene_id=prev["id"], kind="keyframe_first")
            prev_kf = [a for a in prev_kf if a["format"] == fmt] or prev_kf
            if prev_kf:
                f = Path(prev_kf[-1]["path"])
                if f.exists():
                    parts.append(types.Part.from_text(
                        text="Fotograma de la escena anterior (mantén continuidad de escenario, luz y vestuario):"))
                    parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/png"))

    prompt = _scene_prompt(p, scene, style, kind)
    if feedback:
        prompt += f" CORRECCIONES OBLIGATORIAS respecto al intento anterior: {feedback}"
    prompt += config.MODEL_REGISTRY[model_key].get("prompt_suffix", "")
    parts.append(prompt)

    safe_fmt = fmt.replace(":", "x")
    n = len(db.get_assets(pid, scene_id=scene_id, kind=kind, active_only=False)) + 1
    rel = f"scenes/{scene['ord']:02d}_{kind}_{safe_fmt}_v{n}.png"
    out = db.project_dir(pid) / rel
    _generate(pid, model_key, parts, fmt, out, f"escena {scene['ord'] + 1} {kind}")
    db.add_asset(pid, scene_id, kind, out, model=model_key,
                 cost=costs.image_cost(model_key), fmt=fmt)
    db.update_scene(scene_id, status="imagen")
    return rel
