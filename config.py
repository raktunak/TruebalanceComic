"""Registro central de modelos Vertex AI (proyecto brainrot-walloop).

Solo modelos Google verificados por API el 2026-07-14. Precios en USD.
Imagen/texto -> location "global"; video Veo -> "us-central1"; Omni Flash en ambas.
"""

GCP_PROJECT = "brainrot-walloop"
GCLOUD_ACCOUNT = "out.brainrot@gmail.com"
LOC_GLOBAL = "global"
LOC_US = "us-central1"

# task: storyboard | image | video | tts | music | qc
MODEL_REGISTRY = {
    # --- Texto / razonamiento (storyboard, QC) ---
    "gemini-3.1-pro-preview": {
        "task": "storyboard", "location": LOC_GLOBAL, "label": "Gemini 3.1 Pro (mejor guionista)",
        "price_unit": "1M tokens", "price_in": 2.0, "price_out": 12.0, "default": True,
    },
    "gemini-3.5-flash": {
        "task": "storyboard", "location": LOC_GLOBAL, "label": "Gemini 3.5 Flash (rápido y barato)",
        "price_unit": "1M tokens", "price_in": 0.30, "price_out": 2.50, "default": False,
    },
    # --- Imagen ---
    "gemini-3.1-flash-lite-image": {
        "task": "image", "location": LOC_GLOBAL, "label": "Nano Banana Lite ($0.034/img — iterar)",
        "price_unit": "imagen", "price": 0.034, "default": True,
    },
    "gemini-3.1-flash-image": {
        "task": "image", "location": LOC_GLOBAL, "label": "Nano Banana Flash (intermedio)",
        "price_unit": "imagen", "price": 0.067, "default": False,
    },
    "gemini-3-pro-image": {
        "task": "image", "location": LOC_GLOBAL, "label": "Nano Banana Pro ($0.134/img — final)",
        "price_unit": "imagen", "price": 0.134, "default": False,
        "prompt_suffix": " Prohibido: asteriscos visibles, marcas de agua, frases repetidas.",
    },
    # --- Vídeo (todos us-central1, clips máx 8s, i2v + first/last frame en 3.1) ---
    "veo-3.1-lite-generate-001": {
        "task": "video", "location": LOC_US, "label": "Veo 3.1 Lite ($0.05/s — iterar)",
        "price_unit": "segundo", "price": 0.05, "default": False, "max_s": 8,
    },
    "veo-3.1-fast-generate-001": {
        "task": "video", "location": LOC_US, "label": "Veo 3.1 Fast ($0.15/s — default)",
        "price_unit": "segundo", "price": 0.15, "default": True, "max_s": 8,
    },
    "veo-3.1-generate-001": {
        "task": "video", "location": LOC_US, "label": "Veo 3.1 Standard ($0.40/s — máxima calidad)",
        "price_unit": "segundo", "price": 0.40, "default": False, "max_s": 8,
    },
    "gemini-omni-flash-preview": {
        "task": "video", "location": LOC_US, "label": "Gemini Omni Flash ($0.10/s — edición conversacional)",
        "price_unit": "segundo", "price": 0.10, "default": False, "max_s": 8,
        "experimental": True,  # pendiente de primera llamada real OK
    },
    # --- TTS voz ---
    "gemini-2.5-flash-tts": {
        "task": "tts", "location": LOC_GLOBAL, "label": "Gemini Flash TTS (voz barata)",
        "price_unit": "1M tokens", "price_in": 0.50, "price_out": 10.0, "default": True,
    },
    "gemini-2.5-pro-tts": {
        "task": "tts", "location": LOC_GLOBAL, "label": "Gemini Pro TTS (voz premium)",
        "price_unit": "1M tokens", "price_in": 1.0, "price_out": 20.0, "default": False,
    },
    # --- Música ---
    "lyria-3-clip-preview": {
        "task": "music", "location": LOC_US, "label": "Lyria 3 Clip (BSO, preview)",
        "price_unit": "clip", "price": 0.06, "default": True, "experimental": True,
    },
    "lyria-002": {
        "task": "music", "location": LOC_US, "label": "Lyria 2 (BSO estable)",
        "price_unit": "clip", "price": 0.06, "default": False,
    },
    # --- QC visión ---
    "gemini-3.5-flash-qc": {
        "task": "qc", "location": LOC_GLOBAL, "label": "QC visión (Gemini 3.5 Flash)",
        "price_unit": "1M tokens", "price_in": 0.30, "price_out": 2.50, "default": True,
        "model_id": "gemini-3.5-flash",
    },
}

MODES = {
    "video": "Vídeo (keyframes → animación → montaje)",
    "promo": "Slides promocionales",
    "comic": "Cómic",
}

FORMATS = ["9:16", "16:9"]

# Decisión de diseño: el sistema NO comprueba nada automáticamente; genera y muestra, el humano
# aprueba a ojo. El módulo services/qc.py se conserva pero queda desactivado por defecto.
QC_ENABLED = False

VOICES = ["Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda"]  # voces prebuilt Gemini TTS
VOICE_GENDER = {"Kore": "mujer", "Aoede": "mujer", "Leda": "mujer",
                "Puck": "hombre", "Charon": "hombre", "Fenrir": "hombre"}


def models_for(task: str) -> dict:
    out = {}
    for mid, m in MODEL_REGISTRY.items():
        if m["task"] == task:
            out[mid] = m
    return out


def default_model(task: str) -> str:
    for mid, m in MODEL_REGISTRY.items():
        if m["task"] == task and m.get("default"):
            return mid
    raise KeyError(f"sin default para {task}")


def real_model_id(mid: str) -> str:
    """ID que se envía a la API (algunas entradas del registry son alias)."""
    return MODEL_REGISTRY[mid].get("model_id", mid)
