"""Generazione musicale in rete, con la chiave dell'utente.

- **ElevenLabs Music** (``POST /v1/music``): canzoni anche con voce, da un
  prompt (il testo va nel prompt), fino a 10 minuti.
- **Replicate**: qualunque modello audio pubblicato li', di default
  ``meta/musicgen`` (strumentale). ``model`` e ``inputs`` si cambiano in
  configurazione.

Le chiavi stanno in ``~/.medit/ai_api.json`` (o ``ELEVENLABS_API_KEY`` /
``REPLICATE_API_TOKEN``), solo su questa macchina, mai nel documento e mai
attraverso gli strumenti MCP. Un servizio a pagamento si usa da solo
(``backend="auto"``) solo se l'utente l'ha reso predefinito. Tutto l'HTTP
passa da ``_http``: nei test e' sempre sostituita.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SERVIZI = {
    "elevenlabs": {"nome": "ElevenLabs Music", "env": "ELEVENLABS_API_KEY", "voce": True,
                   "nota": "Songs with vocals from a prompt (lyrics inside the prompt), 3 s to 10 min. Paid per use."},
    "replicate": {"nome": "Replicate", "env": "REPLICATE_API_TOKEN", "voce": False,
                  "nota": "Any audio model on replicate.com; default meta/musicgen (instrumental). Paid per use."},
}
REPLICATE_DEFAULT = {"model": "meta/musicgen",
                     "inputs": {"model_version": "stereo-melody-large", "output_format": "wav"}}


class CloudError(RuntimeError):
    pass


def _file() -> Path:
    base = Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "ai_api.json"


def carica() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("services", {})
    d.setdefault("default", "")
    return d


def _scrivi(d: dict) -> None:
    f = _file()
    tmp = f.with_name("~" + f.name)
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def chiave(servizio: str) -> str:
    s = carica()["services"].get(servizio) or {}
    return s.get("key") or os.environ.get(SERVIZI[servizio]["env"], "")


def stato() -> dict:
    d = carica()
    out = {}
    for k, v in SERVIZI.items():
        c = chiave(k)
        out[k] = {"name": v["nome"], "ready": bool(c), "key": (c[:4] + "…" + c[-3:]) if c else "", "note": v["nota"],
                  "vocals": v["voce"]}
        if k == "replicate":
            out[k]["model"] = (d["services"].get(k) or {}).get("model") or REPLICATE_DEFAULT["model"]
    return {"services": out, "default": d["default"]}


def imposta(servizio: str, key: str | None = None, model: str | None = None, inputs: dict | None = None,
            default: bool | None = None) -> dict:
    if servizio not in SERVIZI:
        raise CloudError(f"unknown service {servizio!r}; available: {', '.join(SERVIZI)}")
    d = carica()
    s = d["services"].setdefault(servizio, {})
    if key is not None:
        if key.strip():
            s["key"] = key.strip()
        else:
            s.pop("key", None)
    if model is not None:
        s["model"] = model.strip()
    if inputs is not None:
        s["inputs"] = inputs
    if default is True:
        d["default"] = servizio
    elif default is False and d["default"] == servizio:
        d["default"] = ""
    _scrivi(d)
    return stato()


def predefinito() -> str | None:
    d = carica()["default"]
    return d if d in SERVIZI and chiave(d) else None


# --------------------------------------------------------------------------
# HTTP (sostituita nei test)
# --------------------------------------------------------------------------


def _http(method: str, url: str, headers: dict, body: bytes | None = None, timeout: float = 600.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        testo = exc.read().decode("utf-8", "replace")[:600]
        raise CloudError(f"{url.split('/')[2]} refused the request ({exc.code}): {testo}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise CloudError(f"cannot reach {url.split('/')[2]}: {exc}") from exc


# --------------------------------------------------------------------------
# generazione
# --------------------------------------------------------------------------


def _estensione(ctype: str, default: str = ".mp3") -> str:
    ctype = (ctype or "").lower()
    for k, e in (("wav", ".wav"), ("flac", ".flac"), ("ogg", ".ogg"), ("mpeg", ".mp3"), ("mp3", ".mp3")):
        if k in ctype:
            return e
    return default


def elevenlabs(prompt: str, seconds: float | None) -> tuple[bytes, str]:
    k = chiave("elevenlabs")
    if not k:
        raise CloudError("no ElevenLabs key: add it in AI services (stays on this computer)")
    body: dict[str, Any] = {"prompt": prompt[:4100]}
    if seconds:
        body["music_length_ms"] = int(min(600000, max(3000, seconds * 1000)))
    data, ctype = _http("POST", "https://api.elevenlabs.io/v1/music",
                        {"xi-api-key": k, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                        json.dumps(body).encode())
    if ctype.startswith("application/json"):
        raise CloudError(f"ElevenLabs answered without audio: {data[:300].decode('utf-8', 'replace')}")
    return data, _estensione(ctype)


def replicate(prompt: str, seconds: float | None) -> tuple[bytes, str]:
    k = chiave("replicate")
    if not k:
        raise CloudError("no Replicate token: add it in AI services (stays on this computer)")
    conf = carica()["services"].get("replicate") or {}
    model = conf.get("model") or REPLICATE_DEFAULT["model"]
    inputs = dict(conf.get("inputs") or REPLICATE_DEFAULT["inputs"])
    inputs["prompt"] = prompt
    if seconds:
        inputs.setdefault("duration", int(round(seconds)))
    h = {"Authorization": f"Bearer {k}", "Content-Type": "application/json", "Prefer": "wait"}
    data, _ = _http("POST", f"https://api.replicate.com/v1/models/{model}/predictions", h,
                    json.dumps({"input": inputs}).encode())
    pred = json.loads(data)
    t0 = time.monotonic()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.monotonic() - t0 > 900:
            raise CloudError("Replicate took too long")
        time.sleep(2)
        data, _ = _http("GET", pred["urls"]["get"], {"Authorization": f"Bearer {k}"})
        pred = json.loads(data)
    if pred["status"] != "succeeded":
        raise CloudError(f"Replicate: {pred.get('error') or pred['status']}")
    out = pred.get("output")
    url = out[0] if isinstance(out, list) else out.get("audio") if isinstance(out, dict) else out
    if not isinstance(url, str):
        raise CloudError(f"Replicate returned no audio file: {str(out)[:200]}")
    audio, ctype = _http("GET", url, {})
    return audio, _estensione(ctype, Path(url.split("?")[0]).suffix or ".wav")


def genera(servizio: str, prompt: str, seconds: float | None = None) -> tuple[bytes, str]:
    if servizio == "elevenlabs":
        return elevenlabs(prompt, seconds)
    if servizio == "replicate":
        return replicate(prompt, seconds)
    raise CloudError(f"unknown service {servizio!r}; available: {', '.join(SERVIZI)}")
