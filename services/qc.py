"""QC automático con visión: revisa consistencia y defectos antes de enseñar la imagen."""
import json
from pathlib import Path

from google.genai import types

import config
import db
from services import vertex, costs

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ok": {"type": "BOOLEAN"},
        "problems": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["ok", "problems"],
}


def review(pid, image_path: Path, scene, expects_text: str = "") -> dict:
    """Devuelve {ok, problems}. Tolerante: solo suspende defectos graves."""
    model_key = "gemini-3.5-flash-qc"
    mid = config.real_model_id(model_key)
    loc = config.MODEL_REGISTRY[model_key]["location"]

    parts = []
    for ch in db.get_characters(pid):
        if ch["ref_image"]:
            f = db.project_dir(pid) / ch["ref_image"]
            if f.exists():
                parts.append(types.Part.from_text(text=f"Referencia de {ch['name']}:"))
                parts.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/png"))
    parts.append(types.Part.from_text(text="Imagen a revisar:"))
    parts.append(types.Part.from_bytes(data=image_path.read_bytes(), mime_type="image/png"))

    checks = (
        "1) Anatomía correcta (manos, caras). "
        "2) Personajes consistentes con sus referencias (cara, ropa, edad). "
        "3) Sin texto corrupto, marcas de agua ni artefactos graves. "
    )
    if expects_text:
        checks += f"4) Si hay globos/texto, debe decir exactamente: \"{expects_text}\" sin erratas. "
    parts.append(types.Part.from_text(text=(
        f"Eres control de calidad de una productora. Escena esperada: {scene['visual']}. "
        f"Revisa SOLO defectos graves: {checks}"
        "Si es aceptable para publicar, ok=true. Lista solo problemas graves y accionables (en español)."
    )))

    def _call():
        return vertex.client(loc).models.generate_content(
            model=mid, contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_SCHEMA, temperature=0.1,
            ),
        )

    try:
        r = vertex.call_with_retry(_call)
        usd = costs.token_cost(model_key, r.usage_metadata)
        costs.register(pid, model_key, "qc", usd)
        return json.loads(r.text)
    except Exception as e:  # el QC nunca debe tumbar el pipeline
        return {"ok": True, "problems": [f"QC no disponible: {vertex.scrub(e)[:120]}"]}
