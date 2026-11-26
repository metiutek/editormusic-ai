"""Strumenti interni: sintesi in numpy, una nota alla volta, vettoriale.

Cinque motori, tutti deterministici (il rumore ha un seme che dipende dalla
nota), cosi' il render resta una funzione pura del documento:

- ``synth``   sottrattivo: due oscillatori PolyBLEP + sub + rumore, unison con
              detune e apertura stereo, filtro biquad con inviluppo, ADSR;
- ``fm``      due operatori (+ un terzo per il "tine" dei piani elettrici);
- ``pluck``   corda pizzicata Karplus-Strong (chitarre, arpe, bassi);
- ``drums``   kit di batteria sintetizzato sulle note General MIDI;
- ``sampler`` un file audio suonato alle varie altezze, o una mappa nota -> file.

Ogni motore riceve note in campioni assoluti e restituisce un buffer stereo
(2, N) float32. I parametri mancanti prendono i default qui sotto: un preset e'
solo un dizionario di parametri.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

import numpy as np
from scipy.signal import lfilter

WAVES = ("saw", "square", "triangle", "sine", "noise")
FILTERS = ("lowpass", "highpass", "bandpass", "none")

SYNTH_DEFAULTS = {
    "osc1": "saw", "osc2": "saw", "osc2_semi": 0.0, "osc2_detune": 7.0, "osc_mix": 0.5, "pw": 0.5,
    "sub": 0.0, "noise": 0.0, "unison": 1, "unison_detune": 15.0, "spread": 0.5,
    "attack": 0.005, "decay": 0.3, "sustain": 0.7, "release": 0.25,
    "filter": "lowpass", "cutoff": 4000.0, "resonance": 0.7, "filter_env": 0.0,
    "f_attack": 0.005, "f_decay": 0.3, "f_sustain": 0.0, "keytrack": 0.5, "vel_to_filter": 0.3,
    "vibrato_rate": 5.0, "vibrato_depth": 0.0, "drive": 0.0, "gain_db": 0.0, "velocity_sens": 0.7,
    "octave": 0, "glide": 0.0,
}
FM_DEFAULTS = {
    "ratio": 1.0, "index": 2.0, "index_decay": 0.5, "index_sustain": 0.2, "ratio2": 0.0, "index2": 0.0,
    "decay2": 0.05, "attack": 0.002, "decay": 1.2, "sustain": 0.3, "release": 0.4, "detune": 4.0,
    "vel_to_index": 0.6, "gain_db": 0.0, "velocity_sens": 0.7, "octave": 0, "tremolo": 0.0,
}
PLUCK_DEFAULTS = {
    "brightness": 0.6, "decay": 3.0, "pick_position": 0.2, "body": 0.4, "release": 0.08, "width": 0.4,
    "gain_db": 0.0, "velocity_sens": 0.6, "octave": 0, "mute": 0.0,
}
DRUM_DEFAULTS = {
    "tune": 0.0, "kick_freq": 52.0, "kick_start": 160.0, "kick_decay": 0.45, "kick_click": 0.4,
    "kick_drive": 0.2, "kick_sweep": 0.04, "snare_tone": 190.0, "snare_decay": 0.18, "snare_noise": 0.7,
    "clap_decay": 0.2, "hat_decay": 0.05, "hat_open_decay": 0.35, "hat_tone": 0.6, "tom_decay": 0.35,
    "cymbal_decay": 1.6, "crush": 0.0, "gain_db": 0.0, "pan_spread": 0.3, "velocity_sens": 0.8,
}
SAMPLER_DEFAULTS = {
    "asset": None, "root": 60, "one_shot": False, "attack": 0.002, "release": 0.15, "gain_db": 0.0,
    "start": 0.0, "end": 0.0, "velocity_sens": 0.6, "map": {}, "octave": 0,
}
DEFAULTS = {"synth": SYNTH_DEFAULTS, "fm": FM_DEFAULTS, "pluck": PLUCK_DEFAULTS, "drums": DRUM_DEFAULTS,
            "sampler": SAMPLER_DEFAULTS}

# descrizioni brevi dei parametri, per la UI e per l'agente
PARAM_DOCS = {
    "synth": {
        "osc1": "wave of oscillator 1: saw, square, triangle, sine, noise", "osc2": "wave of oscillator 2",
        "osc2_semi": "osc 2 pitch in semitones", "osc2_detune": "osc 2 detune in cents",
        "osc_mix": "0 = only osc 1, 1 = only osc 2", "pw": "pulse width of square waves (0.05-0.95)",
        "sub": "sub oscillator (sine, one octave down) level 0-1", "noise": "noise level 0-1",
        "unison": "voices per note 1-7 (supersaw)", "unison_detune": "spread of the unison voices in cents",
        "spread": "stereo width of the unison voices 0-1",
        "attack": "amp attack s", "decay": "amp decay s", "sustain": "amp sustain 0-1", "release": "amp release s",
        "filter": "lowpass, highpass, bandpass or none", "cutoff": "filter cutoff Hz",
        "resonance": "filter Q (0.5-12)", "filter_env": "filter envelope amount in octaves (+/-)",
        "f_attack": "filter env attack s", "f_decay": "filter env decay s", "f_sustain": "filter env sustain 0-1",
        "keytrack": "cutoff follows the pitch 0-1", "vel_to_filter": "velocity opens the filter 0-1",
        "vibrato_rate": "Hz", "vibrato_depth": "cents", "drive": "saturation 0-1",
        "gain_db": "output level", "velocity_sens": "how much velocity changes loudness 0-1",
        "octave": "transpose in octaves", "glide": "portamento time s (monophonic slides)",
    },
    "fm": {
        "ratio": "modulator/carrier frequency ratio", "index": "modulation depth (brightness)",
        "index_decay": "how fast brightness decays s", "index_sustain": "brightness left while held 0-1",
        "ratio2": "second modulator ratio (0 = off; 14 = e-piano tine)", "index2": "second modulator depth",
        "decay2": "second modulator decay s", "attack": "s", "decay": "s", "sustain": "0-1", "release": "s",
        "detune": "stereo detune in cents (chorus)", "vel_to_index": "velocity adds brightness 0-1",
        "gain_db": "output level", "velocity_sens": "0-1", "octave": "octaves", "tremolo": "amplitude wobble 0-1",
    },
    "pluck": {
        "brightness": "0 dull - 1 bright", "decay": "ring time s", "pick_position": "0.05 near bridge (thin) - 0.5 middle (round)",
        "body": "wooden body resonance 0-1", "release": "how fast the string is damped after note off s",
        "width": "stereo doubling 0-1", "mute": "palm mute 0-1", "gain_db": "output level", "velocity_sens": "0-1",
        "octave": "octaves",
    },
    "drums": {
        "tune": "semitones for the whole kit", "kick_freq": "kick body Hz", "kick_start": "kick attack pitch Hz",
        "kick_decay": "kick length s (long = 808)", "kick_click": "beater click 0-1", "kick_drive": "kick saturation 0-1",
        "kick_sweep": "pitch drop time s", "snare_tone": "snare shell Hz", "snare_decay": "s", "snare_noise": "snare wires 0-1",
        "clap_decay": "s", "hat_decay": "closed hat s", "hat_open_decay": "open hat s", "hat_tone": "hat brightness 0-1",
        "tom_decay": "s", "cymbal_decay": "s", "crush": "lo-fi bit crushing 0-1", "gain_db": "output level",
        "pan_spread": "stereo placement of hats/toms/cymbals 0-1", "velocity_sens": "0-1",
    },
    "sampler": {
        "asset": "audio asset id to play", "root": "MIDI note at which the sample plays at original pitch",
        "one_shot": "play the whole sample regardless of note length", "attack": "s", "release": "s",
        "gain_db": "output level", "start": "start inside the sample s", "end": "end inside the sample s (0 = end)",
        "velocity_sens": "0-1", "map": "drum-kit mode: {\"36\": asset_id, \"38\": asset_id, ...}",
        "octave": "octaves",
    },
}


def merged(kind: str, params: dict | None) -> dict:
    if kind not in DEFAULTS:
        raise ValueError(f"unknown instrument type {kind!r}; available: {', '.join(DEFAULTS)}")
    out = dict(DEFAULTS[kind])
    for k, v in (params or {}).items():
        if k in out:
            out[k] = v
    return out


def validate(kind: str, params: dict) -> dict:
    """Parametri sconosciuti o valori assurdi -> errore che dice cosa e' ammesso."""
    base = DEFAULTS.get(kind)
    if base is None:
        raise ValueError(f"unknown instrument type {kind!r}; available: {', '.join(DEFAULTS)}")
    out = {}
    for k, v in (params or {}).items():
        if k not in base:
            raise ValueError(f"{kind} has no parameter {k!r}; parameters: {', '.join(base)}")
        if k in ("osc1", "osc2") and v not in WAVES:
            raise ValueError(f"{k} must be one of {', '.join(WAVES)}")
        if k == "filter" and v not in FILTERS:
            raise ValueError(f"filter must be one of {', '.join(FILTERS)}")
        if isinstance(base[k], (int, float)) and not isinstance(base[k], bool) and base[k] is not None:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{kind}.{k} must be a number") from None
            if k == "unison":
                v = int(max(1, min(7, v)))
        out[k] = v
    return out


def midi_hz(p: float) -> float:
    return 440.0 * 2.0 ** ((p - 69.0) / 12.0)


def _db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def _seme(*parti) -> int:
    h = hashlib.blake2b(json.dumps(parti, default=str).encode(), digest_size=8).digest()
    return int.from_bytes(h, "little")


# --------------------------------------------------------------------------
# mattoni
# --------------------------------------------------------------------------


def adsr(n_on: int, sr: int, a: float, d: float, s: float, r: float, n_total: int | None = None) -> np.ndarray:
    """Inviluppo: attacco lineare, decadimento e rilascio esponenziali.

    ``n_on`` campioni a tasto premuto, poi il rilascio parte dal livello raggiunto.
    """
    a_s = max(1, int(a * sr))
    d_s = max(1, int(d * sr))
    r_s = max(1, int(r * sr))
    n = n_total if n_total is not None else n_on + r_s
    idx = np.arange(n, dtype=np.float64)
    env = np.where(idx < a_s, idx / a_s,
                   s + (1.0 - s) * np.exp(-5.0 * np.clip(idx - a_s, 0, None) / d_s))
    if n_on < n:
        liv = env[n_on - 1] if n_on > 0 else 0.0
        coda = liv * np.exp(-6.9 * (idx[n_on:] - n_on) / r_s)
        env[n_on:] = np.minimum(env[n_on:], coda)
    return env


def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    out[m] = x * x + x + x + 1.0
    return out


def oscillator(wave: str, freq: np.ndarray, sr: int, phase0: float = 0.0, pw: float = 0.5,
               rng: np.random.Generator | None = None) -> np.ndarray:
    """Oscillatore a banda limitata (PolyBLEP) su una frequenza che puo' variare."""
    n = len(freq)
    if wave == "noise":
        rng = rng or np.random.default_rng(0)
        return rng.uniform(-1, 1, n)
    dt = np.clip(freq / sr, 1e-9, 0.5)
    phase = (phase0 + np.cumsum(dt)) % 1.0
    if wave == "sine":
        return np.sin(2 * np.pi * phase)
    if wave == "triangle":
        return 2.0 * np.abs(2.0 * phase - 1.0) - 1.0
    if wave == "square":
        pw = float(np.clip(pw, 0.05, 0.95))
        sq = np.where(phase < pw, 1.0, -1.0)
        sq += _polyblep(phase, dt)
        sq -= _polyblep((phase + 1.0 - pw) % 1.0, dt)
        return sq
    saw = 2.0 * phase - 1.0
    saw -= _polyblep(phase, dt)
    return saw


def biquad(kind: str, f: float, q: float, sr: int, gain_db: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Coefficienti RBJ (cookbook). kind: lowpass, highpass, bandpass, peak, lowshelf, highshelf, notch."""
    f = float(np.clip(f, 10.0, sr * 0.45))
    q = float(max(0.1, q))
    w = 2 * np.pi * f / sr
    cw, sw = np.cos(w), np.sin(w)
    al = sw / (2 * q)
    A = 10 ** (gain_db / 40.0)
    if kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "bandpass":
        b = [al, 0.0, -al]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "notch":
        b = [1.0, -2 * cw, 1.0]
        a = [1 + al, -2 * cw, 1 - al]
    elif kind == "peak":
        b = [1 + al * A, -2 * cw, 1 - al * A]
        a = [1 + al / A, -2 * cw, 1 - al / A]
    elif kind == "lowshelf":
        sa = 2 * np.sqrt(A) * al
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif kind == "highshelf":
        sa = 2 * np.sqrt(A) * al
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    else:
        raise ValueError(f"unknown filter {kind!r}")
    a0 = a[0]
    return np.array(b) / a0, np.array(a) / a0


def filter_sweep(x: np.ndarray, kind: str, cutoff: np.ndarray | float, q: float, sr: int,
                 block: int = 256) -> np.ndarray:
    """Filtro con frequenza di taglio che cambia nel tempo (a blocchi, stato continuo).

    ``x`` (C, N). Con un taglio costante e' un solo ``lfilter``.
    """
    if kind == "none":
        return x
    if np.isscalar(cutoff) or np.ptp(cutoff) < 1.0:
        f = float(cutoff if np.isscalar(cutoff) else cutoff[0])
        b, a = biquad(kind, f, q, sr)
        return lfilter(b, a, x, axis=-1)
    n = x.shape[-1]
    out = np.empty_like(x)
    zi = np.zeros((x.shape[0], 2))
    for i in range(0, n, block):
        b, a = biquad(kind, float(cutoff[i]), q, sr)
        out[:, i:i + block], zi = lfilter(b, a, x[:, i:i + block], axis=-1, zi=zi)
    return out


def _pan_gains(pan: float) -> tuple[float, float]:
    """Pan a potenza costante: -1 sinistra, 0 centro, 1 destra."""
    th = (float(np.clip(pan, -1, 1)) + 1) * np.pi / 4
    return float(np.cos(th) * np.sqrt(2)), float(np.sin(th) * np.sqrt(2))


def _vel_gain(vel: int, sens: float) -> float:
    v = max(1, min(127, int(vel))) / 127.0
    return float((1 - sens) + sens * v ** 1.6)


# --------------------------------------------------------------------------
# motori
# --------------------------------------------------------------------------


def _synth_note(p: dict, pitch: float, vel: int, n_on: int, sr: int, seed: int,
                pitch_from: float | None = None) -> np.ndarray:
    release = float(p["release"])
    env = adsr(n_on, sr, p["attack"], p["decay"], p["sustain"], release)
    n = len(env)
    pitch = pitch + 12 * int(p["octave"])
    t = np.arange(n) / sr
    semis = np.full(n, float(pitch))
    if pitch_from is not None and p["glide"] > 0:
        da = pitch_from + 12 * int(p["octave"])
        k = np.clip(np.arange(n) / max(1, int(p["glide"] * sr)), 0, 1)
        semis = da + (pitch - da) * k
    if p["vibrato_depth"]:
        ritardo = np.clip((t - 0.15) / 0.3, 0, 1)
        semis = semis + (p["vibrato_depth"] / 100.0) * ritardo * np.sin(2 * np.pi * p["vibrato_rate"] * t)
    freq = 440.0 * 2.0 ** ((semis - 69.0) / 12.0)
    rng = np.random.default_rng(seed)
    voci = int(max(1, min(7, p["unison"])))
    out = np.zeros((2, n))
    mix = float(np.clip(p["osc_mix"], 0, 1))
    for v in range(voci):
        if voci > 1:
            pos = v / (voci - 1) * 2 - 1
            det = 2 ** (pos * p["unison_detune"] / 1200.0)
            pan = pos * p["spread"]
        else:
            det, pan = 1.0, 0.0
        ph = rng.random() if voci > 1 else 0.0
        s = np.zeros(n)
        if mix < 1:
            s += (1 - mix) * oscillator(p["osc1"], freq * det, sr, ph, p["pw"], rng)
        if mix > 0:
            f2 = freq * det * 2 ** (p["osc2_semi"] / 12.0 + p["osc2_detune"] / 1200.0)
            s += mix * oscillator(p["osc2"], f2, sr, (ph + 0.37) % 1.0, p["pw"], rng)
        gl, gr = _pan_gains(pan)
        out[0] += s * gl
        out[1] += s * gr
    out /= np.sqrt(voci)
    if p["sub"]:
        sub = p["sub"] * oscillator("sine", freq / 2, sr)
        out += sub
    if p["noise"]:
        out += p["noise"] * 0.5 * rng.uniform(-1, 1, (2, n))
    if p["filter"] != "none":
        vel01 = vel / 127.0
        base = p["cutoff"] * 2 ** (p["keytrack"] * (pitch - 60) / 12.0) * 2 ** (p["vel_to_filter"] * (vel01 - 0.7) * 2)
        if p["filter_env"]:
            fenv = adsr(n_on, sr, p["f_attack"], p["f_decay"], p["f_sustain"], release, n)
            cut = base * 2 ** (p["filter_env"] * fenv)
        else:
            cut = base
        out = filter_sweep(out, p["filter"], np.clip(cut, 20, sr * 0.45) if not np.isscalar(cut) else
                           float(np.clip(cut, 20, sr * 0.45)), p["resonance"], sr)
    if p["drive"]:
        k = 1 + 8 * p["drive"]
        out = np.tanh(out * k) / np.tanh(k)
    return out * env * _vel_gain(vel, p["velocity_sens"]) * 0.35 * _db(p["gain_db"])


def _fm_note(p: dict, pitch: float, vel: int, n_on: int, sr: int, seed: int) -> np.ndarray:
    env = adsr(n_on, sr, p["attack"], p["decay"], p["sustain"], p["release"])
    n = len(env)
    t = np.arange(n) / sr
    f = midi_hz(pitch + 12 * int(p["octave"]))
    vel01 = vel / 127.0
    idx_env = p["index_sustain"] + (1 - p["index_sustain"]) * np.exp(-t / max(1e-3, p["index_decay"]))
    index = p["index"] * idx_env * (1 + p["vel_to_index"] * (vel01 - 0.6))
    out = np.zeros((2, n))
    for ch, cents in ((0, -p["detune"] / 2), (1, p["detune"] / 2)):
        fc = f * 2 ** (cents / 1200.0)
        mod = np.sin(2 * np.pi * fc * p["ratio"] * t) * index
        if p["ratio2"] and p["index2"]:
            mod += np.sin(2 * np.pi * fc * p["ratio2"] * t) * p["index2"] * np.exp(-t / max(1e-3, p["decay2"]))
        out[ch] = np.sin(2 * np.pi * fc * t + mod)
    if p["tremolo"]:
        out *= 1 - p["tremolo"] * 0.5 * (1 + np.sin(2 * np.pi * 4.5 * t))
    return out * env * _vel_gain(vel, p["velocity_sens"]) * 0.3 * _db(p["gain_db"])


def _ks(f: float, n: int, n_on: int, sr: int, p: dict, vel: int, rng: np.random.Generator) -> np.ndarray:
    """Karplus-Strong a blocchi lunghi un periodo: ogni blocco dipende solo dal precedente."""
    periodo = sr / f
    N = max(2, int(periodo))
    w = periodo - N
    # eccitazione: rumore filtrato (brillantezza) con il pettine della posizione del plettro
    burst = rng.uniform(-1, 1, N)
    bright = float(np.clip(p["brightness"] * (0.6 + 0.4 * vel / 127.0), 0.02, 1.0))
    if bright < 1:
        a = 1 - bright
        burst = lfilter([1 - a], [1, -a], burst)
    k = int(N * float(np.clip(p["pick_position"], 0.02, 0.5)))
    if k > 0:
        burst = burst - np.concatenate([np.zeros(k), burst[:-k]])
    burst -= burst.mean()
    x = np.zeros(n)
    x[:N] = burst
    T60 = max(0.05, p["decay"] * (1 - 0.85 * p["mute"]))
    g_on = 10 ** (-3.0 / (f * T60))
    g_off = 10 ** (-3.0 / (f * max(0.01, p["release"])))
    y = np.zeros(n + N + 1)
    y_off = N + 1   # y[i + y_off] = uscita al campione i (in testa, zeri)
    for start in range(0, n, N):
        stop = min(n, start + N)
        g = g_on if start < n_on else g_off
        a1 = y[start + y_off - N: stop + y_off - N]
        a2 = y[start + y_off - N - 1: stop + y_off - N - 1]
        y[start + y_off: stop + y_off] = x[start:stop] + g * ((1 - w) * a1 + w * a2)
    return y[y_off:y_off + n]


def _pluck_note(p: dict, pitch: float, vel: int, n_on: int, sr: int, seed: int) -> np.ndarray:
    f = midi_hz(pitch + 12 * int(p["octave"]))
    coda = int(max(p["release"], 0.02) * sr * 4)
    n = n_on + coda
    rng = np.random.default_rng(seed)
    left = _ks(f, n, n_on, sr, p, vel, rng)
    if p["width"] > 0:
        right = _ks(f * 2 ** (3 / 1200.0), n, n_on, sr, p, vel, rng)
        out = np.stack([left * (1 - p["width"] / 2) + right * p["width"] / 2,
                        right * (1 - p["width"] / 2) + left * p["width"] / 2])
    else:
        out = np.stack([left, left])
    if p["body"]:
        b, a = biquad("peak", 180.0, 1.2, sr, 6 * p["body"])
        out = lfilter(b, a, out, axis=-1)
        b, a = biquad("peak", 2600.0, 2.0, sr, 2 * p["body"])
        out = lfilter(b, a, out, axis=-1)
    fade = np.ones(n)
    fade[-min(n, 256):] = np.linspace(1, 0, min(n, 256))
    return out * fade * _vel_gain(vel, p["velocity_sens"]) * 0.5 * _db(p["gain_db"])


# --------------------------------------------------------------------------
# batteria
# --------------------------------------------------------------------------

# note GM -> (voce, pan)
_KIT_MAP = {
    35: ("kick", 0), 36: ("kick", 0), 37: ("rim", 0.1), 38: ("snare", 0), 40: ("snare", 0), 39: ("clap", 0),
    41: ("tom_floor", -0.3), 43: ("tom_floor", -0.3), 45: ("tom_low", -0.15), 47: ("tom_mid", 0.1),
    48: ("tom_mid", 0.1), 50: ("tom_high", 0.25), 42: ("hat", 0.3), 44: ("hat_pedal", 0.3),
    46: ("hat_open", 0.3), 49: ("crash", -0.4), 57: ("crash", 0.45), 55: ("crash", -0.4),
    51: ("ride", 0.4), 59: ("ride", 0.4), 53: ("ride_bell", 0.4), 52: ("china", -0.45),
    54: ("tambourine", 0.35), 56: ("cowbell", -0.2), 69: ("shaker", 0.3), 70: ("shaker", 0.3),
    75: ("clave", 0.2), 76: ("woodblock", -0.2), 77: ("woodblock", 0.2),
}
_HAT_CHOKE = {42, 44}
_HAT_OPEN = {46}


def _metallo(n: int, sr: int, base: float, rng) -> np.ndarray:
    """Sei onde quadre a frequenze inarmoniche: il suono dei piatti dell'808."""
    t = np.arange(n) / sr
    s = np.zeros(n)
    for r in (1.0, 1.342, 1.2312, 1.6532, 1.9523, 2.1523):
        s += np.sign(np.sin(2 * np.pi * base * r * t + rng.random() * 6.28))
    return s / 6.0


def drum_voice(voce: str, vel: int, p: dict, sr: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tune = 2 ** (p["tune"] / 12.0)

    def env(dec, n):
        return np.exp(-np.arange(n) / (max(1e-3, dec) * sr) * 6.9)

    if voce == "kick":
        dec = p["kick_decay"]
        n = int(sr * (dec + 0.05))
        t = np.arange(n) / sr
        f = p["kick_freq"] * tune + (p["kick_start"] - p["kick_freq"]) * tune * np.exp(-t / max(1e-3, p["kick_sweep"]))
        ph = 2 * np.pi * np.cumsum(f) / sr
        s = np.sin(ph) * env(dec, n)
        if p["kick_click"]:
            nc = int(sr * 0.004)
            click = rng.uniform(-1, 1, nc) * np.linspace(1, 0, nc) * p["kick_click"]
            b, a = biquad("highpass", 1500, 0.7, sr)
            s[:nc] += lfilter(b, a, click)
        if p["kick_drive"]:
            k = 1 + 6 * p["kick_drive"]
            s = np.tanh(s * k) / np.tanh(k)
        return np.stack([s, s])
    if voce in ("snare", "rim", "clap"):
        if voce == "rim":
            n = int(sr * 0.06)
            t = np.arange(n) / sr
            s = (np.sin(2 * np.pi * 820 * tune * t) * 0.6 + rng.uniform(-1, 1, n) * 0.4) * env(0.025, n)
            b, a = biquad("bandpass", 1800, 1.5, sr)
            s = lfilter(b, a, s) * 2.0
        elif voce == "clap":
            dec = p["clap_decay"]
            n = int(sr * (dec + 0.05))
            rumore = rng.uniform(-1, 1, n)
            inv = np.zeros(n)
            for k, off in enumerate((0.0, 0.011, 0.022)):
                i0 = int(off * sr)
                m = int(0.01 * sr)
                inv[i0:i0 + m] = np.maximum(inv[i0:i0 + m], np.exp(-np.arange(min(m, n - i0)) / (0.003 * sr)))
            i0 = int(0.03 * sr)
            inv[i0:] = np.maximum(inv[i0:], env(dec, n - i0))
            b, a = biquad("bandpass", 1300, 1.2, sr)
            s = lfilter(b, a, rumore * inv) * 2.5
        else:
            dec = p["snare_decay"]
            n = int(sr * (dec + 0.1))
            t = np.arange(n) / sr
            corpo = (np.sin(2 * np.pi * p["snare_tone"] * tune * t) +
                     0.5 * np.sin(2 * np.pi * p["snare_tone"] * 1.6 * tune * t)) * env(dec * 0.5, n)
            fili = rng.uniform(-1, 1, n)
            b, a = biquad("highpass", 1800, 0.7, sr)
            fili = lfilter(b, a, fili) * env(dec, n)
            s = corpo * (1 - p["snare_noise"] * 0.6) + fili * p["snare_noise"] * 1.2
        return np.stack([s, s])
    if voce.startswith("tom"):
        base = {"tom_floor": 82, "tom_low": 105, "tom_mid": 135, "tom_high": 170}[voce] * tune
        dec = p["tom_decay"]
        n = int(sr * (dec + 0.05))
        t = np.arange(n) / sr
        f = base * (1 + 0.6 * np.exp(-t / 0.03))
        s = np.sin(2 * np.pi * np.cumsum(f) / sr) * env(dec, n)
        s += rng.uniform(-1, 1, n) * env(0.01, n) * 0.1
        return np.stack([s, s])
    if voce in ("hat", "hat_pedal", "hat_open", "crash", "ride", "ride_bell", "china"):
        dec = {"hat": p["hat_decay"], "hat_pedal": p["hat_decay"] * 0.7, "hat_open": p["hat_open_decay"],
               "crash": p["cymbal_decay"], "china": p["cymbal_decay"] * 0.8, "ride": p["cymbal_decay"] * 1.2,
               "ride_bell": p["cymbal_decay"] * 0.8}[voce]
        n = int(sr * (dec + 0.05))
        metallo = _metallo(n, sr, 330 * tune if "ride" not in voce else 420 * tune, rng)
        rumore = rng.uniform(-1, 1, n)
        mix = {"hat": 0.5, "hat_pedal": 0.5, "hat_open": 0.5, "crash": 0.35, "china": 0.6,
               "ride": 0.7, "ride_bell": 0.9}[voce]
        s = metallo * mix + rumore * (1 - mix)
        hp = 6000 + 3000 * p["hat_tone"] if voce.startswith("hat") else 4000 + 2000 * p["hat_tone"]
        b, a = biquad("highpass", hp, 0.8, sr)
        s = lfilter(b, a, s)
        if voce == "ride_bell":
            t = np.arange(n) / sr
            s += 0.4 * np.sin(2 * np.pi * 2350 * tune * t)
        s = s * env(dec, n) * (1.4 if voce.startswith("hat") else 0.8)
        return np.stack([s, s])
    if voce in ("tambourine", "shaker"):
        dec = 0.12 if voce == "tambourine" else 0.06
        n = int(sr * (dec + 0.03))
        s = rng.uniform(-1, 1, n)
        b, a = biquad("highpass", 7000 if voce == "shaker" else 5000, 0.7, sr)
        s = lfilter(b, a, s) * env(dec, n) * (0.9 if voce == "shaker" else 1.2)
        if voce == "tambourine":
            s += 0.3 * _metallo(n, sr, 2200 * tune, rng) * env(dec, n)
        return np.stack([s, s])
    if voce == "cowbell":
        n = int(sr * 0.3)
        t = np.arange(n) / sr
        s = (np.sign(np.sin(2 * np.pi * 540 * tune * t)) + np.sign(np.sin(2 * np.pi * 800 * tune * t))) * 0.4
        b, a = biquad("bandpass", 900 * tune, 2.0, sr)
        s = lfilter(b, a, s) * env(0.2, n) * 2.0
        return np.stack([s, s])
    # clave, woodblock e tutto il resto: un colpo di legno
    n = int(sr * 0.08)
    t = np.arange(n) / sr
    f = 2500 if voce == "clave" else 1200
    s = np.sin(2 * np.pi * f * tune * t) * env(0.03, n)
    return np.stack([s, s])


def _crush(x: np.ndarray, amount: float, sr: int) -> np.ndarray:
    if amount <= 0:
        return x
    bits = 16 - 12 * amount
    q = 2 ** bits
    x = np.round(x * q) / q
    passo = int(1 + 7 * amount)
    if passo > 1:
        x = np.repeat(x[:, ::passo], passo, axis=1)[:, :x.shape[1]]
    return x


# --------------------------------------------------------------------------
# sampler
# --------------------------------------------------------------------------


def _resample(x: np.ndarray, ratio: float) -> np.ndarray:
    """Cambio di velocita' (e altezza) per interpolazione lineare: ratio 2 = un'ottava sopra."""
    n = x.shape[-1]
    if abs(ratio - 1.0) < 1e-6 or n < 2:
        return x
    m = max(1, int(n / ratio))
    pos = np.arange(m) * ratio
    return np.stack([np.interp(pos, np.arange(n), ch) for ch in x])


def _sampler_note(p: dict, pitch: float, vel: int, n_on: int, sr: int, loader: Callable | None) -> np.ndarray | None:
    mappa = p.get("map") or {}
    asset = mappa.get(str(int(pitch))) if mappa else p.get("asset")
    if not asset or loader is None:
        return None
    x = loader(asset)
    if x is None or x.shape[-1] == 0:
        return None
    i0 = int(p["start"] * sr)
    i1 = int(p["end"] * sr) if p["end"] else x.shape[-1]
    x = x[:, i0:i1]
    if not mappa:
        x = _resample(x, 2 ** ((pitch + 12 * int(p["octave"]) - p["root"]) / 12.0))
    n = x.shape[-1]
    if p["one_shot"] or mappa:
        env = adsr(n, sr, p["attack"], 0.01, 1.0, 0.005, n)
    else:
        n_tot = min(n, n_on + int(p["release"] * sr))
        x = x[:, :n_tot]
        env = adsr(min(n_on, n_tot), sr, p["attack"], 0.01, 1.0, p["release"], n_tot)
    return x * env * _vel_gain(vel, p["velocity_sens"]) * _db(p["gain_db"])


# --------------------------------------------------------------------------
# render di una sequenza di note
# --------------------------------------------------------------------------


# note gia' sintetizzate: il render a pezzi rilegge le stesse note (pre-roll, code) piu' volte
_NOTE: dict[tuple, np.ndarray] = {}
_NOTE_BYTES = 0
_NOTE_MAX = 300_000_000


def _nota(chiave: tuple, fai: Callable[[], np.ndarray]) -> np.ndarray:
    global _NOTE_BYTES
    y = _NOTE.pop(chiave, None)
    if y is None:
        y = fai()
        _NOTE_BYTES += y.nbytes
        while _NOTE and _NOTE_BYTES > _NOTE_MAX:
            _NOTE_BYTES -= _NOTE.pop(next(iter(_NOTE))).nbytes
    _NOTE[chiave] = y          # in fondo: usata di recente
    return y


_CODA_MAX_S = 8.0   # la coda piu' lunga di una nota dopo la fine (release, decadimento)


def _somma(out: np.ndarray, y: np.ndarray, s0: int) -> None:
    """Somma ``y`` in ``out`` a partire da ``s0`` (anche negativo: si taglia la parte prima)."""
    k = max(0, -s0)
    m = min(y.shape[-1], out.shape[-1] - s0)
    if m > k:
        out[:, s0 + k:s0 + m] += y[:, k:m]


def render_notes(kind: str, params: dict, notes: list[tuple[int, int, float, int]], length: int, sr: int,
                 loader: Callable | None = None, seed: int = 0, start: int = 0) -> np.ndarray:
    """Suona ``notes`` = [(inizio, durata, altezza, velocity)] in campioni assoluti.

    Restituisce (2, length) a partire dal campione ``start`` (0 = la canzone intera): un pezzo
    renderizzato cosi' e' identico allo stesso tratto del render completo (stessi semi).
    Le note che sforano la fine vengono troncate.
    """
    coda = int(sr * _CODA_MAX_S)
    p = merged(kind, params)
    pk = json.dumps(p, sort_keys=True, default=str)
    out = np.zeros((2, length), dtype=np.float64)
    # gli open hat suonano a parte: un hat chiuso li strozza (choke) senza toccare il resto
    aperti = np.zeros((2, length), dtype=np.float64) if kind == "drums" else None
    if not notes:
        return out.astype(np.float32)
    notes = sorted(notes, key=lambda n: (n[0], n[2]))
    cache: dict[tuple, np.ndarray] = {}
    hat_aperti: list[tuple[int, int]] = []   # (inizio, fine) degli open hat, per lo choke
    prec_pitch = None
    prec_fine = -1
    for i, (s0, dur, pitch, vel) in enumerate(notes):
        s0 = int(s0) - start            # da qui in poi: posizione dentro il pezzo
        if s0 >= length:
            continue
        dur = max(1, int(dur))
        if s0 + dur + coda < 0:         # finita (coda compresa) prima del pezzo
            if kind == "synth":
                prec_pitch, prec_fine = pitch, s0 + dur
            continue
        seme = _seme(seed, i, s0 + start, pitch)
        if kind == "synth":
            glide_da = prec_pitch if (p["glide"] > 0 and prec_fine >= s0 - 1) else None
            y = _nota(('synth', pk, pitch, vel, dur, sr, seme, glide_da), lambda: _synth_note(p, pitch, vel, dur, sr, seme, glide_da))
            prec_pitch, prec_fine = pitch, s0 + dur
        elif kind == "fm":
            y = _nota(('fm', pk, pitch, vel, dur, sr, seme), lambda: _fm_note(p, pitch, vel, dur, sr, seme))
        elif kind == "pluck":
            y = _nota(('pluck', pk, pitch, vel, dur, sr, seme), lambda: _pluck_note(p, pitch, vel, dur, sr, seme))
        elif kind == "drums":
            voce, pan = _KIT_MAP.get(int(pitch), ("perc", 0.0))
            vq = int(vel) // 8
            chiave = (voce, vq)
            if chiave not in cache:
                cache[chiave] = drum_voice(voce, vel, p, sr, _seme(seed, voce, vq))
            y = cache[chiave] * _vel_gain(vq * 8 + 4, p["velocity_sens"]) * _db(p["gain_db"]) * 0.8
            gl, gr = _pan_gains(pan * p["pan_spread"] / 0.3 if p["pan_spread"] else 0.0)
            y = y * np.array([[gl], [gr]])
            if int(pitch) in _HAT_CHOKE:
                for (a, b) in hat_aperti:
                    m = min(length, b) - s0
                    if a < s0 and m > 0:
                        k = max(0, -s0)
                        if m > k:
                            aperti[:, s0 + k:s0 + m] *= np.exp(-np.arange(k, m) / (0.004 * sr))
                hat_aperti = [(a, b) for (a, b) in hat_aperti if b > s0 and a >= s0]
            if int(pitch) in _HAT_OPEN:
                hat_aperti.append((s0, s0 + y.shape[-1]))
                _somma(aperti, y, s0)
                continue
        elif kind == "sampler":
            y = _sampler_note(p, pitch, vel, dur, sr, loader)
            if y is None:
                continue
        else:
            raise ValueError(f"unknown instrument type {kind!r}")
        _somma(out, y, s0)
    if aperti is not None:
        out += aperti
    if kind == "drums" and p["crush"]:
        out = _crush(out, p["crush"], sr)
    return out.astype(np.float32)
