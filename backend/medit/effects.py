"""Registro degli effetti: parametri, validazione, funzioni numpy.

Ogni effetto lavora su un buffer stereo ``(2, N)`` float64 e restituisce lo
stesso formato. ``ctx`` porta cio' che serve oltre ai parametri: ``bpm`` (per i
tempi in beat: delay, tremolo, pump), ``sr``, ``seed`` (il rumore del lofi ha
un seme: il render resta una funzione pura).

Automazione: i parametri elencati in ``automatable`` possono arrivare come
array lunghi quanto il buffer invece che come numeri. ``mix`` e' automatizzabile
in ogni effetto che lo ha (si calcola il bagnato pieno e poi si dosa).
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import fftconvolve, lfilter, resample_poly

from . import intonazione
from .synth import _pan_gains, biquad, filter_sweep
from .theory import SCALES, TheoryError, scale_pcs


def _db(x):
    return np.power(10.0, np.asarray(x, dtype=np.float64) / 20.0)


def _to_db(x):
    return 20.0 * np.log10(np.maximum(np.asarray(x, dtype=np.float64), 1e-9))


def _f(v) -> float:
    return float(np.mean(v)) if isinstance(v, np.ndarray) else float(v)


# --------------------------------------------------------------------------
# mattoni dinamici
# --------------------------------------------------------------------------


def envelope(level: np.ndarray, sr: int, attack_ms: float, release_ms: float, hop: int = 32) -> np.ndarray:
    """Inseguitore d'inviluppo con attacco e rilascio diversi.

    Il ciclo gira a ``sr/hop`` (≈1.4 kHz): veloce in Python, e per un compressore
    piu' fine di cosi' non si sente. Poi si interpola sui campioni.
    """
    n = level.shape[-1]
    if n == 0:
        return level
    m = (n + hop - 1) // hop
    pad = np.pad(level, (0, m * hop - n))
    blocchi = pad.reshape(m, hop).max(axis=1)
    fr = sr / hop
    a = np.exp(-1.0 / max(1e-4, attack_ms / 1000.0 * fr))
    r = np.exp(-1.0 / max(1e-4, release_ms / 1000.0 * fr))
    out = np.empty(m)
    e = 0.0
    for i, x in enumerate(blocchi.tolist()):
        e = (a * e + (1 - a) * x) if x > e else (r * e + (1 - r) * x)
        out[i] = e
    return np.interp(np.arange(n), np.arange(m) * hop + hop / 2, out)


def _tempo(n: int, sr: int, ctx: dict) -> np.ndarray:
    """Secondi dall'inizio della canzone: LFO e modulazioni restano a tempo anche quando
    si renderizza un pezzo solo (``ctx["t0"]`` = primo campione del pezzo)."""
    return (np.arange(n) + ctx.get("t0", 0)) / sr


def _gain_computer(level_db: np.ndarray, thr: float, ratio: float, knee: float) -> np.ndarray:
    """Riduzione di guadagno in dB (<= 0) con ginocchio morbido."""
    over = level_db - thr
    gr = np.zeros_like(over)
    if knee > 0:
        dentro = np.abs(over) <= knee / 2
        gr[dentro] = (1 / ratio - 1) * (over[dentro] + knee / 2) ** 2 / (2 * knee)
        sopra = over > knee / 2
        gr[sopra] = (1 / ratio - 1) * over[sopra]
    else:
        sopra = over > 0
        gr[sopra] = (1 / ratio - 1) * over[sopra]
    return gr


# --------------------------------------------------------------------------
# effetti
# --------------------------------------------------------------------------


def fx_gain(x, sr, p, ctx):
    g = _db(p["db"])
    out = x * g
    if p["pan"]:
        gl, gr = _pan_gains(p["pan"])
        out = out * np.array([[gl], [gr]])
    return out


def fx_eq(x, sr, p, ctx):
    y = x
    if p["low_cut"] > 0:
        b, a = biquad("highpass", p["low_cut"], 0.707, sr)
        y = lfilter(b, a, y, axis=-1)
        y = lfilter(b, a, y, axis=-1)   # 24 dB/oct
    if p["low_gain"]:
        b, a = biquad("lowshelf", p["low_freq"], 0.707, sr, p["low_gain"])
        y = lfilter(b, a, y, axis=-1)
    if p["mid_gain"]:
        b, a = biquad("peak", p["mid_freq"], p["mid_q"], sr, p["mid_gain"])
        y = lfilter(b, a, y, axis=-1)
    if p["mid2_gain"]:
        b, a = biquad("peak", p["mid2_freq"], p["mid2_q"], sr, p["mid2_gain"])
        y = lfilter(b, a, y, axis=-1)
    if p["high_gain"]:
        b, a = biquad("highshelf", p["high_freq"], 0.707, sr, p["high_gain"])
        y = lfilter(b, a, y, axis=-1)
    if p["high_cut"] > 0:
        b, a = biquad("lowpass", p["high_cut"], 0.707, sr)
        y = lfilter(b, a, y, axis=-1)
    return y


def _filtro(kind):
    def fx(x, sr, p, ctx):
        cut = p["cutoff"]
        y = filter_sweep(x, kind, np.clip(cut, 20, sr * 0.45) if isinstance(cut, np.ndarray) else cut, p["q"], sr)
        if p.get("steep"):
            y = filter_sweep(y, kind, np.clip(cut, 20, sr * 0.45) if isinstance(cut, np.ndarray) else cut, p["q"], sr)
        return y
    return fx


def fx_filter_lfo(x, sr, p, ctx):
    """Filtro che si apre e si chiude a tempo (wobble, sweep ritmico)."""
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    hz = ctx["bpm"] / 60.0 / max(1e-3, p["rate"])
    lfo = 0.5 * (1 - np.cos(2 * np.pi * hz * t))
    lo, hi = np.log2(max(20, p["min"])), np.log2(max(30, p["max"]))
    cut = 2 ** (lo + (hi - lo) * lfo)
    return filter_sweep(x, p["type"], cut, p["q"], sr, block=128)


def fx_compressor(x, sr, p, ctx):
    lev = np.abs(x).max(axis=0)
    env = envelope(lev, sr, p["attack_ms"], p["release_ms"])
    gr = _gain_computer(_to_db(env), p["threshold_db"], max(1.0, p["ratio"]), p["knee_db"])
    g = _db(gr + p["makeup_db"])
    return x * g


def fx_limiter(x, sr, p, ctx):
    """Limitatore con lookahead: il picco viene visto prima di arrivare."""
    y = x * _db(p["gain_db"])
    ceil = float(_db(p["ceiling_db"]))
    la = max(1, int(sr * 0.0015))
    # picco *vero*: si guarda il segnale sovracampionato 4x, cosi' anche i picchi fra
    # un campione e l'altro (quelli che un convertitore o un MP3 fanno uscire) restano sotto
    picco = np.abs(resample_poly(y, 4, 1, axis=-1)).max(axis=0)
    picco = picco[: (len(picco) // 4) * 4].reshape(-1, 4).max(axis=1)
    picco = np.pad(picco, (0, max(0, y.shape[-1] - len(picco))), mode="edge")[: y.shape[-1]]
    g_req = np.minimum(1.0, ceil / np.maximum(picco, 1e-9))
    # minimo su una finestra e poi media sulla stessa finestra: la curva scende *prima*
    # del picco, liscia, e in ogni punto resta sotto quello che serve
    w = 2 * la + 1
    g = uniform_filter1d(minimum_filter1d(g_req, size=w), size=w)
    # rilascio: la riduzione torna su lentamente
    env = envelope(1.0 / np.maximum(g, 1e-9), sr, 0.01, p["release_ms"], hop=16)
    g = np.minimum(g, 1.0 / np.maximum(env, 1.0))
    return np.clip(y * g, -ceil, ceil)


def fx_gate(x, sr, p, ctx):
    lev = np.abs(x).max(axis=0)
    env = envelope(lev, sr, 1.0, p["release_ms"])
    aperto = (_to_db(env) > p["threshold_db"]).astype(np.float64)
    a = np.exp(-1.0 / (0.002 * sr))
    g = lfilter([1 - a], [1, -a], aperto)
    floor = float(_db(-abs(p["range_db"])))
    return x * (floor + (1 - floor) * g)


def fx_deesser(x, sr, p, ctx):
    b, a = biquad("highpass", p["freq"], 0.707, sr)
    alto = lfilter(b, a, x, axis=-1)
    env = envelope(np.abs(alto).max(axis=0), sr, 1.0, 60.0)
    gr = _gain_computer(_to_db(env), p["threshold_db"], 4.0, 3.0)
    g = _db(np.maximum(gr, -abs(p["max_reduction_db"])))
    return x - alto + alto * g


def _ir(sr: int, decay: float, predelay_ms: float, damping: float, width: float, seed: int,
        early: float = 0.3) -> np.ndarray:
    """Risposta all'impulso sintetica: rumore che decade, sempre piu' scuro, decorrelato L/R."""
    rng = np.random.default_rng(seed)
    n = int(sr * min(8.0, decay * 1.1)) + 1
    t = np.arange(n) / sr
    inv = np.exp(-6.9 * t / max(0.05, decay))
    ir = rng.standard_normal((2, n)) * inv
    # smorzamento che cresce col tempo: tre bande incrociate
    if damping > 0:
        for f0, peso in ((8000 * (1 - damping) + 1500, 0.4), (3000 * (1 - damping) + 600, 0.6)):
            b, a = biquad("lowpass", f0, 0.6, sr)
            scuro = lfilter(b, a, ir, axis=-1)
            k = np.clip(t / max(0.05, decay * peso), 0, 1)
            ir = ir * (1 - k) + scuro * k
    # prime riflessioni
    for i in range(8):
        d = int(sr * (0.004 + rng.random() * 0.03))
        if d < n:
            ir[:, d] += early * rng.uniform(-1, 1, 2) * (1 - i / 8)
    if width < 1:
        m = ir.mean(axis=0)
        ir = m + (ir - m) * width
    pd = int(sr * predelay_ms / 1000.0)
    if pd:
        ir = np.concatenate([np.zeros((2, pd)), ir], axis=1)
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True).mean()) + 1e-9
    return ir


_IR_CACHE: dict[tuple, np.ndarray] = {}


def fx_reverb(x, sr, p, ctx):
    chiave = (sr, round(p["decay"], 3), round(p["predelay_ms"], 1), round(p["damping"], 3),
              round(_f(p["width"]), 3), int(ctx.get("seed", 0)) % 97)
    ir = _IR_CACHE.get(chiave)
    if ir is None:
        ir = _ir(sr, p["decay"], p["predelay_ms"], p["damping"], _f(p["width"]), chiave[-1])
        if len(_IR_CACHE) > 16:
            _IR_CACHE.pop(next(iter(_IR_CACHE)))
        _IR_CACHE[chiave] = ir
    src = x
    if p["low_cut"] > 0:
        b, a = biquad("highpass", p["low_cut"], 0.707, sr)
        src = lfilter(b, a, x, axis=-1)
    n = x.shape[-1]
    wet = np.stack([fftconvolve(src[0], ir[0])[:n], fftconvolve(src[1], ir[1])[:n]]) * 0.25
    return wet


def fx_delay(x, sr, p, ctx):
    passo = p["time_ms"] / 1000.0 if p["time_ms"] > 0 else p["time_beats"] * 60.0 / ctx["bpm"]
    d = max(1, int(passo * sr))
    n = x.shape[-1]
    fb = float(np.clip(p["feedback"], 0, 0.95))
    wet = np.zeros_like(x)
    eco = x.copy()
    b, a = biquad("lowpass", p["tone"], 0.707, sr) if p["tone"] < sr * 0.45 else (None, None)
    hb, ha = biquad("highpass", 120.0, 0.707, sr)
    k = 1
    g = 1.0
    while k * d < n and g > 1e-3 and k < 64:
        if b is not None:
            eco = lfilter(b, a, eco, axis=-1)
        eco = lfilter(hb, ha, eco, axis=-1)
        if p["ping_pong"]:
            eco = eco[::-1].copy()
        wet[:, k * d:] += eco[:, : n - k * d] * g
        g *= fb
        k += 1
    return wet


def _mod_delay(x, sr, ritardo_s: np.ndarray) -> np.ndarray:
    n = x.shape[-1]
    idx = np.arange(n) - ritardo_s * sr
    return np.interp(idx, np.arange(n), x, left=0.0)


def fx_chorus(x, sr, p, ctx):
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    base = p["delay_ms"] / 1000.0
    dep = p["depth_ms"] / 1000.0
    l = _mod_delay(x[0], sr, base + dep * 0.5 * (1 + np.sin(2 * np.pi * p["rate"] * t)))
    r = _mod_delay(x[1], sr, base + dep * 0.5 * (1 + np.sin(2 * np.pi * p["rate"] * t + np.pi / 2)))
    return np.stack([l, r])


def fx_flanger(x, sr, p, ctx):
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    rit = 0.0005 + p["depth_ms"] / 1000.0 * 0.5 * (1 + np.sin(2 * np.pi * p["rate"] * t))
    wet = np.stack([_mod_delay(c, sr, rit) for c in x])
    return x + wet * p["feedback"] if p["feedback"] else wet


def fx_distortion(x, sr, p, ctx):
    k = 1 + 30 * _f(p["drive"])
    m = p["mode"]
    if m == "hard":
        y = np.clip(x * k, -1, 1)
    elif m == "fold":
        y = np.sin(x * k * np.pi / 2)
    elif m == "tape":
        k = 1 + 4 * _f(p["drive"])
        y = np.tanh(x * k + 0.1 * (x * k) ** 2) / np.tanh(k)
        y = y - y.mean(axis=-1, keepdims=True)
    elif m == "fuzz":
        y = np.sign(x) * (1 - np.exp(-np.abs(x * k * 2)))
    else:
        y = np.tanh(x * k) / np.tanh(min(k, 3.0))
    if p["tone"] < sr * 0.45:
        b, a = biquad("lowpass", p["tone"], 0.707, sr)
        y = lfilter(b, a, y, axis=-1)
    return y * _db(p["output_db"])


def fx_bitcrusher(x, sr, p, ctx):
    q = 2 ** max(1.0, p["bits"])
    y = np.round(x * q) / q
    passo = max(1, int(p["downsample"]))
    if passo > 1:
        y = np.repeat(y[:, ::passo], passo, axis=1)[:, : x.shape[-1]]
    return y


def _lfo_beats(n, sr, bpm, rate_beats, shape="sine", phase=0.0, t0=0):
    t = (np.arange(n) + t0) / sr
    hz = bpm / 60.0 / max(1e-3, rate_beats)
    ph = (t * hz + phase) % 1.0
    if shape == "square":
        return (ph < 0.5).astype(np.float64)
    if shape == "triangle":
        return 1 - np.abs(2 * ph - 1)
    return 0.5 * (1 + np.sin(2 * np.pi * ph))


def fx_tremolo(x, sr, p, ctx):
    lfo = _lfo_beats(x.shape[-1], sr, ctx["bpm"], p["rate_beats"], p["shape"], t0=ctx.get("t0", 0))
    return x * (1 - p["depth"] * lfo)


def fx_autopan(x, sr, p, ctx):
    lfo = _lfo_beats(x.shape[-1], sr, ctx["bpm"], p["rate_beats"], t0=ctx.get("t0", 0)) * 2 - 1
    pan = lfo * p["depth"]
    th = (pan + 1) * np.pi / 4
    m = x.mean(axis=0)
    return np.stack([m * np.cos(th) * np.sqrt(2), m * np.sin(th) * np.sqrt(2)]) * 0.5 + x * 0.5


def fx_pump(x, sr, p, ctx):
    """Il 'pompaggio' del sidechain a tempo: il volume si abbassa a ogni battito e risale."""
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    passo = 60.0 / ctx["bpm"] * p["rate_beats"]
    ph = (t / passo) % 1.0
    # discesa in 1.5% del passo (niente click), poi risalita esponenziale
    curva = 1 - p["depth"] * np.clip(ph / 0.015, 0, 1) * np.exp(-ph / max(0.02, p["release"]) * 3.0)
    return x * curva


def fx_stereo_width(x, sr, p, ctx):
    m = (x[0] + x[1]) / 2
    s = (x[0] - x[1]) / 2
    w = p["width"]
    s = s * w
    if p["bass_mono"] > 0:
        b, a = biquad("highpass", p["bass_mono"], 0.707, sr)
        s = lfilter(b, a, s)
    return np.stack([m + s, m - s])


def fx_lofi(x, sr, p, ctx):
    """Nastro e vinile: oscillazione d'altezza, banda stretta, fruscio e crepitii."""
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    rng = np.random.default_rng(int(ctx.get("seed", 0)) + 7)
    y = x
    if p["wow"]:
        rit = 0.004 + 0.0015 * p["wow"] * (np.sin(2 * np.pi * 0.6 * t) + 0.3 * np.sin(2 * np.pi * 5.3 * t))
        y = np.stack([_mod_delay(c, sr, rit) for c in y])
    b, a = biquad("lowpass", p["tone"], 0.707, sr)
    y = lfilter(b, a, y, axis=-1)
    b, a = biquad("highpass", 90.0, 0.707, sr)
    y = lfilter(b, a, y, axis=-1)
    if p["noise"]:
        fr = rng.standard_normal((2, n)) * 0.02 * p["noise"]
        b, a = biquad("lowpass", 5000, 0.5, sr)
        y = y + lfilter(b, a, fr, axis=-1)
    if p["crackle"]:
        k = rng.random(n) < (p["crackle"] * 8 / sr)
        imp = np.zeros(n)
        imp[k] = rng.uniform(-0.3, 0.3, int(k.sum())) * p["crackle"]
        y = y + imp
    if p["saturation"]:
        kk = 1 + 3 * p["saturation"]
        y = np.tanh(y * kk) / np.tanh(kk)
    return y


def _pcs(p, ctx) -> list[int]:
    """Le note permesse dall'autotune: la tonalita' della canzone o quella scelta."""
    key = ctx.get("key", "C") if p["key"] == "song" else p["key"]
    mode = ctx.get("mode", "major") if p["scale"] == "song" else p["scale"]
    try:
        return scale_pcs(key, mode)
    except TheoryError:
        return list(range(12))


def fx_autotune(x, sr, p, ctx):
    """Correzione d'intonazione sulla scala, con le formanti al loro posto."""
    lo, hi = {"bass": (50.0, 400.0), "low": (70.0, 600.0), "high": (120.0, 1200.0)}.get(p["range"], (70.0, 1000.0))
    return intonazione.autotune(x, sr, _pcs(p, ctx), p["speed_ms"], p["amount"], p["humanize"], lo, hi)


def fx_pitch_shift(x, sr, p, ctx):
    semi = p["semitones"] + p["cents"] / 100.0
    if p["mode"] == "voice":
        f0, dt = intonazione.f0_track(x.mean(axis=0), sr)
        return intonazione.psola(x, sr, f0, dt, np.full(len(f0), semi))
    return intonazione.pitch_shift(x, semi)


def fx_doubler(x, sr, p, ctx):
    """Doppia ripresa finta: due copie un po' in ritardo e stonate, aperte ai lati."""
    n = x.shape[-1]
    t = _tempo(n, sr, ctx)
    m = x.mean(axis=0)
    base = p["delay_ms"] / 1000.0
    # una deriva lenta del ritardo = un leggero cambio d'altezza, come una seconda voce
    dep = p["detune"] * 0.004
    l = _mod_delay(m, sr, base + dep * (0.5 + 0.5 * np.sin(2 * np.pi * 0.31 * t)))
    r = _mod_delay(m, sr, base * 1.37 + dep * (0.5 + 0.5 * np.sin(2 * np.pi * 0.23 * t + 1.3)))
    w = p["width"]
    return np.stack([x[0] + l * (0.5 + 0.5 * w) + r * (0.5 - 0.5 * w),
                     x[1] + r * (0.5 + 0.5 * w) + l * (0.5 - 0.5 * w)]) * 0.7


def fx_phaser(x, sr, p, ctx):
    """Phaser: catena di passa-tutto che si sposta con un LFO."""
    n = x.shape[-1]
    stadi = int(p["stages"])
    rate = p["rate"] if p["rate_beats"] <= 0 else ctx["bpm"] / 60.0 / p["rate_beats"]
    blocco = 128
    t = (np.arange(0, n, blocco) + ctx.get("t0", 0)) / sr
    lo, hi = np.log2(max(20, p["min"])), np.log2(max(40, p["max"]))
    fc = 2 ** (lo + (hi - lo) * 0.5 * (1 - np.cos(2 * np.pi * rate * t)))
    tn = np.tan(np.pi * np.clip(fc, 20, sr * 0.45) / sr)
    coef = (tn - 1) / (tn + 1)
    out = np.empty_like(x)
    zi = np.zeros((x.shape[0], stadi))
    fb = float(p["feedback"])
    prec = np.zeros(x.shape[0])
    for i, c in enumerate(coef.tolist()):
        a0, a1 = i * blocco, min(n, (i + 1) * blocco)
        b = np.array([1.0])
        a = np.array([1.0])
        for _ in range(stadi):
            b = np.convolve(b, [c, 1.0])
            a = np.convolve(a, [1.0, c])
        out[:, a0:a1], zi = lfilter(b, a, x[:, a0:a1] + fb * prec[:, None], axis=-1, zi=zi)
        prec = out[:, a1 - 1]
    return (x + out) * 0.5


def fx_exciter(x, sr, p, ctx):
    """Exciter: armoniche nuove sugli acuti (aria, presenza) senza alzare l'EQ."""
    b, a = biquad("highpass", p["freq"], 0.707, sr)
    alto = lfilter(b, a, x, axis=-1)
    k = 1 + 8 * p["drive"]
    sat = np.tanh(alto * k) / np.tanh(k) - alto
    return x + lfilter(b, a, sat, axis=-1) * p["amount"] * 2.0


def fx_transient(x, sr, p, ctx):
    """Transient shaper: piu' (o meno) colpo e piu' (o meno) coda, senza soglia."""
    lev = np.abs(x).max(axis=0)
    veloce = envelope(lev, sr, 0.5, 40.0, hop=16)
    lento = envelope(lev, sr, 25.0, 250.0, hop=16)
    att = np.clip(_to_db(veloce) - _to_db(lento), 0, 24) / 24.0
    sus = np.clip(_to_db(lento) - _to_db(veloce), 0, 24) / 24.0
    g = _db(p["attack"] * att * 2.0 + p["sustain"] * sus * 2.0)
    return x * uniform_filter1d(g, size=max(1, int(sr * 0.001))) * _db(p["output_db"])


def _bande(x, sr, f1, f2):
    """Tre bande che sommate ridanno il segnale."""
    def lr(kind, f, y):
        b, a = biquad(kind, f, 0.707, sr)
        return lfilter(b, a, lfilter(b, a, y, axis=-1), axis=-1)
    basso = lr("lowpass", f1, x)
    resto = x - basso
    medio = lr("lowpass", f2, resto)
    return basso, medio, resto - medio


def fx_multiband(x, sr, p, ctx):
    """Compressore a tre bande: bassi, medi e alti tenuti ciascuno per conto suo."""
    out = np.zeros_like(x)
    for nome, y in zip(("low", "mid", "high"), _bande(x, sr, p["low_freq"], p["high_freq"])):
        env = envelope(np.abs(y).max(axis=0), sr, p["attack_ms"], p["release_ms"])
        gr = _gain_computer(_to_db(env), p[f"{nome}_threshold_db"], max(1.0, p["ratio"]), 6.0)
        out += y * _db(gr + p[f"{nome}_gain_db"])
    return out


_GEQ = (31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def _geq_nome(f: int) -> str:
    return f"g{f // 1000}k" if f >= 1000 else f"g{f}"


def fx_graphic_eq(x, sr, p, ctx):
    y = x
    for f in _GEQ:
        g = p[_geq_nome(f)]
        if g and f < sr * 0.45:
            b, a = biquad("peak", float(f), 1.4, sr, g)
            y = lfilter(b, a, y, axis=-1)
    return y * _db(p["output_db"])


def fx_ring_mod(x, sr, p, ctx):
    t = _tempo(x.shape[-1], sr, ctx)
    return x * np.sin(2 * np.pi * p["freq"] * t)


def fx_vibrato(x, sr, p, ctx):
    t = _tempo(x.shape[-1], sr, ctx)
    rit = 0.003 + p["depth"] * 0.002 * 0.5 * (1 + np.sin(2 * np.pi * p["rate"] * t))
    return np.stack([_mod_delay(c, sr, rit) for c in x])


# --------------------------------------------------------------------------
# registro
# --------------------------------------------------------------------------


def _P(default, lo=None, hi=None, desc="", unit="", type_="float", choices=None):
    d: dict[str, Any] = {"type": type_, "default": default, "desc": desc}
    if lo is not None:
        d["min"] = lo
    if hi is not None:
        d["max"] = hi
    if unit:
        d["unit"] = unit
    if choices:
        d["choices"] = list(choices)
    return d


MIX = _P(1.0, 0, 1, "dry/wet: 0 = only dry, 1 = only effect")
_NOTE_CHOICES = ("song", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_SCALE_CHOICES = ("song",) + tuple(SCALES)

REGISTRY: dict[str, dict[str, Any]] = {
    "gain": {"fn": fx_gain, "group": "utility", "desc": "Level and balance.",
             "params": {"db": _P(0.0, -60, 24, "gain", "dB"), "pan": _P(0.0, -1, 1, "balance -1 left, 1 right")},
             "automatable": ["db"]},
    "eq": {"fn": fx_eq, "group": "tone", "desc": "Parametric EQ: low cut, low shelf, two bells, high shelf, high cut.",
           "params": {"low_cut": _P(0.0, 0, 1000, "high-pass (0 = off)", "Hz"),
                      "low_gain": _P(0.0, -18, 18, "low shelf gain", "dB"), "low_freq": _P(120.0, 30, 600, "low shelf", "Hz"),
                      "mid_gain": _P(0.0, -18, 18, "bell 1 gain", "dB"), "mid_freq": _P(800.0, 80, 12000, "bell 1", "Hz"),
                      "mid_q": _P(1.0, 0.2, 12, "bell 1 width (Q)"),
                      "mid2_gain": _P(0.0, -18, 18, "bell 2 gain", "dB"), "mid2_freq": _P(3000.0, 80, 16000, "bell 2", "Hz"),
                      "mid2_q": _P(1.0, 0.2, 12, "bell 2 width (Q)"),
                      "high_gain": _P(0.0, -18, 18, "high shelf gain", "dB"), "high_freq": _P(8000.0, 1500, 18000, "high shelf", "Hz"),
                      "high_cut": _P(0.0, 0, 22000, "low-pass (0 = off)", "Hz")}},
    "lowpass": {"fn": _filtro("lowpass"), "group": "tone", "desc": "Low-pass filter (darker). Automate cutoff for sweeps.",
                "params": {"cutoff": _P(2000.0, 20, 20000, "cutoff", "Hz"), "q": _P(0.707, 0.3, 12, "resonance"),
                           "steep": _P(False, desc="24 dB/oct instead of 12", type_="bool")},
                "automatable": ["cutoff"]},
    "highpass": {"fn": _filtro("highpass"), "group": "tone", "desc": "High-pass filter (thinner, removes rumble).",
                 "params": {"cutoff": _P(100.0, 20, 20000, "cutoff", "Hz"), "q": _P(0.707, 0.3, 12, "resonance"),
                            "steep": _P(False, desc="24 dB/oct instead of 12", type_="bool")},
                 "automatable": ["cutoff"]},
    "bandpass": {"fn": _filtro("bandpass"), "group": "tone", "desc": "Band-pass (telephone, radio).",
                 "params": {"cutoff": _P(1200.0, 40, 16000, "center", "Hz"), "q": _P(1.0, 0.3, 12, "width"),
                            "steep": _P(False, desc="steeper", type_="bool")},
                 "automatable": ["cutoff"]},
    "filter_lfo": {"fn": fx_filter_lfo, "group": "modulation", "desc": "Filter swept by a tempo-synced LFO (wobble).",
                   "params": {"type": _P("lowpass", desc="filter type", type_="choice", choices=("lowpass", "highpass", "bandpass")),
                              "rate": _P(1.0, 0.0625, 16, "one sweep every N beats", "beats"),
                              "min": _P(300.0, 20, 20000, "lowest cutoff", "Hz"), "max": _P(4000.0, 20, 20000, "highest cutoff", "Hz"),
                              "q": _P(2.0, 0.3, 12, "resonance"), "mix": MIX}},
    "compressor": {"fn": fx_compressor, "group": "dynamics", "desc": "Compressor: evens out the level.",
                   "params": {"threshold_db": _P(-18.0, -60, 0, "threshold", "dB"), "ratio": _P(3.0, 1, 30, "ratio"),
                              "attack_ms": _P(10.0, 0.1, 300, "attack", "ms"), "release_ms": _P(120.0, 5, 2000, "release", "ms"),
                              "knee_db": _P(6.0, 0, 24, "soft knee", "dB"), "makeup_db": _P(0.0, -12, 24, "make-up gain", "dB"),
                              "mix": MIX}},
    "limiter": {"fn": fx_limiter, "group": "dynamics", "desc": "Brick-wall limiter with look-ahead: last on the master.",
                "params": {"gain_db": _P(0.0, -12, 24, "input gain (push into the limiter)", "dB"),
                           "ceiling_db": _P(-1.0, -12, 0, "output ceiling", "dB"),
                           "release_ms": _P(80.0, 5, 1000, "release", "ms")}},
    "gate": {"fn": fx_gate, "group": "dynamics", "desc": "Noise gate: silences what is under the threshold.",
             "params": {"threshold_db": _P(-45.0, -90, 0, "threshold", "dB"), "release_ms": _P(80.0, 5, 2000, "release", "ms"),
                        "range_db": _P(60.0, 0, 90, "how much it closes", "dB")}},
    "deesser": {"fn": fx_deesser, "group": "dynamics", "desc": "De-esser: tames harsh 's' sounds on vocals.",
                "params": {"freq": _P(6000.0, 2000, 12000, "where the sibilance is", "Hz"),
                           "threshold_db": _P(-28.0, -60, 0, "threshold", "dB"),
                           "max_reduction_db": _P(9.0, 0, 24, "max reduction", "dB")}},
    "reverb": {"fn": fx_reverb, "group": "space", "desc": "Reverb (room, hall, plate). Best on a bus via a send.",
               "params": {"decay": _P(1.8, 0.1, 8, "decay time (RT60)", "s"),
                          "predelay_ms": _P(20.0, 0, 200, "pre-delay", "ms"),
                          "damping": _P(0.5, 0, 1, "0 bright, 1 dark"), "width": _P(1.0, 0, 1, "stereo width"),
                          "low_cut": _P(200.0, 0, 1000, "keep the lows out of the reverb", "Hz"),
                          "mix": _P(0.25, 0, 1, "dry/wet (on a bus use 1)")},
               "automatable": ["mix"]},
    "delay": {"fn": fx_delay, "group": "space", "desc": "Echo synced to the tempo (0.75 beats = dotted eighth).",
              "params": {"time_beats": _P(0.75, 0.0625, 8, "echo time", "beats"),
                         "time_ms": _P(0.0, 0, 3000, "fixed time instead of beats (0 = synced)", "ms"),
                         "feedback": _P(0.35, 0, 0.95, "how many repeats"), "tone": _P(6000.0, 500, 22050, "repeats get darker", "Hz"),
                         "ping_pong": _P(False, desc="bounce left/right", type_="bool"),
                         "mix": _P(0.25, 0, 1, "dry/wet")},
              "automatable": ["mix"]},
    "chorus": {"fn": fx_chorus, "group": "modulation", "desc": "Chorus: thick, wide, shimmering.",
               "params": {"rate": _P(0.8, 0.05, 8, "speed", "Hz"), "depth_ms": _P(3.0, 0, 15, "depth", "ms"),
                          "delay_ms": _P(12.0, 1, 40, "base delay", "ms"), "mix": _P(0.4, 0, 1, "dry/wet")}},
    "flanger": {"fn": fx_flanger, "group": "modulation", "desc": "Flanger: jet sweep.",
                "params": {"rate": _P(0.25, 0.02, 5, "speed", "Hz"), "depth_ms": _P(2.5, 0.1, 10, "depth", "ms"),
                           "feedback": _P(0.0, 0, 0.9, "intensity"), "mix": _P(0.5, 0, 1, "dry/wet")}},
    "distortion": {"fn": fx_distortion, "group": "color", "desc": "Saturation and distortion: soft, tape, hard, fuzz, fold.",
                   "params": {"drive": _P(0.3, 0, 1, "amount"), "mode": _P("soft", desc="character", type_="choice",
                                                                           choices=("soft", "tape", "hard", "fuzz", "fold")),
                              "tone": _P(12000.0, 500, 22050, "low-pass after the distortion", "Hz"),
                              "output_db": _P(-3.0, -24, 12, "output level", "dB"), "mix": MIX}},
    "bitcrusher": {"fn": fx_bitcrusher, "group": "color", "desc": "Bit crusher: digital grit.",
                   "params": {"bits": _P(8.0, 1, 16, "bit depth"), "downsample": _P(4.0, 1, 32, "sample-rate reduction"),
                              "mix": MIX}},
    "lofi": {"fn": fx_lofi, "group": "color", "desc": "Lo-fi tape/vinyl: wobble, dull top, hiss and crackle.",
             "params": {"wow": _P(0.5, 0, 1, "pitch wobble"), "tone": _P(5000.0, 1000, 16000, "top end", "Hz"),
                        "noise": _P(0.3, 0, 1, "hiss"), "crackle": _P(0.3, 0, 1, "vinyl crackle"),
                        "saturation": _P(0.3, 0, 1, "tape saturation"), "mix": MIX}},
    "tremolo": {"fn": fx_tremolo, "group": "modulation", "desc": "Tremolo synced to the tempo.",
                "params": {"rate_beats": _P(0.5, 0.0625, 8, "one cycle every N beats", "beats"),
                           "depth": _P(0.5, 0, 1, "depth"),
                           "shape": _P("sine", desc="LFO shape", type_="choice", choices=("sine", "triangle", "square"))}},
    "autopan": {"fn": fx_autopan, "group": "modulation", "desc": "Auto-pan synced to the tempo.",
                "params": {"rate_beats": _P(2.0, 0.125, 16, "one cycle every N beats", "beats"),
                           "depth": _P(0.6, 0, 1, "depth")}},
    "pump": {"fn": fx_pump, "group": "dynamics", "desc": "Sidechain-style pumping synced to the beat (EDM, house).",
             "params": {"rate_beats": _P(1.0, 0.25, 4, "duck every N beats", "beats"),
                        "depth": _P(0.6, 0, 1, "how deep"), "release": _P(0.3, 0.05, 1, "how fast it comes back (fraction of the step)")}},
    "stereo_width": {"fn": fx_stereo_width, "group": "space", "desc": "Stereo width (0 = mono) and mono low end.",
                     "params": {"width": _P(1.0, 0, 2, "0 mono, 1 unchanged, 2 extra wide"),
                                "bass_mono": _P(0.0, 0, 300, "make everything below this mono (0 = off)", "Hz")},
                     "automatable": ["width"]},
    "autotune": {"fn": fx_autotune, "group": "pitch",
                 "desc": "Auto-Tune: snaps the voice to the song's scale. Speed 0 = robotic, 20-50 ms = natural.",
                 "params": {"key": _P("song", desc="key (song = the song's key)", type_="choice", choices=_NOTE_CHOICES),
                            "scale": _P("song", desc="scale (song = the song's mode)", type_="choice", choices=_SCALE_CHOICES),
                            "speed_ms": _P(20.0, 0, 400, "retune speed: 0 = hard/robotic", "ms"),
                            "amount": _P(1.0, 0, 1, "how much to correct"),
                            "humanize": _P(0.0, 0, 1, "keep some natural drift on long notes"),
                            "range": _P("voice", desc="singer range", type_="choice", choices=("voice", "bass", "low", "high")),
                            "mix": MIX}},
    "pitch_shift": {"fn": fx_pitch_shift, "group": "pitch", "desc": "Pitch shift, same length. Voice mode keeps the formants.",
                    "params": {"semitones": _P(0.0, -24, 24, "shift", "st"), "cents": _P(0.0, -100, 100, "fine", "cents"),
                               "mode": _P("any", desc="any sound, or a single voice (more natural)", type_="choice",
                                          choices=("any", "voice")),
                               "mix": MIX}},
    "vibrato": {"fn": fx_vibrato, "group": "pitch", "desc": "Vibrato: pitch wobble.",
                "params": {"rate": _P(5.5, 0.5, 12, "speed", "Hz"), "depth": _P(0.4, 0, 1, "depth"), "mix": MIX}},
    "doubler": {"fn": fx_doubler, "group": "space", "desc": "Fake double-tracking: thicker, wider vocals and guitars.",
                "params": {"delay_ms": _P(18.0, 5, 60, "delay of the copies", "ms"), "detune": _P(0.5, 0, 1, "detune"),
                           "width": _P(0.8, 0, 1, "stereo spread"), "mix": _P(0.5, 0, 1, "dry/wet")}},
    "phaser": {"fn": fx_phaser, "group": "modulation", "desc": "Phaser: swirling notches.",
               "params": {"rate": _P(0.4, 0.02, 8, "speed", "Hz"),
                          "rate_beats": _P(0.0, 0, 32, "sync: one sweep every N beats (0 = use Hz)", "beats"),
                          "stages": _P(4.0, 2, 8, "allpass stages"), "min": _P(300.0, 20, 5000, "lowest", "Hz"),
                          "max": _P(3000.0, 100, 16000, "highest", "Hz"), "feedback": _P(0.3, 0, 0.9, "intensity"),
                          "mix": _P(0.6, 0, 1, "dry/wet")}},
    "ring_mod": {"fn": fx_ring_mod, "group": "color", "desc": "Ring modulator: metallic, robotic tones.",
                 "params": {"freq": _P(30.0, 1, 5000, "carrier", "Hz"), "mix": _P(0.5, 0, 1, "dry/wet")}},
    "exciter": {"fn": fx_exciter, "group": "tone", "desc": "Exciter: adds air and presence with new harmonics.",
                "params": {"freq": _P(3000.0, 800, 12000, "from this frequency up", "Hz"),
                           "drive": _P(0.5, 0, 1, "harmonics"), "amount": _P(0.3, 0, 1, "how much")}},
    "graphic_eq": {"fn": fx_graphic_eq, "group": "tone", "desc": "10-band graphic EQ (31 Hz - 16 kHz).",
                   "params": {**{_geq_nome(f): _P(0.0, -12, 12, f"{f} Hz" if f < 1000 else f"{f // 1000} kHz", "dB")
                                 for f in _GEQ},
                              "output_db": _P(0.0, -12, 12, "output level", "dB")}},
    "transient": {"fn": fx_transient, "group": "dynamics", "desc": "Transient shaper: more/less punch and tail.",
                  "params": {"attack": _P(3.0, -12, 12, "punch", "dB"), "sustain": _P(0.0, -12, 12, "tail", "dB"),
                             "output_db": _P(0.0, -12, 12, "output level", "dB")}},
    "multiband": {"fn": fx_multiband, "group": "dynamics", "desc": "3-band compressor: lows, mids and highs separately.",
                  "params": {"low_freq": _P(200.0, 40, 1000, "low/mid split", "Hz"),
                             "high_freq": _P(3000.0, 1000, 12000, "mid/high split", "Hz"),
                             "low_threshold_db": _P(-20.0, -60, 0, "low threshold", "dB"),
                             "mid_threshold_db": _P(-20.0, -60, 0, "mid threshold", "dB"),
                             "high_threshold_db": _P(-20.0, -60, 0, "high threshold", "dB"),
                             "ratio": _P(3.0, 1, 20, "ratio"), "attack_ms": _P(10.0, 0.1, 200, "attack", "ms"),
                             "release_ms": _P(150.0, 5, 2000, "release", "ms"),
                             "low_gain_db": _P(0.0, -12, 12, "low make-up", "dB"),
                             "mid_gain_db": _P(0.0, -12, 12, "mid make-up", "dB"),
                             "high_gain_db": _P(0.0, -12, 12, "high make-up", "dB"),
                             "mix": MIX}},
}

AUTOMATABLE = {k: list(v.get("automatable", [])) + (["mix"] if "mix" in v["params"] else [])
               for k, v in REGISTRY.items()}


def describe() -> list[dict]:
    out = []
    for name, spec in REGISTRY.items():
        out.append({"name": name, "group": spec["group"], "desc": spec["desc"],
                    "params": {k: {kk: vv for kk, vv in p.items()} for k, p in spec["params"].items()},
                    "automatable": AUTOMATABLE[name]})
    return out


def validate(name: str, params: dict | None, partial: bool = False) -> dict:
    if name not in REGISTRY:
        raise ValueError(f"unknown effect {name!r}; available: {', '.join(REGISTRY)}")
    spec = REGISTRY[name]["params"]
    out = {} if partial else {k: p["default"] for k, p in spec.items()}
    for k, v in (params or {}).items():
        if k not in spec:
            raise ValueError(f"effect {name} has no parameter {k!r}; parameters: {', '.join(spec)}")
        p = spec[k]
        if p["type"] == "bool":
            v = bool(v)
        elif p["type"] == "choice":
            if v not in p["choices"]:
                raise ValueError(f"{name}.{k} must be one of {', '.join(p['choices'])}")
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{name}.{k} must be a number") from None
            lo, hi = p.get("min"), p.get("max")
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                raise ValueError(f"{name}.{k}={v} out of range [{lo}, {hi}]")
        out[k] = v
    return out


def apply(name: str, x: np.ndarray, sr: int, params: dict, ctx: dict,
          curves: dict[str, np.ndarray] | None = None) -> np.ndarray:
    """Applica un effetto (con le eventuali curve di automazione)."""
    spec = REGISTRY[name]
    p = {k: d["default"] for k, d in spec["params"].items()}
    p.update(params or {})
    curves = curves or {}
    for k, arr in curves.items():
        if k in AUTOMATABLE[name] and k != "mix":
            p[k] = arr
    fn: Callable = spec["fn"]
    if "mix" in spec["params"]:
        mix = curves.get("mix", p["mix"])
        if not isinstance(mix, np.ndarray) and mix <= 0:
            return x
        wet = fn(x, sr, {**p, "mix": 1.0}, ctx)
        if not isinstance(mix, np.ndarray) and mix >= 1:
            return wet
        return x * (1 - mix) + wet * mix
    return fn(x, sr, p, ctx)
