"""Immagini della canzone: quello che l'agente *guarda* al posto di ascoltare.

- ``arrangement``: tracce x battute, sezioni in alto, clip con le note in
  miniatura (MIDI) o la forma d'onda (audio);
- ``piano_roll``: le note di una clip o di una traccia, con i nomi delle note,
  la griglia delle battute e le righe della scala evidenziate;
- ``mix``: forma d'onda del master, loudness nel tempo e spettrogramma.

Pillow e basta: stesse immagini per l'agente (MCP) e per la UI se servono.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import render, theory
from .model import Project

BG = (24, 25, 29)
GRID = (44, 46, 52)
GRID_BAR = (70, 73, 82)
TEXT = (220, 222, 228)
DIM = (140, 144, 152)


def _font(size: int = 12):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _rgb(hexcol: str | None, default=(90, 140, 220)) -> tuple[int, int, int]:
    try:
        h = (hexcol or "").lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def _mix(c, k: float, base=BG):
    return tuple(int(base[i] + (c[i] - base[i]) * k) for i in range(3))


def _range(project: Project, bars: list[float] | None) -> tuple[float, float]:
    if bars:
        a = project.bar_to_beat(float(bars[0]))
        b = project.bar_to_beat(float(bars[1]) + 1) if len(bars) > 1 else a + project.beats_per_bar * 8
        return a, max(b, a + project.beats_per_bar)
    fine = max(render.song_beats(project), project.beats_per_bar * 4)
    return 0.0, fine


def arrangement(project: Project, width: int = 1400, bars: list[float] | None = None,
                base_dir: str | None = None, waveforms: bool = True) -> Image.Image:
    a, b = _range(project, bars)
    head = 150
    row = 46
    top = 44
    h = top + row * max(1, len(project.tracks)) + 8
    img = Image.new("RGB", (width, h), BG)
    d = ImageDraw.Draw(img)
    f, fs = _font(12), _font(10)
    W = width - head - 8
    bpb = project.beats_per_bar

    def X(beat: float) -> float:
        return head + (beat - a) / (b - a) * W

    # battute
    n_bar0 = int(a // bpb)
    n_bar1 = int(np.ceil(b / bpb))
    passo = max(1, int(np.ceil((n_bar1 - n_bar0) / 32)))
    for k in range(n_bar0, n_bar1 + 1):
        x = X(k * bpb)
        if x < head - 1 or x > width:
            continue
        d.line([(x, 18), (x, h)], fill=GRID_BAR if k % 4 == 0 else GRID, width=1)
        if (k - n_bar0) % passo == 0:
            d.text((x + 2, 2), str(k + 1), fill=DIM, font=fs)
    # sezioni
    for s in project.sections:
        x0, x1 = max(head, X(s.start)), min(width - 8, X(s.end))
        if x1 <= x0:
            continue
        c = _rgb(s.color, (120, 120, 160))
        d.rectangle([x0, 18, x1, 38], fill=_mix(c, 0.45), outline=_mix(c, 0.9))
        d.text((x0 + 4, 21), s.name, fill=TEXT, font=f)
    # tracce
    for i, t in enumerate(project.tracks):
        y0 = top + i * row
        y1 = y0 + row - 6
        c = _rgb(t.color)
        d.rectangle([0, y0, head - 6, y1], fill=(34, 36, 41))
        d.rectangle([0, y0, 4, y1], fill=c)
        etichetta = t.name[:18]
        stato = ("M" if t.mute else "") + ("S" if t.solo else "")
        d.text((10, y0 + 4), etichetta, fill=TEXT if not t.mute else DIM, font=f)
        sotto = (t.instrument.preset or t.instrument.type) if t.instrument else t.kind
        d.text((10, y0 + 20), f"{sotto[:16]} {t.volume_db:+.0f}dB {stato}", fill=DIM, font=fs)
        for cl in t.clips:
            x0, x1 = X(cl.start), X(cl.end)
            if x1 < head or x0 > width:
                continue
            x0c, x1c = max(head, x0), min(width - 8, x1)
            cc = _rgb(cl.color or t.color)
            d.rectangle([x0c, y0, x1c, y1], fill=_mix(cc, 0.35 if not cl.muted else 0.15), outline=_mix(cc, 0.8))
            if cl.kind == "midi" and cl.notes:
                L = cl.loop_length if cl.loop_length > 0 else cl.length
                altezze = [n.pitch for n in cl.notes]
                lo, hi = min(altezze), max(altezze)
                span = max(12, hi - lo + 1)
                rip = int(np.ceil(cl.length / L)) if cl.loop_length > 0 else 1
                for k in range(rip):
                    for n in cl.notes:
                        if cl.loop_length > 0 and n.start >= L:
                            continue
                        s0 = cl.start + k * L + n.start
                        if s0 >= cl.end:
                            continue
                        e0 = min(cl.end, s0 + n.length)
                        yy = y1 - 4 - (n.pitch - lo + (span - (hi - lo + 1)) / 2) / span * (row - 16)
                        xa, xb = X(s0), max(X(s0) + 1, X(e0))
                        if xb < head or xa > width - 8:
                            continue
                        d.line([(max(head, xa), yy), (min(width - 8, xb), yy)], fill=_mix(cc, 1.0, (255, 255, 255)), width=2)
            elif cl.kind == "audio" and waveforms and cl.asset:
                try:
                    from . import audio_io

                    asset = project.asset(cl.asset)
                    x = audio_io.load(render.resolve(asset.path, base_dir), 8000)
                    s0 = int(cl.offset * 8000)
                    s1 = s0 + int(project.beat_to_s(cl.length) * 8000 * 2 ** (-cl.transpose / 12))
                    seg = np.abs(x[:, s0:s1]).max(axis=0)
                    if len(seg) > 1:
                        px = int(max(1, x1c - x0c))
                        cols = np.array_split(seg[: len(seg)], px) if len(seg) >= px else [seg]
                        mid = (y0 + y1) / 2
                        for j, col in enumerate(cols):
                            v = float(col.max()) if len(col) else 0.0
                            xx = x0c + j
                            d.line([(xx, mid - v * (row - 14) / 2), (xx, mid + v * (row - 14) / 2)],
                                   fill=_mix(cc, 0.95, (255, 255, 255)))
                except Exception:  # noqa: BLE001 - una forma d'onda mancante non blocca l'immagine
                    pass
            if x1c - x0c > 40:
                d.text((x0c + 3, y0 + 2), (cl.name or "")[:24], fill=TEXT, font=fs)
    return img


def piano_roll(project: Project, track_ref: str | None = None, clip_ref: str | None = None,
               width: int = 1200, bars: list[float] | None = None) -> Image.Image:
    if clip_ref:
        t, cl = project.clip(clip_ref)
        clips = [cl]
        a, b = cl.start, cl.end
    elif track_ref:
        t = project.track(track_ref)
        clips = list(t.clips)
        if clips and not bars:
            # di una traccia si guarda dove suona, non tutta la canzone
            a = min(c.start for c in clips)
            b = max(c.end for c in clips)
        else:
            a, b = _range(project, bars)
    else:
        raise ValueError("piano_roll needs a clip or a track")
    if bars and not clip_ref:
        a, b = _range(project, bars)
    notes = []
    for cl in clips:
        for s0, durata, pitch in _note_assolute(cl):
            if s0 < b and s0 + durata > a:
                notes.append((s0, durata, pitch[0], pitch[1]))
    if notes:
        lo = min(n[2] for n in notes) - 2
        hi = max(n[2] for n in notes) + 2
    else:
        lo, hi = 48, 72
    if hi - lo < 12:
        mid = (hi + lo) // 2
        lo, hi = mid - 6, mid + 6
    righe = hi - lo + 1
    rh = int(np.clip(560 / righe, 6, 16))
    head = 46
    top = 20
    h = top + righe * rh + 4
    img = Image.new("RGB", (width, h), BG)
    d = ImageDraw.Draw(img)
    fs = _font(10)
    W = width - head - 6
    pcs = theory.scale_pcs(project.key, project.mode)
    tamburi = t.instrument is not None and t.instrument.type == "drums"

    def X(beat):
        return head + (beat - a) / max(1e-6, b - a) * W

    for r in range(righe):
        p = hi - r
        y = top + r * rh
        nero = p % 12 in (1, 3, 6, 8, 10)
        fondo = (30, 31, 36) if nero else (36, 38, 44)
        if not tamburi and p % 12 in pcs:
            fondo = _mix((80, 110, 160), 0.25, fondo)
        d.rectangle([head, y, width, y + rh - 1], fill=fondo)
        nome = theory.DRUM_NAMES.get(p, theory.pitch_name(p)) if tamburi else theory.pitch_name(p)
        if tamburi or p % 12 == 0 or rh >= 12:
            d.text((2, y + max(0, rh // 2 - 6)), nome[:8], fill=TEXT if p % 12 == 0 or tamburi else DIM, font=fs)
    bpb = project.beats_per_bar
    k = np.floor(a)
    while k <= b:
        x = X(k)
        bar = abs(k / bpb - round(k / bpb)) < 1e-6
        d.line([(x, top), (x, h)], fill=GRID_BAR if bar else GRID)
        if bar:
            d.text((x + 2, 4), str(int(k / bpb) + 1), fill=DIM, font=fs)
        k += 1.0 if (b - a) <= 64 else bpb
    c = _rgb(t.color)
    for s0, durata, p, vel in notes:
        if not lo <= p <= hi:
            continue
        y = top + (hi - p) * rh
        xa, xb = X(max(a, s0)), X(min(b, s0 + durata))
        col = _mix(c, 0.45 + 0.55 * vel / 127, (255, 255, 255)) if vel > 0 else c
        d.rectangle([xa, y + 1, max(xa + 2, xb - 1), y + rh - 2], fill=col, outline=(10, 10, 12))
    d.text((head + 4, h - 14), f"{t.name} - {project.key} {project.mode}", fill=DIM, font=fs)
    return img


def _note_assolute(cl):
    L = cl.loop_length if cl.loop_length > 0 else cl.length
    rip = int(np.ceil(cl.length / L)) if cl.loop_length > 0 else 1
    for k in range(rip):
        for n in cl.notes:
            if cl.loop_length > 0 and n.start >= L:
                continue
            s = cl.start + k * L + n.start
            if s >= cl.end:
                continue
            yield s, min(n.length, cl.end - s), (n.pitch + cl.transpose, n.velocity)


def mix_view(project: Project, x: np.ndarray, width: int = 1400, height: int = 420) -> Image.Image:
    """Forma d'onda, loudness a breve termine e spettrogramma del master."""
    sr = project.sample_rate
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    fs = _font(10)
    m = np.asarray(x, dtype=np.float64)
    n = m.shape[-1]
    if n == 0:
        return img
    wh = height // 3
    cols = np.array_split(np.arange(n), width)
    for i, idx in enumerate(cols):
        if len(idx) == 0:
            continue
        seg = m[:, idx[0]: idx[-1] + 1]
        top, bot = float(seg.max()), float(seg.min())
        rms = float(np.sqrt((seg ** 2).mean()))
        mid = wh / 2
        d.line([(i, mid - top * mid), (i, mid - bot * mid)], fill=(90, 140, 220))
        d.line([(i, mid - rms * mid), (i, mid + rms * mid)], fill=(150, 190, 255))
        if max(abs(top), abs(bot)) >= 0.999:
            d.point((i, 1), fill=(255, 60, 60))
    # battute e sezioni
    for s in project.sections:
        xx = render.beat_sample(project, s.start, sr) / n * width
        d.line([(xx, 0), (xx, height)], fill=GRID_BAR)
        d.text((xx + 3, wh + 2), s.name, fill=TEXT, font=fs)
    # spettrogramma (log in frequenza)
    nfft = 2048
    mono = m.mean(axis=0)
    sh = height - wh - 18
    spec = np.zeros((sh, width))
    fr = np.fft.rfftfreq(nfft, 1 / sr)
    edges = np.geomspace(30, min(18000, sr / 2), sh + 1)
    bins = np.clip(np.searchsorted(fr, edges), 1, len(fr) - 1)
    win = np.hanning(nfft)
    for i in range(width):
        c = int(i / width * max(1, n - nfft))
        mag = np.abs(np.fft.rfft(mono[c:c + nfft] * win)) if c + nfft <= n else np.zeros(len(fr))
        cs = np.concatenate([[0], np.cumsum(mag)])
        val = (cs[bins[1:]] - cs[bins[:-1]]) / np.maximum(1, bins[1:] - bins[:-1])
        spec[:, i] = val[::-1]
    db = 20 * np.log10(spec + 1e-9)
    db = np.clip((db - (db.max() - 80)) / 80, 0, 1)
    rgb = np.stack([db ** 0.7 * 255, db ** 1.5 * 200, (1 - db) * db * 4 * 180 + db ** 3 * 60], axis=-1).astype(np.uint8)
    img.paste(Image.fromarray(rgb), (0, wh + 18))
    for f0 in (100, 1000, 10000):
        yy = wh + 18 + sh - (np.log(f0 / 30) / np.log(edges[-1] / 30)) * sh
        d.line([(0, yy), (14, yy)], fill=TEXT)
        d.text((16, yy - 6), f"{f0 if f0 < 1000 else str(f0 // 1000) + 'k'}", fill=TEXT, font=fs)
    return img
