"""Client minimo per un ComfyUI locale: canzoni (ACE-Step 1.5) e suoni (Stable Audio).

medit non porta modelli di diffusione dentro di se': sono giga di pesi e una
GPU. Se sulla macchina gira ComfyUI (di solito ``127.0.0.1:8188``) lo usa via
API HTTP. Senza ComfyUI, o senza il modello, gli strumenti generativi dicono
esattamente cosa scaricare e dove; il resto dell'editor funziona uguale.

I workflow sono quelli dei template ufficiali di ComfyUI
(``audio_ace_step_1_5_checkpoint``, ``audio_stable_audio_example``) in formato
API. I parametri del codificatore di ACE-Step si allineano a ``/object_info``:
un ComfyUI piu' nuovo con un campo in piu' prende il suo default, uno con un
campo in meno non riceve quello che non conosce.

Configurazione in ``~/.medit/comfy.json`` (``url``, ``song_checkpoint``,
``audio_checkpoint``) oppure ``MEDIT_COMFY_URL``.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8188"

# cosa scaricare, e dove, per ogni funzione (dai template ufficiali)
MODELLI = {
    "song": {"file": "ace_step_1.5_turbo_aio.safetensors", "folder": "checkpoints", "size": "~10 GB",
             "url": "https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/resolve/main/checkpoints/"
                    "ace_step_1.5_turbo_aio.safetensors"},
    "audio": {"file": "stable-audio-open-1.0.safetensors", "folder": "checkpoints", "size": "~4.8 GB",
              "url": "https://huggingface.co/Comfy-Org/stable-audio-open-1.0_repackaged/resolve/main/"
                     "stable-audio-open-1.0.safetensors"},
    "audio_text_encoder": {"file": "t5-base.safetensors", "folder": "text_encoders", "size": "~0.9 GB",
                           "url": "https://huggingface.co/ComfyUI-Wiki/t5-base/resolve/main/t5-base.safetensors"},
}


class ComfyError(RuntimeError):
    pass


def _cfg_file() -> Path:
    base = Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "comfy.json"


def config() -> dict:
    try:
        cfg = json.loads(_cfg_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg["url"] = (os.environ.get("MEDIT_COMFY_URL") or cfg.get("url") or DEFAULT_URL).rstrip("/")
    return cfg


def set_config(**kw: Any) -> dict:
    cfg = config()
    for k, v in kw.items():
        if v is None:
            continue
        if v == "":
            cfg.pop(k, None)
        else:
            cfg[k] = v
    f = _cfg_file()
    tmp = f.with_name("~" + f.name)
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    return cfg


def _get(path: str, timeout: float = 10.0) -> Any:
    url = config()["url"] + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ComfyError(f"ComfyUI not reachable at {config()['url']}: {exc}") from exc
    try:
        return json.loads(data)
    except ValueError:
        return data


def _post(path: str, body: bytes, timeout: float = 30.0) -> Any:
    url = config()["url"] + path
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        dettaglio = exc.read().decode("utf-8", "replace")[:800]
        raise ComfyError(f"ComfyUI refused the job ({exc.code}): {dettaglio}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ComfyError(f"ComfyUI not reachable at {config()['url']}: {exc}") from exc


def available(timeout: float = 1.5) -> bool:
    try:
        _get("/system_stats", timeout=timeout)
        return True
    except ComfyError:
        return False


def _spec(node: str) -> dict:
    info = _get(f"/object_info/{urllib.parse.quote(node)}")
    if not isinstance(info, dict) or node not in info:
        raise ComfyError(f"this ComfyUI has no node {node!r}: update ComfyUI (the audio nodes are built in)")
    return info[node].get("input") or {}


def _choices(node: str, field: str) -> list[str]:
    try:
        spec = (_spec(node).get("required") or {})[field]
    except (KeyError, ComfyError):
        return []
    first = spec[0] if spec else []
    if isinstance(first, list):
        return first
    if len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options") or [])
    return []


def checkpoints() -> list[str]:
    return _choices("CheckpointLoaderSimple", "ckpt_name")


def _scegli(ck: list[str], chiave: str, parole: tuple[str, ...]) -> str | None:
    voluto = config().get(chiave)
    if voluto and voluto in ck:
        return voluto
    for c in ck:
        low = c.lower().replace("-", "_")
        if all(p in low for p in parole):
            return c
    return None


def song_checkpoint(ck: list[str] | None = None) -> str | None:
    ck = checkpoints() if ck is None else ck
    return _scegli(ck, "song_checkpoint", ("ace", "1.5")) or _scegli(ck, "song_checkpoint", ("ace", "step"))


def audio_checkpoint(ck: list[str] | None = None) -> str | None:
    ck = checkpoints() if ck is None else ck
    return _scegli(ck, "audio_checkpoint", ("stable", "audio"))


def _manca(cosa: str) -> str:
    m = MODELLI[cosa]
    return f"download {m['file']} ({m['size']}) into ComfyUI models/{m['folder']}: {m['url']}"


def status() -> dict:
    cfg = config()
    if not available():
        return {"ok": False, "url": cfg["url"],
                "hint": "start ComfyUI (default 127.0.0.1:8188) or set its address with comfy_settings"}
    ck = checkpoints()
    song, audio = song_checkpoint(ck), audio_checkpoint(ck)
    t5 = "t5-base.safetensors" in _choices("CLIPLoader", "clip_name")
    out = {"ok": True, "url": cfg["url"], "song_model": song, "audio_model": audio if t5 else None}
    if not song:
        out["song_hint"] = _manca("song")
    if not audio:
        out["audio_hint"] = _manca("audio")
    elif not t5:
        out["audio_hint"] = _manca("audio_text_encoder")
    return out


# --------------------------------------------------------------------------
# esecuzione
# --------------------------------------------------------------------------


def run(workflow: dict, timeout: float = 1800.0) -> list[bytes]:
    """Mette in coda un workflow (formato API) e restituisce i file audio salvati (byte)."""
    res = _post("/prompt", json.dumps({"prompt": workflow, "client_id": "medit"}).encode())
    pid = res.get("prompt_id")
    if not pid:
        raise ComfyError(f"ComfyUI did not accept the workflow: {res}")
    t0 = time.monotonic()
    while True:
        hist = _get(f"/history/{pid}")
        if isinstance(hist, dict) and pid in hist:
            item = hist[pid]
            st = item.get("status") or {}
            if st.get("status_str") == "error":
                raise ComfyError(f"ComfyUI job failed: {json.dumps(st.get('messages'))[:800]}")
            files = []
            for out in (item.get("outputs") or {}).values():
                for a in out.get("audio") or []:
                    q = urllib.parse.urlencode({"filename": a["filename"], "subfolder": a.get("subfolder", ""),
                                                "type": a.get("type", "output")})
                    data = _get(f"/view?{q}", timeout=120)
                    if isinstance(data, (bytes, bytearray)):
                        files.append(bytes(data))
            if files:
                return files
            if st.get("completed"):
                raise ComfyError("ComfyUI finished without producing audio")
        if time.monotonic() - t0 > timeout:
            raise ComfyError("ComfyUI took too long (timeout)")
        time.sleep(1.0)


def seed(s: int | None) -> int:
    return int(s) if s is not None and s >= 0 else random.randint(0, 2 ** 31 - 1)


def _allinea(node: str, valori: dict) -> dict:
    """Ingressi del nodo come li vuole *questo* ComfyUI: default dove non diciamo niente,
    via quello che non conosce."""
    try:
        spec = _spec(node)
    except ComfyError:
        return valori
    out = {}
    for gruppo in ("required", "optional"):
        for nome, s in (spec.get(gruppo) or {}).items():
            if nome in valori:
                out[nome] = valori[nome]
            elif isinstance(s, (list, tuple)) and len(s) > 1 and isinstance(s[1], dict) and "default" in s[1]:
                out[nome] = s[1]["default"]
    for k, v in valori.items():
        if isinstance(v, list):   # collegamenti ad altri nodi: sempre
            out[k] = v
    return out


def workflow_song(ckpt: str, tags: str, lyrics: str, seconds: float, bpm: float, keyscale: str,
                  time_sig: int, language: str, s: int, steps: int = 8) -> dict:
    """ACE-Step 1.5 (turbo, checkpoint unico): tag di stile + testo -> canzone con voce."""
    enc = _allinea("TextEncodeAceStepAudio1.5", {
        "clip": ["1", 1], "tags": tags, "lyrics": lyrics, "seed": s, "bpm": int(round(bpm)),
        "duration": float(seconds), "timesignature": str(time_sig), "language": language,
        "keyscale": keyscale, "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85,
        "top_p": 0.9, "top_k": 0, "min_p": 0.0})
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "3": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": enc},
        "4": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["3", 0]}},
        "5": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["3", 0], "negative": ["4", 0],
                                                   "latent_image": ["5", 0], "seed": s, "steps": steps, "cfg": 1.0,
                                                   "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudio", "inputs": {"audio": ["7", 0], "filename_prefix": "medit/song"}},
    }


def workflow_audio(ckpt: str, prompt: str, negative: str, seconds: float, s: int, steps: int = 50) -> dict:
    """Stable Audio Open 1.0: loop, strumenti, effetti sonori (fino a ~47 s)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5-base.safetensors", "type": "stable_audio",
                                                     "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "5": {"class_type": "EmptyLatentAudio", "inputs": {"seconds": float(seconds), "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                                                   "latent_image": ["5", 0], "seed": s, "steps": steps, "cfg": 4.98,
                                                   "sampler_name": "dpmpp_3m_sde_gpu", "scheduler": "exponential",
                                                   "denoise": 1.0}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudio", "inputs": {"audio": ["7", 0], "filename_prefix": "medit/sound"}},
    }


def generate_song(tags: str, lyrics: str, seconds: float, bpm: float, keyscale: str, time_sig: int = 4,
                  language: str = "en", s: int | None = None) -> bytes:
    ck = song_checkpoint()
    if not ck:
        raise ComfyError("no ACE-Step model in ComfyUI: " + _manca("song"))
    wf = workflow_song(ck, tags, lyrics, seconds, bpm, keyscale, time_sig, language, seed(s))
    return run(wf)[0]


def generate_audio(prompt: str, seconds: float, negative: str = "low quality, noise, distortion",
                   s: int | None = None) -> bytes:
    ck = audio_checkpoint()
    if not ck:
        raise ComfyError("no Stable Audio model in ComfyUI: " + _manca("audio"))
    return run(workflow_audio(ck, prompt, negative, min(float(seconds), 47.0), seed(s)))[0]
