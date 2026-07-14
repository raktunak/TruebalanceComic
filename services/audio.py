"""Audio: voz TTS por escena (Gemini) y música (Lyria).

Cada personaje tiene su voz (asignada por género en el storyboard, editable en la UI).
Si en una escena hablan dos, se usa TTS multi-speaker; 'narrador' usa la voz del proyecto.
El TTS devuelve PCM 24kHz 16-bit mono; se envuelve en WAV.
La duración real de la voz fija duration_s de la escena en modo audio-first.
"""
import base64
import re
import wave
from pathlib import Path

import requests
from google.genai import types

import config
import db
from services import vertex, costs

PCM_RATE = 24000
_SPK = re.compile(r"\b([A-ZÁÉÍÓÚÑ]{2,20}):\s*")


def _dialogue_parts(text):
    """'ANA: hola LUIS: adiós' → [('Ana','hola'), ('Luis','adiós')]. [] si no hay prefijos."""
    parts = _SPK.split(text or "")
    if len(parts) < 3:
        return []
    out = []
    for i in range(1, len(parts) - 1, 2):
        t = parts[i + 1].strip()
        if t:
            out.append((parts[i].title(), t))
    return out


def _voice_for(p, chars_by_name, speaker):
    s = (speaker or "").strip().lower()
    ch = chars_by_name.get(s)
    if ch and ch.get("voice"):
        return ch["voice"]
    return p["voice"]  # narrador / desconocido → voz del proyecto


def _wrap_wav(pcm: bytes, path: Path, rate=PCM_RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def pcm_seconds(pcm: bytes, rate=PCM_RATE) -> float:
    return len(pcm) / 2 / rate


def _single_speech_config(voice):
    return types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
        )
    )


def _multi_speech_config(pairs_voices):
    return types.SpeechConfig(
        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                types.SpeakerVoiceConfig(
                    speaker=name,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=v)
                    ),
                )
                for name, v in pairs_voices
            ]
        )
    )


def gen_voice(pid, scene_id, instruction="") -> dict:
    """Genera la locución de una escena con la voz del personaje que habla.
    instruction: indicación de mejora del usuario (botón 'reeditar voz': tono, ritmo…)."""
    p = db.get_project(pid)
    scene = db.get_scene(scene_id)
    text = (scene["dialogue"] or scene["visual"]).strip()
    if not text:
        return {}
    model_key = p["models"]["tts"]
    mid = config.real_model_id(model_key)
    loc = config.MODEL_REGISTRY[model_key]["location"]
    chars_by_name = {c["name"].strip().lower(): c for c in db.get_characters(pid)}
    emotion = scene["emotion"] or "natural"
    if instruction:
        emotion = f"{emotion} ({instruction})"

    pairs = _dialogue_parts(text)
    speakers = list(dict.fromkeys(n for n, _ in pairs))  # únicos, en orden

    if len(speakers) >= 2:
        # conversación: TTS multi-speaker (máx 2 voces)
        chosen = speakers[:2]
        speech = _multi_speech_config([(n, _voice_for(p, chars_by_name, n)) for n in chosen])
        contents = (f"Conversación en español con emoción {emotion}:\n"
                    + "\n".join(f"{n}: {t}" for n, t in pairs if n in chosen))
    else:
        speaker = scene.get("speaker") or (speakers[0] if speakers else "")
        voice = _voice_for(p, chars_by_name, speaker)
        spoken = " ".join(t for _, t in pairs) if pairs else text
        speech = _single_speech_config(voice)
        contents = f"Lee con emoción {emotion}, en español: {spoken}"

    def _call(cfg=speech, cont=contents):
        return vertex.client(loc).models.generate_content(
            model=mid,
            contents=cont,
            config=types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=cfg),
        )

    try:
        r = vertex.call_with_retry(_call)
    except Exception:
        if len(speakers) < 2:
            raise
        # fallback: si multi-speaker falla, todo con la voz del primero
        voice = _voice_for(p, chars_by_name, speakers[0])
        spoken = " ".join(t for _, t in pairs)
        r = vertex.call_with_retry(lambda: _call(
            _single_speech_config(voice), f"Lee con emoción {emotion}, en español: {spoken}"))
    pcm = b""
    for part in r.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            pcm += part.inline_data.data
    if not pcm:
        raise RuntimeError("TTS sin audio en la respuesta")

    rel = f"audio/voz_{scene['ord']:02d}.wav"
    out = db.project_dir(pid) / rel
    _wrap_wav(pcm, out)
    secs = pcm_seconds(pcm)

    usd = costs.token_cost(model_key, r.usage_metadata)
    costs.register(pid, model_key, f"voz escena {scene['ord'] + 1}", usd)
    db.add_asset(pid, scene_id, "voice", out, model=model_key, cost=usd)

    if p["audio_first"]:
        # la voz manda: duración de escena = voz + 0.5s de aire (mín 2s, máx 8s por clip Veo)
        db.update_scene(scene_id, duration_s=round(min(max(secs + 0.5, 2), 8), 1))
    elif secs + 0.3 > float(scene["duration_s"] or 0):
        # sin audio-first la escena manda… pero una locución NUNCA se corta: se alarga la escena
        db.update_scene(scene_id, duration_s=round(min(secs + 0.5, 8), 1))
    return {"path": rel, "seconds": secs}


def gen_music(pid, prompt_extra="") -> str:
    """Música de fondo con Lyria (endpoint predict). Falla con gracia: devuelve '' si no hay música."""
    p = db.get_project(pid)
    model_key = p["models"]["music"]
    mid = config.real_model_id(model_key)
    style = prompt_extra or f"Música instrumental de fondo para un vídeo sobre: {p['script'][:200]}"

    url = (f"https://us-central1-aiplatform.googleapis.com/v1/projects/{config.GCP_PROJECT}"
           f"/locations/us-central1/publishers/google/models/{mid}:predict")
    headers = {
        "Authorization": f"Bearer {vertex.current_token()}",
        "X-Goog-User-Project": config.GCP_PROJECT,
        "Content-Type": "application/json",
    }
    body = {"instances": [{"prompt": style}], "parameters": {}}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(f"Lyria HTTP {resp.status_code}: {resp.text[:200]}")
        pred = resp.json()["predictions"][0]
        b64 = pred.get("bytesBase64Encoded") or pred.get("audioContent") or ""
        if not b64:
            raise RuntimeError(f"Lyria sin audio: claves {list(pred.keys())}")
        data = base64.b64decode(b64)
        rel = "audio/musica.wav"
        out = db.project_dir(pid) / rel
        out.write_bytes(data)
        usd = costs.music_cost(model_key)
        costs.register(pid, model_key, "música", usd)
        db.add_asset(pid, None, "music", out, model=model_key, cost=usd)
        return rel
    except Exception as e:
        db.set_status(pid, msg=f"Música no disponible ({vertex.scrub(e)[:120]}), sigo sin BSO")
        return ""
