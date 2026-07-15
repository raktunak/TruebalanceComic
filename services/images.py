"""Generación de imágenes: fichas de personaje, slides, viñetas y keyframes.

Consistencia: el estilo global + las imágenes de referencia de los personajes
se inyectan en cada llamada. En modo vídeo, el keyframe final de la escena N
se pasa como referencia de continuidad para la escena N+1.
"""
import json
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
    """Imágenes de referencia de personajes aprobadas, como parts (todos los del proyecto)."""
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


def _json_list(v):
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        x = json.loads(v)
        return x if isinstance(x, list) else []
    except Exception:
        return []


def _img_part(pid, rel, label):
    f = db.project_dir(pid) / rel
    if not f.exists():
        return []
    return [types.Part.from_text(text=label),
            types.Part.from_bytes(data=f.read_bytes(), mime_type="image/png")]


def _scene_ref_parts(pid, scene):
    """Referencias aprobadas a inyectar en la escena: personajes/localización/objetos enlazados.

    Si la escena no trae enlaces (storyboard antiguo), cae al comportamiento previo: todos los
    personajes del proyecto. La IMAGEN de referencia manda sobre el texto (decisión de diseño).
    """
    parts = []
    char_ids = _json_list(scene.get("char_ids"))
    chars = db.get_characters(pid)
    if char_ids:
        chars = [c for c in chars if c["id"] in char_ids]
    for ch in chars:
        if ch.get("ref_image"):
            parts += _img_part(pid, ch["ref_image"],
                               f"Referencia del personaje {ch['name']} ({ch['description']}):")
    loc_id = scene.get("location_id")
    if loc_id:
        loc = db.get_entity("location", loc_id)
        if loc and loc.get("ref_image"):
            parts += _img_part(pid, loc["ref_image"],
                               f"Referencia de la localización {loc['name']} "
                               "(mantén su distribución, luz y materiales):")
    for prop_id in _json_list(scene.get("prop_ids")):
        prop = db.get_entity("prop", prop_id)
        if prop and prop.get("ref_image"):
            parts += _img_part(pid, prop["ref_image"],
                               f"Referencia del objeto {prop['name']} (mantén su diseño):")
    return parts


def _present_names(pid, scene):
    char_ids = _json_list(scene.get("char_ids"))
    if not char_ids:
        return []
    return [c["name"] for c in db.get_characters(pid) if c["id"] in char_ids]


_ENTITY_FOLDER = {"character": "characters", "location": "locations", "prop": "props"}


def _entity_ref_prompt(entity, ent, style, suffix):
    if entity == "location":
        return (
            f"Plate de referencia de LOCALIZACIÓN para producción audiovisual. Estilo: {style}. "
            f"Lugar: {ent['name']} ({ent.get('type', '')}). {ent['description']}. "
            "Plano general del espacio VACÍO (sin personajes), iluminación coherente, "
            "sin texto, sin marcas de agua." + suffix
        )
    if entity == "prop":
        return (
            f"Ficha de referencia de OBJETO para producción audiovisual. Estilo: {style}. "
            f"Objeto: {ent['name']} ({ent.get('category', '')}). {ent['description']}. "
            "El objeto centrado sobre fondo gris liso, iluminación de estudio, "
            "sin texto, sin marcas de agua." + suffix
        )
    return (
        f"Ficha de referencia de PERSONAJE para producción audiovisual. Estilo: {style}. "
        f"Personaje: {ent['name']}. {ent['description']}. "
        "Cuerpo entero, pose neutra de pie, fondo gris liso, iluminación uniforme. "
        "Sin texto, sin marcas de agua." + suffix
    )


def gen_entity_ref(pid, entity, eid, model_key="") -> str:
    """Genera la imagen de referencia de una entidad de biblia (personaje/localización/objeto)."""
    p = db.get_project(pid)
    ent = db.get_entity(entity, eid)
    style = storyboard.get_style(pid)
    model_key = model_key or p["models"]["image"]
    suffix = config.MODEL_REGISTRY[model_key].get("prompt_suffix", "")
    prompt = _entity_ref_prompt(entity, ent, style, suffix)
    rel = f"{_ENTITY_FOLDER[entity]}/{eid}.png"
    _generate(pid, model_key, [prompt], "9:16", db.project_dir(pid) / rel, f"ref {ent['name']}")
    db.update_entity(entity, eid, ref_image=rel)
    return rel


def gen_character_ref(pid, char_id, model_key="") -> str:
    """Ficha de referencia de un personaje (compat: delega en gen_entity_ref)."""
    return gen_entity_ref(pid, "character", char_id, model_key=model_key)


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


def gen_scene_image(pid, scene_id, kind, fmt, feedback: str = "", model_key: str = ""):
    """Genera slide/viñeta/keyframe de una escena. feedback = correcciones del QC o del usuario.
    model_key permite sobreescribir el modelo del proyecto solo para esta llamada."""
    p = db.get_project(pid)
    scene = db.get_scene(scene_id)
    style = storyboard.get_style(pid)
    model_key = model_key or p["models"]["image"]

    parts: list = []
    parts += _scene_ref_parts(pid, scene)

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
    present = _present_names(pid, scene)
    if len(present) > 1:  # etiquetado de personajes cuando hay varios en el plano
        prompt += (f" Personajes presentes en el plano: {', '.join(present)}. "
                   "Mantén la identidad de cada uno según su imagen de referencia.")
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


def edit_active_image(pid, scene_id, instruction, kind: str = "", fmt: str = "", model_key: str = ""):
    """Edición conversacional (Nano Banana, vía verificada): parte de la imagen activa de la escena,
    aplica una instrucción del usuario manteniendo la identidad y guarda una versión nueva.

    Es el §10 del spec (cambiar zona/vestuario/objeto/fondo) sin máscara: 'edit_image' tipado da 404
    en el proyecto; esta es la única vía que funciona (ver pendientes/PENDIENTES.md).
    """
    p = db.get_project(pid)
    scene = db.get_scene(scene_id)
    model_key = model_key or p["models"]["image"]
    kind = kind or ("keyframe_first" if p["mode"] == "video" else "slide")
    fmt = fmt or p["formats"][0]

    actives = [a for a in db.get_assets(pid, scene_id=scene_id, kind=kind) if a["format"] == fmt]
    if not actives:
        raise RuntimeError("no hay imagen activa que editar en esta escena; genérala primero")
    data = Path(actives[-1]["path"]).read_bytes()

    prompt = (
        "Edita esta imagen manteniendo EXACTAMENTE la misma identidad (rostro, pelo, edad, "
        "proporciones), el mismo encuadre, estilo e iluminación. Aplica solo este cambio pedido por "
        f"el usuario: {instruction.strip()}. Sin texto, sin marcas de agua."
        + config.MODEL_REGISTRY[model_key].get("prompt_suffix", "")
    )
    parts = [types.Part.from_bytes(data=data, mime_type="image/png"),
             types.Part.from_text(text=prompt)]

    safe_fmt = fmt.replace(":", "x")
    n = len(db.get_assets(pid, scene_id=scene_id, kind=kind, active_only=False)) + 1
    rel = f"scenes/{scene['ord']:02d}_{kind}_{safe_fmt}_v{n}.png"
    out = db.project_dir(pid) / rel
    _generate(pid, model_key, parts, fmt, out, f"edición escena {scene['ord'] + 1}")
    db.add_asset(pid, scene_id, kind, out, model=model_key,
                 cost=costs.image_cost(model_key), fmt=fmt)
    db.update_scene(scene_id, status="imagen")
    return rel
