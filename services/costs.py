"""Cálculo y registro de costes por llamada."""
import config
import db


def _price(model_key):
    return config.MODEL_REGISTRY[model_key]


def image_cost(model_key, n=1):
    return _price(model_key)["price"] * n


def video_cost(model_key, seconds):
    return _price(model_key)["price"] * seconds


def token_cost(model_key, usage):
    """usage: objeto usage_metadata de la respuesta genai."""
    m = _price(model_key)
    tin = getattr(usage, "prompt_token_count", 0) or 0
    tout = getattr(usage, "candidates_token_count", 0) or 0
    return (tin * m.get("price_in", 0) + tout * m.get("price_out", 0)) / 1_000_000


def music_cost(model_key, clips=1):
    return _price(model_key)["price"] * clips


def register(pid, model_key, units, usd):
    db.add_cost(pid, model_key, units, round(usd, 6))


def estimate_video_phase(scenes, model_key):
    """Coste estimado de animar todas las escenas aprobadas."""
    total_s = sum(min(s["duration_s"], config.MODEL_REGISTRY[model_key].get("max_s", 8)) for s in scenes)
    return round(video_cost(model_key, total_s), 2), total_s
