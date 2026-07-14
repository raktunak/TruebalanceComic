"""Guion → biblia de personajes + storyboard de escenas (JSON estructurado)."""
import json

from google.genai import types

import config
import db
from services import vertex, costs

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "style": {"type": "STRING", "description": "Estilo visual global: técnica, paleta, iluminación, época"},
        "characters": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "description": {"type": "STRING", "description": "Físico, edad, ropa, rasgos distintivos. Muy concreto y estable."},
                    "gender": {"type": "STRING", "description": "hombre | mujer"},
                },
                "required": ["name", "description", "gender"],
            },
        },
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "visual": {"type": "STRING", "description": "Qué se ve: acción, escenario, personajes presentes"},
                    "dialogue": {"type": "STRING", "description": "Diálogo o texto en pantalla (vacío si no hay). Si hablan varios, formato 'NOMBRE: frase'"},
                    "speaker": {"type": "STRING", "description": "Nombre EXACTO del personaje que habla, o 'narrador' si es voz en off"},
                    "camera": {"type": "STRING", "description": "Plano y movimiento de cámara"},
                    "emotion": {"type": "STRING"},
                    "duration_s": {"type": "NUMBER", "description": "Duración propuesta 2-8 segundos"},
                    "transition": {"type": "STRING", "description": "corte | fundido | barrido"},
                },
                "required": ["visual", "dialogue", "camera", "emotion", "duration_s"],
            },
        },
    },
    "required": ["title", "style", "characters", "scenes"],
}

_MODE_BRIEF = {
    "video": (
        "Vas a crear el storyboard de un VÍDEO corto para redes sociales. Reglas: "
        "1) El primer plano (hook) debe enganchar en 2 segundos: conflicto o pregunta directa. "
        "2) Cada escena dura entre 2 y 8 segundos (máximo 8, límite técnico). "
        "3) Arco: problema → tensión → giro → solución → llamada a la acción final. "
        "4) 'visual' describe UNA sola acción clara por escena (se animará como clip). "
        "5) Continuidad: escenario y ropa coherentes entre escenas consecutivas."
    ),
    "promo": (
        "Vas a crear SLIDES PROMOCIONALES (carrusel para redes). Reglas: "
        "1) Slide 1 = gancho potente (dolor del usuario). "
        "2) 'dialogue' es el texto grande del slide: máximo 12 palabras, directo. "
        "3) Progresión: dolor → agitación → solución (el producto) → beneficios → CTA final. "
        "4) 'visual' describe la imagen de fondo, limpia, con espacio para el texto."
    ),
    "comic": (
        "Vas a crear un CÓMIC de viñetas. Reglas: "
        "1) 'dialogue' son las líneas de los personajes (formato 'NOMBRE: frase', una o dos por viñeta, cortas). "
        "2) 'visual' describe la viñeta: acción, expresiones exageradas, composición. "
        "3) Humor o drama reconocible; remate final con el producto como solución. "
        "4) Máximo 8 viñetas."
    ),
}


def generate(pid: int) -> dict:
    """Genera personajes + escenas y los persiste. Devuelve el storyboard."""
    p = db.get_project(pid)
    model_key = p["models"]["storyboard"]
    mid = config.real_model_id(model_key)
    loc = config.MODEL_REGISTRY[model_key]["location"]

    prompt = (
        f"{_MODE_BRIEF[p['mode']]}\n"
        "REGLA TRANSVERSAL: ni en 'visual' ni en las DESCRIPCIONES de personajes menciones "
        "marcas, franquicias, logotipos ni personajes de terceros (Marvel, arañas de Spider-Man, "
        "iPhone, IKEA...): ropa lisa sin logos, objetos y cajas genéricas sin ilustraciones, "
        "('figuras coleccionables', 'móvil', 'estantería'). Los filtros de imagen y vídeo "
        "bloquean cualquier IP visible.\n\n"
        f"GUION DEL USUARIO:\n{p['script']}\n\n"
        "Responde SOLO el JSON del storyboard. Los textos van en español. "
        "En 'characters' incluye TODOS los personajes visibles con descripción física precisa y estable "
        "(misma ropa y aspecto en todas las escenas). En 'style' define un estilo visual único para todo el proyecto."
    )

    def _call():
        return vertex.client(loc).models.generate_content(
            model=mid,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0.8,
            ),
        )

    r = vertex.call_with_retry(_call)
    data = json.loads(r.text)
    usd = costs.token_cost(model_key, r.usage_metadata)
    costs.register(pid, model_key, "storyboard", usd)

    db.replace_characters(pid, data.get("characters", []))
    db.replace_scenes(pid, data.get("scenes", []))
    assign_voices(pid)
    db.set_status(pid, status="storyboard", msg=f"Storyboard listo: {len(data.get('scenes', []))} escenas")

    # guardamos style/title en el propio proyecto (script no se toca)
    with db.conn() as c:
        c.execute("UPDATE projects SET title=?, status_msg=? WHERE id=?",
                  (data.get("title", p["title"]), f"Estilo: {data.get('style','')[:180]}", pid))
    _save_style(pid, data.get("style", ""))
    return data


def assign_voices(pid):
    """Reparte voces TTS por género del personaje (rotando para no repetir)."""
    pools = {
        "hombre": [v for v in config.VOICES if config.VOICE_GENDER[v] == "hombre"],
        "mujer": [v for v in config.VOICES if config.VOICE_GENDER[v] == "mujer"],
    }
    idx = {"hombre": 0, "mujer": 0}
    for ch in db.get_characters(pid):
        if ch.get("voice"):
            continue
        g = (ch.get("gender") or "").strip().lower()
        pool = pools.get(g) or config.VOICES
        db.update_character(ch["id"], voice=pool[idx.get(g, 0) % len(pool)])
        if g in idx:
            idx[g] += 1


def _style_path(pid):
    return db.project_dir(pid) / "style.txt"


def _save_style(pid, style: str):
    _style_path(pid).write_text(style or "", encoding="utf-8")


def get_style(pid) -> str:
    f = _style_path(pid)
    return f.read_text(encoding="utf-8") if f.exists() else ""
