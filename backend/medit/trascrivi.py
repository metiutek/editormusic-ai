"""Audio -> note MIDI, in numpy e basta.

- ``melody``: una linea alla volta (voce, fischio, canticchiato, basso,
  strumento solista). Altezza con YIN (de Cheveigne' & Kawahara 2002) a frame,
  poi segmentazione in note stabili. Canticchiare una melodia e averla nel piano
  roll.
- ``drums``: attacchi (flusso spettrale) classificati per banda: basse = cassa,
  medie con rumore = rullante, alte = charleston. Beatbox -> batteria.

Le note escono in secondi dall'inizio dell'audio; ``Store`` le porta in beat.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter


def _mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x.mean(axis=0) if x.ndim == 2 else x


def yin(m: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 1000.0, hop: int = 256,
        win: int = 2048, soglia: float = 0.15) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per frame: frequenza (0 = non intonato), aperiodicita', RMS."""
    n = (len(m) - win) // hop
    if n <= 0:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    idx = np.arange(n)[:, None] * hop + np.arange(win)[None, :]
    fr = m[idx]
    rms = np.sqrt((fr ** 2).mean(axis=1))
    tau_max = min(win // 2, int(sr / fmin) + 2)
    tau_min = max(2, int(sr / fmax))
    # funzione differenza via autocorrelazione FFT
    W = win // 2
    F = np.fft.rfft(fr, n=2 * win, axis=1)
    ac = np.fft.irfft(F * np.conj(F), axis=1)[:, :tau_max]
    cs = np.cumsum(np.concatenate([np.zeros((n, 1)), fr ** 2], axis=1), axis=1)
    e0 = cs[:, W] - cs[:, 0]
    taus = np.arange(tau_max)
    etau = cs[:, np.minimum(W + taus, win)] - cs[:, taus]
    d = e0[:, None] + etau - 2 * ac
    d[:, 0] = 0
    cum = np.cumsum(d[:, 1:], axis=1) / np.arange(1, tau_max)[None, :]
    dn = np.ones_like(d)
    dn[:, 1:] = d[:, 1:] / np.maximum(cum, 1e-12)
    f0 = np.zeros(n)
    ap = np.ones(n)
    for i in range(n):
        riga = dn[i, tau_min:tau_max]
        sotto = np.nonzero(riga < soglia)[0]
        if len(sotto):
            k = sotto[0]
            while k + 1 < len(riga) and riga[k + 1] < riga[k]:
                k += 1
        else:
            k = int(np.argmin(riga))
        t = k + tau_min
        ap[i] = riga[k]
        if 1 <= t < tau_max - 1:
            a, b, c = dn[i, t - 1], dn[i, t], dn[i, t + 1]
            den = a - 2 * b + c
            t = t + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
        f0[i] = sr / t if t > 0 else 0.0
    return f0, ap, rms


def melody(x: np.ndarray, sr: int, min_note: float = 0.08, fmin: float = 60.0, fmax: float = 1000.0,
           gate_db: float = -45.0) -> list[dict]:
    """Note di una linea monofonica: [{"pitch", "start", "length", "velocity"}] in secondi."""
    m = _mono(x)
    if sr > 22050:
        from scipy.signal import resample_poly

        m = resample_poly(m, 22050, sr)
        sr = 22050
    hop = 256
    f0, ap, rms = yin(m, sr, fmin, fmax, hop)
    if not len(f0):
        return []
    picco = rms.max() + 1e-12
    voce = (ap < 0.25) & (20 * np.log10(rms / picco + 1e-12) > gate_db) & (f0 > 0)
    midi = np.where(voce, 69 + 12 * np.log2(np.maximum(f0, 1e-6) / 440.0), np.nan)
    # mediana sui frame intonati: via gli scatti di ottava isolati
    piena = np.where(np.isnan(midi), 0, midi)
    liscia = median_filter(piena, size=5)
    midi = np.where(voce, liscia, np.nan)
    dt = hop / sr
    note = []
    i = 0
    n = len(midi)
    while i < n:
        if np.isnan(midi[i]):
            i += 1
            continue
        p = int(round(midi[i]))
        j = i
        while j + 1 < n and not np.isnan(midi[j + 1]) and abs(midi[j + 1] - p) < 0.6:
            j += 1
        durata = (j - i + 1) * dt
        if durata >= min_note:
            seg = midi[i:j + 1]
            altezza = int(round(float(np.median(seg))))
            vel = int(np.clip(40 + 87 * (rms[i:j + 1].max() / picco) ** 0.5, 1, 127))
            note.append({"pitch": altezza, "start": round(i * dt + 1024 / sr, 4), "length": round(durata, 4),
                         "velocity": vel})
        i = j + 1
    # note uguali separate da un buco piccolissimo: una sola
    unite: list[dict] = []
    for nt in note:
        if unite and unite[-1]["pitch"] == nt["pitch"] and nt["start"] - (unite[-1]["start"] + unite[-1]["length"]) < 0.04:
            unite[-1]["length"] = round(nt["start"] + nt["length"] - unite[-1]["start"], 4)
        else:
            unite.append(nt)
    return unite


def drums(x: np.ndarray, sr: int, sensitivity: float = 0.5) -> list[dict]:
    """Colpi percussivi -> kick 36 / snare 38 / hat 42, in secondi."""
    nfft, hop = 1024, 256
    # silenzio in testa: anche un colpo a t=0 ha un "prima" da cui salire
    m = np.concatenate([np.zeros(nfft), _mono(x)])
    n = (len(m) - nfft) // hop
    if n < 3:
        return []
    idx = np.arange(n)[:, None] * hop + np.arange(nfft)[None, :]
    S = np.log1p(np.abs(np.fft.rfft(m[idx] * np.hanning(nfft), axis=1)) * 100)
    f = np.fft.rfftfreq(nfft, 1 / sr)
    # attacchi cercati banda per banda: sommando tutto, i piatti (tante frequenze)
    # coprirebbero la cassa (poche frequenze basse)
    bande = {36: f < 150, 38: (f >= 150) & (f < 2500), 42: f >= 5000}
    soglia = 0.45 - 0.3 * float(np.clip(sensitivity, 0, 1))
    colpi: dict[int, list[tuple[int, float]]] = {}
    for p, maschera in bande.items():
        fl = np.concatenate([[0.0], np.maximum(0, np.diff(S[:, maschera], axis=0)).sum(axis=1)])
        top = fl.max()
        if top <= 0:
            continue
        fl = fl / top
        ultimo = -10
        for i in range(1, n - 1):
            if fl[i] > soglia and fl[i] >= fl[i - 1] and fl[i] >= fl[i + 1] and i - ultimo > 3:
                ultimo = i
                colpi.setdefault(p, []).append((i, float(fl[i])))
    # cassa e rullante insieme sono quasi sempre uno solo che sporca la banda vicina: decide
    # l'energia vera (lineare) del frame dopo l'attacco, bassi contro medi
    P = np.expm1(S) ** 2
    e_bassi = P[:, bande[36]].sum(axis=1)
    e_medi = P[:, bande[38]].sum(axis=1)
    casse, rull = colpi.get(36, []), colpi.get(38, [])
    via_c, via_r = set(), set()
    for a, (i, _) in enumerate(casse):
        for b, (j, _) in enumerate(rull):
            if abs(i - j) <= 2:
                k = min(n - 1, max(i, j) + 1)
                (via_r if e_bassi[k] > e_medi[k] else via_c).add(b if e_bassi[k] > e_medi[k] else a)
    colpi[36] = [x for a, x in enumerate(casse) if a not in via_c]
    colpi[38] = [x for b, x in enumerate(rull) if b not in via_r]
    # il rumore del rullante sale anche negli alti: un "charleston" insieme a un rullante e' il rullante
    rullanti = [i for i, _ in colpi.get(38, [])]
    colpi[42] = [(i, v) for i, v in colpi.get(42, []) if not any(abs(i - r) <= 2 for r in rullanti)]
    note = []
    for p, lista in colpi.items():
        for i, v in lista:
            note.append({"pitch": p, "start": round(max(0.0, i * hop / sr), 4), "length": 0.1,
                         "velocity": int(np.clip(50 + 77 * v, 1, 127))})
    note.sort(key=lambda d: (d["start"], d["pitch"]))
    return note
