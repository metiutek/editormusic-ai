"""Altezza della voce: inseguirla, correggerla, spostarla.

- ``f0_track``: frequenza fondamentale a frame (YIN di ``trascrivi``, a blocchi perche'
  la matrice dei frame di un brano intero non sta in memoria).
- ``autotune``: porta ogni frame intonato sulla nota piu' vicina della scala, con una
  velocita' di correzione (0 = effetto robotico, valori alti = naturale).
- ``psola``: cambio d'altezza nel tempo con grani sincroni al periodo (TD-PSOLA). Tiene
  le formanti al loro posto: la voce resta una voce e non diventa uno scoiattolo.
- ``pitch_shift``: per materiale qualsiasi (anche accordi): phase vocoder + ricampionamento.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import resample_poly

from .synth import _resample
from .trascrivi import yin

SR_ANALISI = 16000
HOP = 128           # 8 ms a 16 kHz
WIN = 1024


def f0_track(m: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 1000.0,
             soglia: float = 0.2, gate_db: float = -50.0) -> tuple[np.ndarray, float]:
    """Frequenza per frame (0 = non intonato) e durata di un frame in secondi."""
    m = np.asarray(m, dtype=np.float64)
    if sr != SR_ANALISI:
        m = resample_poly(m, SR_ANALISI, sr)
    blocco = 1500
    parti = []
    for s in range(0, max(0, len(m) - WIN) // HOP + 1, blocco):
        seg = m[s * HOP: s * HOP + blocco * HOP + WIN]
        if len(seg) <= WIN:
            break
        if not np.any(np.abs(seg) > 1e-5):
            parti.append(np.zeros((len(seg) - WIN) // HOP))
            continue
        f0, ap, rms = yin(seg, SR_ANALISI, fmin, fmax, HOP, WIN, soglia)
        voce = (ap < soglia * 1.5) & (rms > 10 ** (gate_db / 20)) & (f0 >= fmin) & (f0 <= fmax)
        parti.append(np.where(voce, f0, 0.0))
    f = np.concatenate(parti) if parti else np.zeros(0)
    # toglie i salti di un frame (errori d'ottava, attacchi)
    if len(f) > 4:
        lf = np.where(f > 0, np.log2(np.maximum(f, 1e-9)), 0.0)
        med = median_filter(lf, size=5, mode="nearest")
        salto = (f > 0) & (med > 1) & (np.abs(lf - med) >= 0.5)
        f = np.where(salto, 2 ** med, f)
        # isole intonate troppo corte = rumore
        on = f > 0
        cambi = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(np.int8), [0]])))
        for a, b in zip(cambi[::2], cambi[1::2]):
            if b - a < 4:
                f[a:b] = 0.0
    return f, HOP / SR_ANALISI


def correzione(f0: np.ndarray, dt: float, pcs: list[int], speed_ms: float, amount: float,
               humanize: float = 0.0) -> np.ndarray:
    """Semitoni da aggiungere per frame per arrivare sulla scala."""
    out = np.zeros_like(f0)
    voce = f0 > 0
    if not voce.any() or not pcs:
        return out
    midi = 69 + 12 * np.log2(np.where(voce, f0, 440.0) / 440.0)
    base = np.round(midi)
    cand = base[:, None] + np.arange(-6, 7)[None, :]
    ok = np.isin(np.mod(cand, 12).astype(int), list(pcs))
    dist = np.where(ok, np.abs(cand - midi[:, None]), np.inf)
    target = cand[np.arange(len(midi)), np.argmin(dist, axis=1)]
    grezza = np.where(voce, (target - midi) * float(amount), 0.0)
    # velocita': un polo per frame; a ogni nota nuova riparte da zero (si sente l'attacco)
    a = float(np.exp(-dt / (speed_ms / 1000.0))) if speed_ms > 0 else 0.0
    # humanize: le note lunghe tengono un po' della loro deriva
    tieni = float(np.clip(humanize, 0, 1))
    stato = 0.0
    prec_t = None
    for i in range(len(f0)):
        if not voce[i]:
            stato = 0.0
            prec_t = None
            continue
        if prec_t is not None and target[i] != prec_t:
            stato *= 0.5          # cambio nota: aggancio piu' rapido senza scatto
        prec_t = target[i]
        stato = a * stato + (1 - a) * grezza[i]
        out[i] = stato
    if tieni:
        dev = np.where(voce, midi - median_filter(midi, size=31, mode="nearest"), 0.0)
        out = out + dev * tieni * 0.5
    return out


def psola(x: np.ndarray, sr: int, f0: np.ndarray, dt: float, semitoni: np.ndarray) -> np.ndarray:
    """Cambia l'altezza della voce di ``semitoni`` (per frame) tenendo durata e formanti."""
    n = x.shape[-1]
    if n == 0 or not len(f0):
        return x
    t_fr = (np.arange(len(f0)) + 0.5) * dt * sr + WIN / 2 * sr / SR_ANALISI
    idx = np.clip(np.searchsorted(t_fr, np.arange(0, n, 64)), 0, len(f0) - 1)
    f_c = f0[idx]                       # ogni 64 campioni: basta e costa poco
    r_c = 2.0 ** (semitoni[idx] / 12.0)
    if not np.any((f_c > 0) & (np.abs(r_c - 1) > 1e-4)):
        return x
    # segni d'analisi: un periodo l'uno dall'altro dove c'e' voce, 10 ms altrove
    fermo = int(sr * 0.01)
    segni, periodi, rapporti = [], [], []
    t = 0
    while t < n:
        k = t // 64
        f = f_c[k]
        P = int(sr / f) if f > 0 else fermo
        segni.append(t)
        periodi.append(P)
        rapporti.append(r_c[k] if f > 0 else 1.0)
        t += P
    segni = np.asarray(segni)
    out = np.zeros_like(x, dtype=np.float64)
    peso = np.zeros(n)
    finestre: dict[int, np.ndarray] = {}
    ts = 0.0
    j = 0
    while ts < n:
        while j + 1 < len(segni) and abs(segni[j + 1] - ts) <= abs(segni[j] - ts):
            j += 1
        ta, P, r = int(segni[j]), periodi[j], rapporti[j]
        w = finestre.get(P)
        if w is None:
            w = finestre[P] = np.hanning(2 * P + 1)
        c = int(ts)
        a0, a1 = max(0, ta - P), min(n, ta + P + 1)
        s0 = c - (ta - a0)
        s1 = s0 + (a1 - a0)
        if s0 < 0:
            a0 -= s0
            s0 = 0
        if s1 > n:
            a1 -= s1 - n
            s1 = n
        if a1 > a0:
            ww = w[a0 - (ta - P): a1 - (ta - P)]
            out[:, s0:s1] += x[:, a0:a1] * ww
            peso[s0:s1] += ww
        ts += P / r
    return out / np.maximum(peso, 0.35)


def autotune(x: np.ndarray, sr: int, pcs: list[int], speed_ms: float = 20.0, amount: float = 1.0,
             humanize: float = 0.0, fmin: float = 70.0, fmax: float = 1000.0) -> np.ndarray:
    m = x.mean(axis=0)
    if not np.any(np.abs(m) > 1e-5):
        return x
    f0, dt = f0_track(m, sr, fmin, fmax)
    semi = correzione(f0, dt, pcs, speed_ms, amount, humanize)
    return psola(x, sr, f0, dt, semi)


def _stretch(x: np.ndarray, rate: float, nfft: int = 2048) -> np.ndarray:
    """Phase vocoder: stessa altezza, durata * rate. A blocchi di frame per la memoria."""
    ha = nfft // 4
    hs = max(1, int(round(ha * rate)))
    w = np.hanning(nfft)
    c, n = x.shape
    nfr = max(1, (n - nfft) // ha + 2)
    pad = np.pad(x, ((0, 0), (0, max(0, (nfr - 1) * ha + nfft - n))))
    omega = (2 * np.pi * np.arange(nfft // 2 + 1) * ha / nfft).astype(np.float32)
    m = (nfr - 1) * hs + nfft
    out = np.zeros((c, m))
    norm = np.zeros(m)
    w2 = w ** 2
    prec = None            # fase d'analisi dell'ultimo frame
    acc = None             # fase di sintesi accumulata
    blocco = 256
    for b0 in range(0, nfr, blocco):
        b1 = min(nfr, b0 + blocco)
        idx = np.arange(b0, b1)[:, None] * ha + np.arange(nfft)[None, :]
        S = np.fft.rfft(pad[:, idx] * w, axis=-1).astype(np.complex64)   # (C, B, F)
        fase = np.angle(S)
        prima = fase[:, :1] if prec is None else prec[:, None]
        dphi = np.diff(fase, axis=1, prepend=prima) - omega
        dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
        passo = ((omega + dphi) * (hs / ha)).astype(np.float64)
        if acc is None:
            passo[:, 0] = fase[:, 0]
            a = np.cumsum(passo, axis=1)
        else:
            a = acc[:, None] + np.cumsum(passo, axis=1)
        a = np.mod(a, 2 * np.pi)       # la fase cresce senza fine: si tiene piccola
        acc = a[:, -1]
        prec = fase[:, -1]
        a = a.astype(np.float32)
        fr = np.fft.irfft(np.abs(S) * (np.cos(a) + 1j * np.sin(a)), n=nfft, axis=-1) * w
        for k in range(b1 - b0):
            s0 = (b0 + k) * hs
            out[:, s0:s0 + nfft] += fr[:, k]
            norm[s0:s0 + nfft] += w2
    return out / np.maximum(norm, 1e-3)


def pitch_shift(x: np.ndarray, semitoni: float) -> np.ndarray:
    """Altezza diversa, stessa durata (per qualsiasi suono)."""
    if abs(semitoni) < 1e-3 or x.shape[-1] < 4096:
        return x
    r = 2.0 ** (semitoni / 12.0)
    y = _resample(_stretch(x, r), r)
    n = x.shape[-1]
    return y[:, :n] if y.shape[-1] >= n else np.pad(y, ((0, 0), (0, n - y.shape[-1])))
