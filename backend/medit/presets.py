"""Suoni e catene gia' tarati, piu' quelli salvati dall'utente.

Un *suono* e' uno strumento (tipo + parametri). Una *catena* e' una lista di
effetti (come i look di pedit). Applicarli copia i parametri nel documento:
il documento suona uguale anche se qui i valori cambiano in futuro.

I preset dell'utente stanno in ``~/.medit/presets.json`` (``{"sounds": {},
"chains": {}}``) e compaiono insieme a quelli inclusi.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import effects as fx
from . import synth

SOUNDS: dict[str, dict] = {
    # ---- tastiere
    "piano": {"type": "fm", "category": "keys", "desc": "bright acoustic-ish piano",
              "params": {"ratio": 1.0, "index": 1.6, "index_decay": 0.35, "index_sustain": 0.05, "ratio2": 4.0,
                         "index2": 0.6, "decay2": 0.03, "attack": 0.002, "decay": 1.8, "sustain": 0.0,
                         "release": 0.35, "detune": 3.0, "vel_to_index": 0.8}},
    "electric piano": {"type": "fm", "category": "keys", "desc": "Rhodes-style e-piano with a bell tine",
                       "params": {"ratio": 1.0, "index": 1.2, "index_decay": 0.6, "index_sustain": 0.15,
                                  "ratio2": 14.0, "index2": 1.4, "decay2": 0.04, "attack": 0.002, "decay": 2.2,
                                  "sustain": 0.25, "release": 0.4, "detune": 5.0, "tremolo": 0.15}},
    "lofi keys": {"type": "fm", "category": "keys", "desc": "soft, dark keys for lo-fi and chill",
                  "params": {"ratio": 1.0, "index": 0.8, "index_decay": 0.5, "index_sustain": 0.1, "attack": 0.004,
                             "decay": 1.6, "sustain": 0.2, "release": 0.5, "detune": 8.0, "tremolo": 0.1, "gain_db": 1.0}},
    "organ": {"type": "synth", "category": "keys", "desc": "drawbar-ish organ",
              "params": {"osc1": "sine", "osc2": "sine", "osc2_semi": 12.0, "osc2_detune": 2.0, "osc_mix": 0.45,
                         "sub": 0.5, "attack": 0.004, "decay": 0.1, "sustain": 1.0, "release": 0.06,
                         "filter": "lowpass", "cutoff": 6000.0, "vibrato_depth": 8.0, "vibrato_rate": 6.5}},
    "bell": {"type": "fm", "category": "keys", "desc": "glassy FM bell",
             "params": {"ratio": 3.5, "index": 3.0, "index_decay": 1.0, "index_sustain": 0.1, "attack": 0.001,
                        "decay": 3.0, "sustain": 0.0, "release": 1.5, "detune": 6.0}},
    "marimba": {"type": "fm", "category": "keys", "desc": "wooden mallet",
                "params": {"ratio": 4.0, "index": 1.5, "index_decay": 0.05, "index_sustain": 0.0, "attack": 0.001,
                           "decay": 0.5, "sustain": 0.0, "release": 0.2, "detune": 0.0}},
    # ---- pad e archi
    "warm pad": {"type": "synth", "category": "pad", "desc": "slow, warm analog pad",
                 "params": {"osc1": "saw", "osc2": "saw", "osc2_detune": 9.0, "unison": 3, "unison_detune": 18.0,
                            "spread": 0.8, "attack": 0.6, "decay": 1.0, "sustain": 0.8, "release": 1.2,
                            "cutoff": 1400.0, "resonance": 0.8, "keytrack": 0.3, "gain_db": -2.0}},
    "airy pad": {"type": "synth", "category": "pad", "desc": "bright, airy, wide pad",
                 "params": {"osc1": "saw", "osc2": "triangle", "osc2_semi": 12.0, "unison": 5, "unison_detune": 25.0,
                            "spread": 1.0, "attack": 0.8, "decay": 1.5, "sustain": 0.7, "release": 2.0,
                            "cutoff": 5000.0, "noise": 0.05, "gain_db": -4.0}},
    "strings": {"type": "synth", "category": "pad", "desc": "string-ensemble pad",
                "params": {"osc1": "saw", "osc2": "saw", "osc2_detune": 6.0, "unison": 4, "unison_detune": 12.0,
                           "spread": 0.9, "attack": 0.25, "decay": 0.5, "sustain": 0.9, "release": 0.6,
                           "cutoff": 3200.0, "vibrato_depth": 10.0, "vibrato_rate": 5.2, "gain_db": -3.0}},
    "choir pad": {"type": "synth", "category": "pad", "desc": "vowel-like 'aah' pad",
                  "params": {"osc1": "saw", "osc2": "square", "osc_mix": 0.3, "unison": 3, "unison_detune": 10.0,
                             "attack": 0.5, "sustain": 0.85, "release": 1.0, "filter": "bandpass", "cutoff": 900.0,
                             "resonance": 1.4, "keytrack": 0.6, "vibrato_depth": 12.0, "gain_db": 3.0}},
    # ---- lead
    "supersaw lead": {"type": "synth", "category": "lead", "desc": "huge trance/EDM supersaw",
                      "params": {"osc1": "saw", "osc2": "saw", "osc2_detune": 12.0, "unison": 7, "unison_detune": 30.0,
                                 "spread": 1.0, "attack": 0.005, "decay": 0.4, "sustain": 0.8, "release": 0.3,
                                 "cutoff": 7000.0, "gain_db": -4.0}},
    "square lead": {"type": "synth", "category": "lead", "desc": "hollow chiptune-ish square",
                    "params": {"osc1": "square", "osc2": "square", "osc2_semi": 12.0, "osc_mix": 0.25, "pw": 0.4,
                               "attack": 0.003, "decay": 0.2, "sustain": 0.8, "release": 0.12, "cutoff": 5000.0,
                               "vibrato_depth": 15.0, "glide": 0.04}},
    "soft lead": {"type": "synth", "category": "lead", "desc": "round, flute-like lead",
                  "params": {"osc1": "triangle", "osc2": "sine", "osc2_semi": 12.0, "osc_mix": 0.3, "attack": 0.03,
                             "decay": 0.3, "sustain": 0.8, "release": 0.25, "cutoff": 3500.0, "noise": 0.03,
                             "vibrato_depth": 18.0, "vibrato_rate": 5.5}},
    "brass": {"type": "synth", "category": "lead", "desc": "synth brass with a filter swell",
              "params": {"osc1": "saw", "osc2": "saw", "osc2_detune": 8.0, "unison": 2, "attack": 0.05, "decay": 0.4,
                         "sustain": 0.8, "release": 0.25, "cutoff": 700.0, "filter_env": 2.5, "f_attack": 0.08,
                         "f_decay": 0.5, "f_sustain": 0.5, "resonance": 1.0}},
    # ---- plucks
    "pluck": {"type": "synth", "category": "pluck", "desc": "short EDM/pop pluck",
              "params": {"osc1": "saw", "osc2": "square", "osc_mix": 0.3, "unison": 3, "unison_detune": 14.0,
                         "attack": 0.002, "decay": 0.25, "sustain": 0.0, "release": 0.2, "cutoff": 500.0,
                         "filter_env": 4.0, "f_decay": 0.18, "resonance": 1.2}},
    "acoustic guitar": {"type": "pluck", "category": "guitar", "desc": "steel-string acoustic",
                        "params": {"brightness": 0.75, "decay": 3.5, "pick_position": 0.15, "body": 0.6, "width": 0.4}},
    "nylon guitar": {"type": "pluck", "category": "guitar", "desc": "classical nylon guitar",
                     "params": {"brightness": 0.45, "decay": 2.5, "pick_position": 0.3, "body": 0.7, "width": 0.3}},
    "muted guitar": {"type": "pluck", "category": "guitar", "desc": "palm-muted funk guitar",
                     "params": {"brightness": 0.7, "decay": 1.5, "pick_position": 0.12, "body": 0.3, "mute": 0.85,
                                "release": 0.03}},
    "harp": {"type": "pluck", "category": "guitar", "desc": "concert harp",
             "params": {"brightness": 0.5, "decay": 4.0, "pick_position": 0.4, "body": 0.2, "width": 0.6, "release": 1.0}},
    # ---- bassi
    "sub bass": {"type": "synth", "category": "bass", "desc": "pure sine sub",
                 "params": {"osc1": "sine", "osc_mix": 0.0, "attack": 0.005, "decay": 0.2, "sustain": 1.0,
                            "release": 0.1, "filter": "none", "gain_db": 4.0}},
    "808": {"type": "synth", "category": "bass", "desc": "trap 808 bass with a little drive and glide",
            "params": {"osc1": "sine", "osc_mix": 0.0, "attack": 0.002, "decay": 2.0, "sustain": 0.4, "release": 0.25,
                       "filter": "none", "drive": 0.35, "glide": 0.06, "gain_db": 5.0}},
    "saw bass": {"type": "synth", "category": "bass", "desc": "punchy filtered saw bass",
                 "params": {"osc1": "saw", "osc2": "square", "osc2_semi": -12.0, "osc_mix": 0.4, "attack": 0.003,
                            "decay": 0.3, "sustain": 0.7, "release": 0.08, "cutoff": 600.0, "filter_env": 2.0,
                            "f_decay": 0.15, "resonance": 1.0, "sub": 0.3, "gain_db": 1.0}},
    "reese bass": {"type": "synth", "category": "bass", "desc": "detuned DnB reese",
                   "params": {"osc1": "saw", "osc2": "saw", "osc2_detune": 22.0, "unison": 2, "unison_detune": 10.0,
                              "spread": 0.3, "attack": 0.01, "sustain": 1.0, "release": 0.1, "cutoff": 900.0,
                              "drive": 0.3, "sub": 0.4}},
    "acid bass": {"type": "synth", "category": "bass", "desc": "303-style squelchy acid",
                  "params": {"osc1": "saw", "osc_mix": 0.0, "attack": 0.002, "decay": 0.2, "sustain": 0.6,
                             "release": 0.05, "cutoff": 350.0, "filter_env": 3.5, "f_decay": 0.12,
                             "resonance": 8.0, "drive": 0.3, "glide": 0.05}},
    "finger bass": {"type": "pluck", "category": "bass", "desc": "electric finger bass",
                    "params": {"brightness": 0.35, "decay": 2.0, "pick_position": 0.25, "body": 0.2, "width": 0.0,
                               "release": 0.05, "gain_db": 4.0}},
    "fm bass": {"type": "fm", "category": "bass", "desc": "growly FM bass",
                "params": {"ratio": 1.0, "index": 3.0, "index_decay": 0.15, "index_sustain": 0.3, "attack": 0.002,
                           "decay": 0.4, "sustain": 0.7, "release": 0.08, "detune": 0.0, "gain_db": 2.0}},
    # ---- batterie
    "acoustic kit": {"type": "drums", "category": "drums", "desc": "natural-ish kit",
                     "params": {"kick_freq": 58.0, "kick_start": 140.0, "kick_decay": 0.35, "kick_click": 0.5,
                                "snare_tone": 200.0, "snare_decay": 0.22, "snare_noise": 0.75, "hat_tone": 0.5,
                                "cymbal_decay": 2.0}},
    "808 kit": {"type": "drums", "category": "drums", "desc": "classic TR-808",
                "params": {"kick_freq": 48.0, "kick_start": 120.0, "kick_decay": 0.9, "kick_click": 0.15,
                           "kick_drive": 0.1, "snare_tone": 230.0, "snare_decay": 0.15, "snare_noise": 0.55,
                           "hat_decay": 0.04, "hat_open_decay": 0.3, "hat_tone": 0.7}},
    "trap kit": {"type": "drums", "category": "drums", "desc": "hard trap: tight kick, crisp clap, sharp hats",
                 "params": {"kick_freq": 50.0, "kick_start": 200.0, "kick_decay": 0.4, "kick_click": 0.6,
                            "kick_drive": 0.5, "snare_tone": 210.0, "snare_decay": 0.16, "clap_decay": 0.25,
                            "hat_decay": 0.03, "hat_tone": 0.9, "gain_db": 1.0}},
    "electro kit": {"type": "drums", "category": "drums", "desc": "punchy house/techno kit",
                    "params": {"kick_freq": 50.0, "kick_start": 180.0, "kick_decay": 0.45, "kick_click": 0.5,
                               "kick_drive": 0.4, "snare_tone": 180.0, "snare_noise": 0.8, "clap_decay": 0.22,
                               "hat_decay": 0.045, "hat_open_decay": 0.25, "hat_tone": 0.8}},
    "lofi kit": {"type": "drums", "category": "drums", "desc": "dusty lo-fi kit",
                 "params": {"kick_freq": 55.0, "kick_start": 110.0, "kick_decay": 0.35, "kick_click": 0.2,
                            "snare_tone": 170.0, "snare_decay": 0.2, "snare_noise": 0.6, "hat_tone": 0.3,
                            "crush": 0.35, "gain_db": -1.0}},
}


# Livelli tarati: ogni suono, con una parte tipica del suo ruolo a velocity ~100,
# suona a una loudness di riferimento (batteria -19 LUFS, bassi -21, lead -22,
# tastiere/chitarre/pluck -23, pad -25). Cosi' una canzone nuova parte gia'
# bilanciata e con margine prima del master. Rifatta con scripts/calibra_suoni.py.
_CALIBRAZIONE = {
    'piano': -3.7,
    'electric piano': -4.9,
    'lofi keys': -3.5,
    'organ': -13.4,
    'bell': -8.6,
    'marimba': -3.2,
    'warm pad': -9.7,
    'airy pad': -9.5,
    'strings': -11.1,
    'choir pad': -4.9,
    'supersaw lead': -4.4,
    'square lead': -9.5,
    'soft lead': -4.7,
    'brass': -4.1,
    'pluck': -1.7,
    'acoustic guitar': -9.8,
    'nylon guitar': -7.4,
    'muted guitar': -4.5,
    'harp': -7.1,
    'sub bass': -6.5,
    '808': -7.7,
    'saw bass': -0.2,
    'reese bass': -5.9,
    'acid bass': -6.2,
    'finger bass': -3.8,
    'fm bass': -3.1,
    'acoustic kit': -4.9,
    '808 kit': -5.7,
    'trap kit': -6.9,
    'electro kit': -6.8,
    'lofi kit': -4.1,
}
for _nome, _g in _CALIBRAZIONE.items():
    SOUNDS[_nome]["params"]["gain_db"] = _g


CHAINS: dict[str, dict] = {
    "vocal": {"desc": "clean modern vocal: cut lows, presence, de-ess, compress",
              "effects": [{"type": "eq", "params": {"low_cut": 90.0, "mid_gain": -2.0, "mid_freq": 300.0,
                                                    "mid2_gain": 2.5, "mid2_freq": 3500.0, "high_gain": 2.0}},
                          {"type": "deesser", "params": {}},
                          {"type": "compressor", "params": {"threshold_db": -20.0, "ratio": 4.0, "attack_ms": 5.0,
                                                            "release_ms": 100.0, "makeup_db": 4.0}}]},
    "drum bus": {"desc": "glue and punch for drums",
                 "effects": [{"type": "compressor", "params": {"threshold_db": -14.0, "ratio": 4.0, "attack_ms": 20.0,
                                                               "release_ms": 120.0, "makeup_db": 3.0, "mix": 0.6}},
                             {"type": "distortion", "params": {"drive": 0.1, "mode": "tape", "output_db": 0.0, "mix": 0.5}}]},
    "bass": {"desc": "tight, mono-safe bass",
             "effects": [{"type": "eq", "params": {"low_cut": 30.0, "mid_gain": -3.0, "mid_freq": 250.0}},
                         {"type": "compressor", "params": {"threshold_db": -16.0, "ratio": 4.0, "attack_ms": 15.0,
                                                           "release_ms": 80.0, "makeup_db": 2.0}},
                         {"type": "stereo_width", "params": {"width": 0.0}}]},
    "pad space": {"desc": "wide, washed pad",
                  "effects": [{"type": "eq", "params": {"low_cut": 180.0}},
                              {"type": "chorus", "params": {"mix": 0.35}},
                              {"type": "reverb", "params": {"decay": 3.5, "mix": 0.35}}]},
    "lofi": {"desc": "dusty cassette vibe",
             "effects": [{"type": "lofi", "params": {}},
                         {"type": "compressor", "params": {"threshold_db": -18.0, "ratio": 3.0, "makeup_db": 2.0}}]},
    "radio": {"desc": "old radio / telephone",
              "effects": [{"type": "bandpass", "params": {"cutoff": 1500.0, "q": 0.8, "steep": True}},
                          {"type": "distortion", "params": {"drive": 0.3, "mode": "soft", "output_db": -2.0}}]},
    "slapback": {"desc": "50s slapback echo",
                 "effects": [{"type": "delay", "params": {"time_ms": 110.0, "feedback": 0.15, "mix": 0.3, "tone": 4000.0}}]},
    "big reverb bus": {"desc": "hall reverb for a send bus (100% wet)",
                       "effects": [{"type": "reverb", "params": {"decay": 2.8, "predelay_ms": 30.0, "mix": 1.0}}]},
    "plate bus": {"desc": "bright plate for vocals and snares (100% wet)",
                  "effects": [{"type": "reverb", "params": {"decay": 1.6, "damping": 0.2, "predelay_ms": 10.0, "mix": 1.0}}]},
    "delay bus": {"desc": "dotted-eighth ping-pong delay (100% wet)",
                  "effects": [{"type": "delay", "params": {"time_beats": 0.75, "feedback": 0.4, "ping_pong": True,
                                                           "mix": 1.0, "tone": 5000.0}}]},
    "master streaming": {"desc": "gentle master for streaming (~-14 LUFS): EQ tilt, glue, limiter at -1 dBTP",
                         "effects": [{"type": "eq", "params": {"low_cut": 25.0, "high_gain": 1.0, "high_freq": 10000.0}},
                                     {"type": "compressor", "params": {"threshold_db": -14.0, "ratio": 2.0, "attack_ms": 30.0,
                                                                       "release_ms": 200.0, "knee_db": 8.0}},
                                     {"type": "stereo_width", "params": {"width": 1.05, "bass_mono": 120.0}},
                                     {"type": "limiter", "params": {"gain_db": 3.0, "ceiling_db": -1.0}}]},
    "master loud": {"desc": "loud master for club/EDM (~-9 LUFS)",
                    "effects": [{"type": "eq", "params": {"low_cut": 25.0, "low_gain": 1.0, "high_gain": 1.5}},
                                {"type": "compressor", "params": {"threshold_db": -12.0, "ratio": 3.0, "attack_ms": 20.0,
                                                                  "release_ms": 150.0}},
                                {"type": "distortion", "params": {"drive": 0.1, "mode": "tape", "output_db": 0.0, "mix": 0.3}},
                                {"type": "stereo_width", "params": {"width": 1.1, "bass_mono": 150.0}},
                                {"type": "limiter", "params": {"gain_db": 7.0, "ceiling_db": -0.8}}]},
}

# programmi General MIDI -> suono interno (per importare file .mid)
GM_MAP = [
    (0, 7, "piano"), (8, 15, "bell"), (16, 23, "organ"), (24, 25, "nylon guitar"), (26, 31, "acoustic guitar"),
    (32, 32, "finger bass"), (33, 37, "finger bass"), (38, 39, "saw bass"), (40, 51, "strings"),
    (52, 54, "choir pad"), (55, 55, "strings"), (56, 63, "brass"), (64, 79, "soft lead"), (80, 80, "square lead"),
    (81, 87, "supersaw lead"), (88, 95, "warm pad"), (96, 103, "airy pad"), (104, 111, "pluck"),
    (112, 119, "marimba"), (120, 127, "bell"),
]


def gm_sound(program: int) -> str:
    for a, b, nome in GM_MAP:
        if a <= program <= b:
            return nome
    return "piano"


# --------------------------------------------------------------------------
# preset dell'utente
# --------------------------------------------------------------------------


def _file() -> Path:
    base = Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "presets.json"


def _utente() -> dict:
    f = _file()
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"sounds": dict(d.get("sounds") or {}), "chains": dict(d.get("chains") or {})}
    except (OSError, ValueError):
        return {"sounds": {}, "chains": {}}


def _scrivi(d: dict) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


def sound(name: str) -> dict:
    u = _utente()["sounds"]
    if name in u:
        return u[name]
    if name in SOUNDS:
        return SOUNDS[name]
    low = name.lower()
    for k, v in {**SOUNDS, **u}.items():
        if k.lower() == low:
            return v
    raise ValueError(f"unknown sound {name!r}; available: {', '.join(list(SOUNDS) + list(u))}")


def chain(name: str) -> dict:
    u = _utente()["chains"]
    if name in u:
        return u[name]
    if name in CHAINS:
        return CHAINS[name]
    raise ValueError(f"unknown chain {name!r}; available: {', '.join(list(CHAINS) + list(u))}")


def describe_sounds() -> list[dict]:
    u = _utente()["sounds"]
    out = [{"name": k, "type": v["type"], "category": v.get("category", ""), "desc": v.get("desc", ""), "user": False}
           for k, v in SOUNDS.items()]
    out += [{"name": k, "type": v["type"], "category": v.get("category", "mine"), "desc": v.get("desc", ""), "user": True}
            for k, v in u.items()]
    return out


def describe_chains() -> list[dict]:
    u = _utente()["chains"]
    out = [{"name": k, "desc": v["desc"], "effects": [e["type"] for e in v["effects"]], "user": False}
           for k, v in CHAINS.items()]
    out += [{"name": k, "desc": v.get("desc", ""), "effects": [e["type"] for e in v["effects"]], "user": True}
            for k, v in u.items()]
    return out


def save_sound(name: str, kind: str, params: dict, desc: str = "", category: str = "mine") -> dict:
    name = name.strip()
    if not name:
        raise ValueError("a sound needs a name")
    if name in SOUNDS:
        raise ValueError(f"{name!r} is a built-in sound: pick another name")
    synth.validate(kind, params)
    d = _utente()
    d["sounds"][name] = {"type": kind, "params": params, "desc": desc, "category": category}
    _scrivi(d)
    return {"saved": name}


def save_chain(name: str, effects: list[dict], desc: str = "") -> dict:
    name = name.strip()
    if not name:
        raise ValueError("a chain needs a name")
    if name in CHAINS:
        raise ValueError(f"{name!r} is a built-in chain: pick another name")
    if not effects:
        raise ValueError("a chain needs at least one effect")
    pulite = []
    for e in effects:
        pulite.append({"type": e["type"], "params": fx.validate(e["type"], e.get("params"), partial=True)})
    d = _utente()
    d["chains"][name] = {"desc": desc, "effects": pulite}
    _scrivi(d)
    return {"saved": name, "effects": [e["type"] for e in pulite]}


def delete_user(name: str) -> dict:
    d = _utente()
    tolti = [k for k in ("sounds", "chains") if d[k].pop(name, None) is not None]
    if not tolti:
        raise ValueError(f"no preset of yours called {name!r}")
    _scrivi(d)
    return {"deleted": name}
