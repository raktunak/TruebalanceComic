"""Biblias: crear personaje / localización / objeto rellenando la ficha por prompt.

La IA solo estructura los campos a partir de la descripción libre del usuario; el humano
luego revisa, aprueba y (decisión de diseño) la IMAGEN de referencia manda sobre el texto.
Patrón de llamada estructurada calcado de services/storyboard.py.
"""
import json

from google.genai import types

import config
import db
from services import vertex, costs

# Campos que la IA rellena por tipo de entidad. Concreto y estable, sin marcas/IP.
_SCHEMAS = {
    "character": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "description": {"type": "STRING", "description": "Físico, edad, ropa, rasgos distintivos. Muy concreto y estable."},
            "gender": {"type": "STRING", "description": "hombre | mujer"},
        },
        "required": ["name", "description", "gender"],
    },
    "location": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "type": {"type": "STRING", "description": "interior | exterior u otro tipo de espacio"},
            "description": {"type": "STRING", "description": "Arquitectura, materiales, colores, iluminación, mobiliario, atmósfera. Concreto y estable."},
        },
        "required": ["name", "type", "description"],
    },
    "prop": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "category": {"type": "STRING", "description": "objeto | vehiculo | vestuario | accesorio | mascota"},
            "description": {"type": "STRING", "description": "Materiales, colores, tamaño, estado, rasgos distintivos. Concreto y estable."},
        },
        "required": ["name", "category", "description"],
    },
}

_ENTITY_LABEL = {"character": "personaje", "location": "localización", "prop": "objeto"}

# columnas válidas por entidad (evita inyectar claves ajenas a la tabla)
_FIELDS = {
    "character": ("name", "description", "gender"),
    "location": ("name", "type", "description"),
    "prop": ("name", "category", "description"),
}


def fill_entity(pid: int, entity: str, user_prompt: str, model_key: str = "") -> int:
    """La IA rellena la ficha de la entidad a partir de la descripción libre. Devuelve el id creado."""
    if entity not in _SCHEMAS:
        raise ValueError(f"entidad sin ficha: {entity}")
    p = db.get_project(pid)
    model_key = model_key or p["models"]["storyboard"]
    mid = config.real_model_id(model_key)
    loc = config.MODEL_REGISTRY[model_key]["location"]

    prompt = (
        f"Rellena la ficha de {_ENTITY_LABEL[entity]} para una producción audiovisual, en español, "
        "concreta y estable (que se pueda reproducir idéntica en todas las escenas). "
        "NO menciones marcas, franquicias, logotipos ni personajes de terceros (ropa lisa sin logos, "
        "objetos genéricos). Responde SOLO el JSON.\n\n"
        f"DESCRIPCIÓN DEL USUARIO:\n{user_prompt.strip()}"
    )

    def _call():
        return vertex.client(loc).models.generate_content(
            model=mid, contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMAS[entity],
                temperature=0.7,
            ),
        )

    r = vertex.call_with_retry(_call)
    data = json.loads(r.text)
    usd = costs.token_cost(model_key, r.usage_metadata)
    costs.register(pid, model_key, f"ficha {entity}", usd)

    cols = {k: data.get(k, "") for k in _FIELDS[entity] if data.get(k) is not None}
    return db.add_entity(pid, entity, **cols)
