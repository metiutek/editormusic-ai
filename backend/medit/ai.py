"""Cosa c'e' di IA su questa macchina e chi fa cosa.

- canzone con voce da stile + testo: ComfyUI con ACE-Step 1.5, oppure
  ElevenLabs Music (chiave dell'utente);
- loop, strumenti, effetti sonori: ComfyUI con Stable Audio Open, oppure
  Replicate / ElevenLabs;
- stem: Demucs; voce dell'utente: Applio; audio -> MIDI: sempre (numpy).

``backend="auto"`` usa ComfyUI se il modello c'e', altrimenti un servizio in
rete solo se l'utente l'ha reso predefinito: niente spese a sorpresa.
"""

from __future__ import annotations

from . import cloud, comfy, separa, uvr, voce

BACKENDS = ("auto", "comfyui", "elevenlabs", "replicate")


class AIError(RuntimeError):
    pass


def status(check_comfy: bool = True) -> dict:
    c = comfy.status() if check_comfy else {"ok": None, "url": comfy.config()["url"]}
    cl = cloud.stato()
    pronti = [k for k, v in cl["services"].items() if v["ready"]]
    return {
        "song": {"comfyui": bool(c.get("song_model")), "cloud": [k for k in pronti if cl["services"][k]["vocals"]]},
        "sound": {"comfyui": bool(c.get("audio_model")), "cloud": pronti},
        "comfyui": c, "cloud": cl, "stems": separa.stato(), "uvr": uvr.stato(), "voice": voce.stato(),
        "applio_ui": voce.ui_stato(),
        "audio_to_midi": {"ok": True, "modes": ["melody", "drums"]},
    }


def scegli(backend: str, cosa: str) -> str:
    """Il motore da usare per ``cosa`` (song | sound)."""
    if backend not in BACKENDS:
        raise AIError(f"backend must be one of {', '.join(BACKENDS)}")
    if backend != "auto":
        if backend in cloud.SERVIZI and not cloud.chiave(backend):
            raise AIError(f"no {cloud.SERVIZI[backend]['nome']} key: add it in AI services (stays on this computer)")
        return backend
    if comfy.available():
        st = comfy.status()
        if st.get("song_model" if cosa == "song" else "audio_model"):
            return "comfyui"
    d = cloud.predefinito()
    if d:
        return d
    st = comfy.status()
    motivi = []
    if not st["ok"]:
        motivi.append(f"ComfyUI is not running at {st['url']}")
    else:
        motivi.append(st.get("song_hint" if cosa == "song" else "audio_hint") or "")
    motivi.append("or add an ElevenLabs / Replicate key in AI services and make it the default "
                  "(or pass backend='elevenlabs' / 'replicate' explicitly)")
    raise AIError("no AI engine available: " + "; ".join(m for m in motivi if m))
