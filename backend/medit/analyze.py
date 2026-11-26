"""Misure, rilevamenti e revisione: l'agente non sente, ma misura.

- ``stats``: loudness integrata (ITU-R BS.1770 / EBU R128, con gating), picco
  vero (sovracampionato 4x), RMS, crest, bilancio spettrale per bande,
  correlazione e larghezza stereo, campioni in clipping, silenzio in testa/coda;
- ``detect_tempo`` / ``detect_key``: per i file importati (un beat, un loop);
- ``review``: cosa non va nella canzone, ognuno con lo strumento che lo
  sistema (come ``review_image`` di pedit).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, resample_poly

from . import render, theory
from .model import Project

BANDS = (("sub", 20, 60), ("bass", 60, 250), ("low_mid", 250, 500), ("mid", 500, 2000),
         ("high_mid", 2000, 6000), ("air", 6000, 20000))

# bilancio "tipico" di un mix pop/rock moderno (dB relativi al totale): serve
# solo a dire "molto sopra" / "molto sotto", non e' una legge
REFERENCE_BALANCE = {"sub": -12.0, "bass": -5.5, "low_mid": -9.5, "mid": -8.0, "high_mid": -12.0, "air": -18.0}


def _py(x):
    """Numeri numpy -> numeri Python: le risposte diventano JSON pulito."""
    if isinstance(x, dict):
        return {k: _py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_py(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    return x


def _k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    """Filtro K di BS.1770: shelf alto +4 dB e passa-alto a 38 Hz."""
    # coefficienti di riferimento a 48 kHz, ricalcolati per sr con le formule della norma
    import math

    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    y = lfilter(b, a, x, axis=-1)
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a = [1.0, 2 * (K * K - 1) / (1 + K / Q + K * K), (1 - K / Q + K * K) / (1 + K / Q + K * K)]
    b = [1.0, -2.0, 1.0]
    return lfilter(b, a, y, axis=-1)


def loudness(x: np.ndarray, sr: int) -> dict:
    """LUFS integrata (gating assoluto -70 e relativo -10), short-term massima, LRA."""
    x = np.asarray(x, dtype=np.float64)
    if x.shape[-1] < int(0.4 * sr):
        return {"lufs": -70.0, "short_term_max": -70.0, "lra": 0.0}
    y = _k_weight(x, sr)
    blocco, passo = int(0.4 * sr), int(0.1 * sr)
    p = (y ** 2).sum(axis=0)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, len(p) - blocco + 1, passo)
    z = (cs[starts + blocco] - cs[starts]) / blocco
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    ok = lk > -70
    if not ok.any():
        return {"lufs": -70.0, "short_term_max": -70.0, "lra": 0.0}
    rel = -0.691 + 10 * np.log10(z[ok].mean()) - 10
    ok2 = ok & (lk > rel)
    lufs = -0.691 + 10 * np.log10(z[ok2].mean()) if ok2.any() else -70.0
    # short-term 3 s
    b3 = int(3 * sr)
    if len(p) >= b3:
        s3 = np.arange(0, len(p) - b3 + 1, passo)
        st = -0.691 + 10 * np.log10(np.maximum((cs[s3 + b3] - cs[s3]) / b3, 1e-12))
        stm = float(st.max())
        valid = st[st > max(-70, lufs - 20)]
        lra = float(np.percentile(valid, 95) - np.percentile(valid, 10)) if len(valid) > 2 else 0.0
    else:
        stm, lra = float(lk.max()), 0.0
    return {"lufs": round(float(lufs), 2), "short_term_max": round(stm, 2), "lra": round(lra, 2)}


def true_peak_db(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    if x.shape[-1] == 0:
        return -120.0
    # a pezzi: 4x su tutta la canzone pesa
    picco = 0.0
    passo = 1 << 18
    for i in range(0, x.shape[-1], passo):
        seg = x[:, max(0, i - 32): i + passo + 32]
        picco = max(picco, float(np.abs(resample_poly(seg, 4, 1, axis=-1)).max()))
    return round(float(20 * np.log10(max(picco, 1e-9))), 2)


def spectrum_balance(x: np.ndarray, sr: int) -> dict:
    """Energia per banda, in dB relativi all'energia totale (Welch su mono)."""
    m = np.asarray(x, dtype=np.float64).mean(axis=0)
    if len(m) < 4096:
        return {b[0]: -60.0 for b in BANDS}
    nfft = 8192
    hop = nfft // 2
    win = np.hanning(nfft)
    k = (len(m) - nfft) // hop + 1
    if k > 400:   # bastano 400 finestre sparse sulla canzone
        idx = np.linspace(0, len(m) - nfft, 400).astype(int)
    else:
        idx = np.arange(k) * hop
    spec = np.zeros(nfft // 2 + 1)
    for i in idx:
        spec += np.abs(np.fft.rfft(m[i:i + nfft] * win)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / sr)
    tot = spec[(f >= 20) & (f <= 20000)].sum() + 1e-20
    return {nome: round(float(10 * np.log10(spec[(f >= lo) & (f < hi)].sum() / tot + 1e-12)), 2) for nome, lo, hi in BANDS}


def stereo(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=np.float64)
    l, r = x[0], x[1]
    den = np.sqrt((l ** 2).sum() * (r ** 2).sum()) + 1e-20
    corr = float((l * r).sum() / den)
    m, s = (l + r) / 2, (l - r) / 2
    w = float(np.sqrt((s ** 2).mean()) / (np.sqrt((m ** 2).mean()) + 1e-12))
    return {"correlation": round(corr, 3), "side_to_mid": round(w, 3)}


def stats(x: np.ndarray, sr: int, detail: bool = True) -> dict:
    x = np.asarray(x, dtype=np.float64)
    if x.shape[-1] == 0:
        return {"empty": True}
    picco = float(np.abs(x).max())
    rms = float(np.sqrt((x ** 2).mean()))
    out = {"duration_s": round(x.shape[-1] / sr, 2),
           "peak_db": round(20 * np.log10(max(picco, 1e-9)), 2),
           "rms_db": round(20 * np.log10(max(rms, 1e-9)), 2),
           "crest_db": round(20 * np.log10(max(picco, 1e-9) / max(rms, 1e-9)), 2),
           "clipped_samples": int((np.abs(x) >= 0.999).sum())}
    out.update(loudness(x, sr))
    if detail:
        out["true_peak_db"] = true_peak_db(x)
        out["bands_db"] = spectrum_balance(x, sr)
        out["stereo"] = stereo(x)
        soglia = 10 ** (-60 / 20)
        attivo = np.nonzero(np.abs(x).max(axis=0) > soglia)[0]
        if len(attivo):
            out["silence_start_s"] = round(attivo[0] / sr, 2)
            out["silence_end_s"] = round((x.shape[-1] - attivo[-1]) / sr, 2)
    return _py(out)


# --------------------------------------------------------------------------
# rilevamenti (file importati)
# --------------------------------------------------------------------------


def _onset_envelope(m: np.ndarray, sr: int, hop: int = 512) -> tuple[np.ndarray, float]:
    nfft = 2048
    n = (len(m) - nfft) // hop
    if n < 8:
        return np.zeros(1), sr / hop
    win = np.hanning(nfft)
    idx = np.arange(n)[:, None] * hop + np.arange(nfft)[None, :]
    frames = m[idx] * win
    mag = np.log1p(np.abs(np.fft.rfft(frames, axis=1)) * 10)
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")
    return np.maximum(flux, 0), sr / hop


def detect_tempo(x: np.ndarray, sr: int, lo: float = 70, hi: float = 180) -> dict:
    """BPM dall'autocorrelazione dell'inviluppo degli attacchi (con fiducia 0-1)."""
    m = np.asarray(x, dtype=np.float64).mean(axis=0)
    if len(m) > sr * 60:
        m = m[: sr * 60]
    if sr > 22050:
        m = resample_poly(m, 1, 2)
        sr2 = sr // 2
    else:
        sr2 = sr
    env, fr = _onset_envelope(m, sr2, 256)
    if len(env) < 32 or not env.any():
        return {"bpm": 0.0, "confidence": 0.0}
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac /= ac[0] + 1e-12
    lags = np.arange(len(ac))
    bpm = 60 * fr / np.maximum(lags, 1)
    ok = (bpm >= lo) & (bpm <= hi)
    if not ok.any():
        return {"bpm": 0.0, "confidence": 0.0}
    # si premiano anche il doppio e la meta' del periodo (coerenza metrica)
    score = ac.copy()
    for k in (2, 4):
        idx = np.minimum(lags * k, len(ac) - 1)
        score = score + 0.5 * ac[idx]
    cand = np.where(ok)[0]
    best = cand[np.argmax(score[cand])]
    # raffinamento parabolico del picco
    if 1 <= best < len(ac) - 1:
        y0, y1, y2 = ac[best - 1], ac[best], ac[best + 1]
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
        lag = best + float(np.clip(d, -0.5, 0.5))
    else:
        lag = float(best)
    tempo = 60 * fr / lag
    return {"bpm": round(float(tempo), 1), "confidence": round(float(np.clip(ac[best] * 2, 0, 1)), 2)}


_KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def chroma(x: np.ndarray, sr: int) -> np.ndarray:
    m = np.asarray(x, dtype=np.float64).mean(axis=0)
    if len(m) > sr * 90:
        m = m[: sr * 90]
    nfft, hop = 8192, 4096
    n = (len(m) - nfft) // hop
    c = np.zeros(12)
    if n < 1:
        return c
    win = np.hanning(nfft)
    f = np.fft.rfftfreq(nfft, 1 / sr)
    ok = (f > 55) & (f < 2000)
    pc = (np.round(12 * np.log2(f[ok] / 440.0)) + 69).astype(int) % 12
    for i in range(0, n, max(1, n // 300)):
        mag = np.abs(np.fft.rfft(m[i * hop:i * hop + nfft] * win))[ok]
        c += np.bincount(pc, weights=mag, minlength=12)
    return c / (c.sum() + 1e-12)


def detect_key(x: np.ndarray, sr: int) -> dict:
    """Tonalita' con i profili di Krumhansl-Schmuckler sul cromagramma."""
    c = chroma(x, sr)
    if not c.any():
        return {"key": "", "mode": "", "confidence": 0.0}
    best = (-2.0, 0, "major")
    punteggi = []
    for r in range(12):
        for prof, mode in ((_KS_MAJ, "major"), (_KS_MIN, "minor")):
            k = float(np.corrcoef(c, np.roll(prof, r))[0, 1])
            punteggi.append(k)
            if k > best[0]:
                best = (k, r, mode)
    k, r, mode = best
    secondo = sorted(punteggi)[-2]
    nomi = theory.note_names_for(r, mode)
    return {"key": nomi[r], "mode": mode, "confidence": round(float(np.clip((k - secondo) * 5 + k * 0.5, 0, 1)), 2)}


# --------------------------------------------------------------------------
# revisione della canzone
# --------------------------------------------------------------------------


def _w(code: str, msg: str, fix: str, **extra) -> dict:
    return {"code": code, "message": msg, "fix": fix, **extra}


def review(project: Project, base_dir: str | None, mix: np.ndarray | None = None,
           target_lufs: float = -14.0) -> list[dict]:
    """Problemi della canzone, ognuno con lo strumento che lo sistema."""
    W: list[dict] = []
    sr = project.sample_rate
    if not project.tracks:
        return [_w("empty", "the song has no tracks", "add_track, then add_chords / add_drums / add_melody")]
    ids_bus = {t.id for t in project.tracks if t.kind == "bus"}
    for t in project.tracks:
        if t.kind == "midi" and t.instrument is None:
            W.append(_w("no_instrument", f"track {t.name!r} has MIDI but no instrument", "set_instrument", track=t.id))
        if t.kind != "bus" and not t.clips:
            W.append(_w("empty_track", f"track {t.name!r} is empty", "add a clip or remove_track", track=t.id))
        for s in t.sends:
            if s.bus not in ids_bus:
                W.append(_w("bad_send", f"track {t.name!r} sends to a bus that does not exist", "set_send", track=t.id))
        clips = sorted((c for c in t.clips if not c.muted), key=lambda c: c.start)
        for a, b in zip(clips, clips[1:]):
            if b.start < a.end - 1e-6:
                W.append(_w("overlap", f"clips {a.name or a.id} and {b.name or b.id} overlap on {t.name!r} "
                         f"(bar {project.beat_to_bar(b.start):g})", "set_clip (move or shorten one)", track=t.id))
        if t.kind == "midi" and t.role != "drums" and (t.instrument is None or t.instrument.type != "drums"):
            pcs = theory.scale_pcs(project.key, project.mode)
            note = [n.pitch + c.transpose for c in t.clips for n in c.notes]
            fuori = [p for p in note if p % 12 not in pcs]
            if note and len(fuori) / len(note) > 0.2:
                W.append(_w("out_of_key", f"{len(fuori)} of {len(note)} notes on {t.name!r} are outside "
                         f"{project.key} {project.mode}", "fit_to_scale (or set_song key/mode if the key is wrong)",
                         track=t.id))
        if t.kind == "midi":
            for c in t.clips:
                registro = [n.pitch for n in c.notes]
                if registro and (t.role == "bass" or "bass" in t.name.lower()) and min(registro) + c.transpose > 60:
                    W.append(_w("bass_high", f"the bass on {t.name!r} plays above C4: it will not carry the low end",
                             "transpose_notes(semitones=-12)", clip=c.id))
    for a in project.assets:
        if not render.resolve(a.path, base_dir).is_file():
            W.append(_w("missing_file", f"audio file missing: {a.path}", "add_audio again, or remove the clip", asset=a.id))
    if all(t.mute for t in project.tracks):
        W.append(_w("all_muted", "every track is muted", "set_track(mute=false)"))
    if mix is None:
        try:
            mix = render.render(project, base_dir)
        except Exception as exc:  # noqa: BLE001
            W.append(_w("render_failed", f"the song does not render: {exc}", "report_issue"))
            return W
    st = stats(mix, sr)
    if st.get("empty") or st["peak_db"] < -60:
        W.append(_w("silent", "the song is silent", "check mute/solo, instruments and clips"))
        return W
    if st["clipped_samples"] > 0 or st["true_peak_db"] > -0.5:
        W.append(_w("clipping", f"the master clips (true peak {st['true_peak_db']} dBTP)",
                 "add a limiter on the master (auto_master) or lower track volumes", true_peak_db=st["true_peak_db"]))
    elif st["true_peak_db"] > -1.0:
        W.append(_w("hot_peak", f"true peak {st['true_peak_db']} dBTP: streaming services prefer <= -1 dBTP",
                 "limiter ceiling_db=-1 on the master (auto_master)"))
    if st["lufs"] < target_lufs - 6:
        W.append(_w("quiet", f"the mix is quiet ({st['lufs']} LUFS, target ~{target_lufs})",
                 f"auto_master(target_lufs={target_lufs})", lufs=st["lufs"]))
    elif st["lufs"] > target_lufs + 5:
        W.append(_w("loud", f"the mix is very loud ({st['lufs']} LUFS): it will be turned down and sound squashed",
                 "lower the limiter gain or auto_master", lufs=st["lufs"]))
    b = st["bands_db"]
    for banda, rif in REFERENCE_BALANCE.items():
        d = b[banda] - rif
        if banda == "low_mid" and d > 4:
            W.append(_w("muddy", f"too much 250-500 Hz ({d:+.1f} dB vs typical): muddy",
                     "eq mid_gain -3 around 300 Hz on pads/guitars/keys, or low_cut on non-bass tracks", band=banda))
        elif banda == "high_mid" and d > 5:
            W.append(_w("harsh", f"too much 2-6 kHz ({d:+.1f} dB): harsh", "eq cut around 3-4 kHz, deesser on vocals",
                     band=banda))
        elif banda in ("sub", "bass") and d < -8:
            W.append(_w("thin", f"weak low end ({banda} {d:+.1f} dB vs typical)", "a bass track, a longer kick, or eq low_gain",
                     band=banda))
        elif banda in ("sub", "bass") and d > 6:
            W.append(_w("boomy", f"too much low end ({banda} {d:+.1f} dB)", "eq low_cut on non-bass tracks, lower bass/kick",
                     band=banda))
        elif banda == "air" and d < -10:
            W.append(_w("dull", "very little top end: dull", "eq high_gain on master or brighter sounds", band=banda))
    if st["stereo"]["correlation"] < 0:
        W.append(_w("phase", "left and right cancel each other (negative correlation): it vanishes in mono",
                 "stereo_width width<1, check chorus/width settings"))
    # tracce che da sole saturano prima del master
    stems, _ = render.render_stems(project, base_dir, sr)
    for tid, y in stems.items():
        pk = float(np.abs(y).max())
        if pk > 2.0:   # +6 dBFS: in virgola mobile non clippa, ma il master fatica
            t = project.track(tid)
            W.append(_w("track_hot", f"track {t.name!r} peaks at {20 * np.log10(pk):+.1f} dBFS before the master",
                     f"set_track(volume_db={t.volume_db - 20 * np.log10(pk) - 3:.1f})", track=tid))
    if project.sections:
        for s in project.sections:
            pieno = any(c.start < s.end and c.end > s.start and not c.muted for t in project.tracks for c in t.clips)
            if not pieno:
                W.append(_w("empty_section", f"section {s.name!r} has no clips", "fill it, or remove_section", section=s.id))
    return W
