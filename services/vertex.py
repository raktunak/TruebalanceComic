"""Cliente google.genai para Vertex AI.

- Un cliente cacheado por location (global / us-central1).
- Header X-Goog-User-Project (sin él, models.list/get dan 403 engañoso).
- Token: se auto-renueva con gcloud cada ~50 min o ante un 401 (los access
  tokens de Google caducan a la hora). NUNCA se loguea ni se imprime.
"""
import os
import subprocess
import time

from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials

import config

_clients: dict[str, genai.Client] = {}
_tok = ""
_tok_ts = 0.0


class TokenError(RuntimeError):
    """No hay forma de conseguir un token válido (¿sesión de gcloud cerrada?)."""


def _gcloud_token() -> str:
    r = subprocess.run(
        f"gcloud auth print-access-token --account={config.GCLOUD_ACCOUNT}",
        capture_output=True, text=True, shell=True, timeout=60,
    )
    tok = (r.stdout or "").strip()
    if r.returncode != 0 or not tok:
        raise TokenError(
            "No pude renovar el token con gcloud. Ejecuta a mano: "
            f"gcloud auth login {config.GCLOUD_ACCOUNT}"
        )
    return tok


def _token(force: bool = False) -> str:
    """Token vigente; se renueva solo (proactivo a los 50 min, o forzado tras un 401)."""
    global _tok, _tok_ts
    if not _tok:
        _tok = os.environ.get("VXTOKEN", "").strip()
        _tok_ts = time.time() if _tok else 0.0
    if force or not _tok or time.time() - _tok_ts > 50 * 60:
        _tok = _gcloud_token()
        _tok_ts = time.time()
        os.environ["VXTOKEN"] = _tok  # scrub() y audio.gen_music leen de aquí
        _clients.clear()  # los clientes cacheados llevan credenciales viejas
    return _tok


def current_token() -> str:
    """Para llamadas REST directas (p.ej. Lyria). Siempre devuelve token vigente."""
    return _token()


def scrub(err) -> str:
    """Mensaje de error sin rastro del token."""
    msg = str(err)
    tok = os.environ.get("VXTOKEN", "").strip()
    if tok:
        msg = msg.replace(tok, "[TOKEN]")
    return msg[:500]


def client(location: str) -> genai.Client:
    if location not in _clients:
        creds = Credentials(token=_token())
        _clients[location] = genai.Client(
            vertexai=True,
            project=config.GCP_PROJECT,
            location=location,
            credentials=creds,
            http_options=types.HttpOptions(
                headers={"X-Goog-User-Project": config.GCP_PROJECT}
            ),
        )
    return _clients[location]


def call_with_retry(fn, tries=6, wait=5):
    """Reintenta errores transitorios. 429 espera largo; 401 renueva token y reintenta."""
    last = None
    refreshed = False
    for i in range(tries):
        try:
            return fn()
        except TokenError:
            raise
        except Exception as e:  # noqa: BLE001
            msg = scrub(e)
            if "401" in msg or "UNAUTHENTICATED" in msg:
                if refreshed:
                    raise TokenError("Vertex rechaza incluso el token recién renovado (revisa la cuenta gcloud)") from None
                _token(force=True)
                refreshed = True
                continue
            last = RuntimeError(msg)
            rate_limited = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            transitory = rate_limited or any(k in msg for k in ("500", "503", "UNAVAILABLE", "INTERNAL", "DEADLINE"))
            if not transitory or i == tries - 1:
                raise last
            time.sleep(20 * (i + 1) if rate_limited else wait * (i + 1))
    raise last
