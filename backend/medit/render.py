"""Render: documento -> campioni. Funzione pura del documento e dei file audio.

Catena di una traccia:
    clip (note -> strumento, oppure pezzi di file audio) -> effetti in serie
    (con automazione) -> volume -> pan -> master, piu' le mandate (post-fader)
    verso le tracce bus, che hanno i loro effetti e tornano nel master.
    Master: effetti in serie -> volume.

Mute e solo decidono solo *cosa entra* nel master: il render di ogni traccia
resta in cache per impronta (il suo JSON + tempo + file usati), quindi un mute,
un solo o una modifica a un'altra traccia non ricalcolano niente. Anteprima
della UI, analisi dell'agente ed export escono da questo stesso codice.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import audio_io
from . import effects as fx
from . import synth
from .model import Clip, Project, Track, to_dict

TAIL_S = 2.5          # coda dopo l'ultima nota: riverberi e rilasci
MAX_S = 20 * 60       # oltre venti minuti e' quasi certamente un errore di battute
SWING_GRID = 0.25     # lo swing globale sposta i sedicesimi in levare


def resolve(path: str, base_dir: str | None) -> Path:
    p = Path(path)
    if not p.is_absolute() and base_dir:
        p = Path(base_dir) / p
    return p


def _db(x: float) -> float:
    return 10.0 ** (x / 20.0)


# --------------------------------------------------------------------------
# tempo
# --------------------------------------------------------------------------


def song_beats(project: Project) -> float:
    return max(project.end_beat(), project.beats_per_bar)


def length_samples(project: Project, sr: int | None = None, tail: float = TAIL_S) -> int:
    sr = sr or project.sample_rate
    s = min(MAX_S, project.beat_to_s(song_beats(project)) + tail)
    return int(math.ceil(s * sr))


def beat_sample(project: Project, beat: float, sr: int) -> int:
    return int(round(beat * project.seconds_per_beat * sr))


def _swing(beat: float, swing: float) -> float:
    if swing <= 0:
        return beat
    pos = beat / SWING_GRID
    k = int(round(pos))
    if k % 2 == 1 and abs(pos - k) < 1e-3:
        return beat + SWING_GRID * swing / 3.0
    return beat


def clip_note_events(project: Project, clip: Clip, sr: int) -> list[tuple[int, int, float, int]]:
    """Note della clip in campioni assoluti, con loop, trasposizione e swing."""
    if clip.muted or not clip.notes or clip.length <= 0:
        return []
    L = clip.loop_length if clip.loop_length > 0 else clip.length
    ripetizioni = int(math.ceil(clip.length / L - 1e-9)) if clip.loop_length > 0 else 1
    out = []
    for k in range(ripetizioni):
        for n in clip.notes:
            if clip.loop_length > 0 and n.start >= L - 1e-9:
                continue
            t = k * L + n.start
            if t >= clip.length - 1e-9 or t < 0:
                continue
            durata = min(n.length, clip.length - t)
            if durata <= 0:
                continue
            inizio = _swing(t, project.swing) + clip.start
            s0 = beat_sample(project, inizio, sr)
            s1 = beat_sample(project, inizio + durata, sr)
            p = n.pitch + clip.transpose
            if 0 <= p <= 127:
                out.append((s0, max(1, s1 - s0), float(p), int(n.velocity)))
    return out


def automation_curve(project: Project, points: list[list[float]], n: int, sr: int) -> np.ndarray:
    pts = sorted((float(b), float(v)) for b, v in points)
    beats = np.arange(n) / sr / project.seconds_per_beat
    return np.interp(beats, [p[0] for p in pts], [p[1] for p in pts])


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

_CACHE: dict[str, np.ndarray] = {}
_CACHE_BYTES = 900_000_000


def _cache_get(k: str):
    v = _CACHE.pop(k, None)
    if v is not None:
        _CACHE[k] = v   # in fondo: usato di recente
    return v


def _cache_put(k: str, v: np.ndarray) -> None:
    peso = sum(x.nbytes for x in _CACHE.values())
    while _CACHE and peso + v.nbytes > _CACHE_BYTES:
        peso -= _CACHE.pop(next(iter(_CACHE))).nbytes
    _CACHE[k] = v


def clear_cache() -> None:
    _CACHE.clear()


def _asset_firma(project: Project, ids: set[str], base_dir: str | None) -> list:
    out = []
    for a in project.assets:
        if a.id in ids:
            p = resolve(a.path, base_dir)
            try:
                out.append([a.id, str(p), p.stat().st_mtime_ns])
            except OSError:
                out.append([a.id, str(p), 0])
    return out


def _asset_usati(track: Track) -> set[str]:
    ids = {c.asset for c in track.clips if c.asset}
    if track.instrument and track.instrument.type == "sampler":
        par = track.instrument.params
        if par.get("asset"):
            ids.add(par["asset"])
        ids.update((par.get("map") or {}).values())
    return ids


def track_key(project: Project, track: Track, sr: int, n: int, base_dir: str | None) -> str:
    d = to_dict(track)
    for k in ("mute", "solo", "sends", "name", "color", "role"):
        d.pop(k, None)
    # l'autotune "sulla tonalita' della canzone" cambia se cambia la tonalita'
    tono = [project.key, project.mode] if any(e.type == "autotune" for e in track.effects) else None
    blob = json.dumps([d, project.bpm, project.swing, sr, n, _asset_firma(project, _asset_usati(track), base_dir), tono],
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


# --------------------------------------------------------------------------
# tracce
# --------------------------------------------------------------------------


def _loader(project: Project, base_dir: str | None, sr: int):
    def carica(asset_id: str):
        try:
            a = project.asset(asset_id)
        except KeyError:
            return None
        try:
            return audio_io.load(resolve(a.path, base_dir), sr)
        except audio_io.AudioError:
            return None
    return carica


def _fade(n: int, fi: int, fo: int) -> np.ndarray | None:
    if fi <= 0 and fo <= 0:
        return None
    g = np.ones(n)
    if fi > 0:
        m = min(fi, n)
        g[:m] = np.sin(np.linspace(0, np.pi / 2, m)) ** 2
    if fo > 0:
        m = min(fo, n)
        g[n - m:] *= np.cos(np.linspace(0, np.pi / 2, m)) ** 2
    return g


def _audio_clip(project: Project, clip: Clip, sr: int, n: int, carica) -> tuple[int, np.ndarray] | None:
    if clip.muted or not clip.asset:
        return None
    src = carica(clip.asset)
    if src is None:
        return None
    if clip.transpose:
        src = synth._resample(src, 2 ** (clip.transpose / 12.0))
    s0 = beat_sample(project, clip.start, sr)
    lung = beat_sample(project, clip.start + clip.length, sr) - s0
    if lung <= 0 or s0 >= n:
        return None
    i0 = int(clip.offset * sr)
    if clip.loop_length > 0:
        L = max(1, beat_sample(project, clip.loop_length, sr))
        pezzo = src[:, i0:i0 + L]
        if pezzo.shape[-1] == 0:
            return None
        rip = int(math.ceil(lung / pezzo.shape[-1]))
        seg = np.tile(pezzo, (1, rip))[:, :lung]
    else:
        seg = src[:, i0:i0 + lung]
    if seg.shape[-1] == 0:
        return None
    seg = seg.astype(np.float64) * _db(clip.gain_db)
    g = _fade(seg.shape[-1], beat_sample(project, clip.fade_in, sr), beat_sample(project, clip.fade_out, sr))
    if g is not None:
        seg = seg * g
    return s0, seg


def render_track_dry(project: Project, track: Track, sr: int, n: int, base_dir: str | None) -> np.ndarray:
    """Il suono della traccia prima di effetti, volume e pan."""
    out = np.zeros((2, n), dtype=np.float64)
    carica = _loader(project, base_dir, sr)
    if track.kind == "midi" and track.instrument is not None:
        inst = track.instrument
        for clip in track.clips:
            ev = clip_note_events(project, clip, sr)
            if not ev:
                continue
            y = synth.render_notes(inst.type, inst.params, ev, n, sr, carica, seed=hash_seed(track.id, clip.id))
            g = _db(clip.gain_db)
            if clip.fade_in or clip.fade_out:
                s0 = beat_sample(project, clip.start, sr)
                s1 = min(n, beat_sample(project, clip.end, sr))
                f = _fade(max(0, s1 - s0), beat_sample(project, clip.fade_in, sr), beat_sample(project, clip.fade_out, sr))
                if f is not None and s1 > s0:
                    y = y.astype(np.float64)
                    y[:, s0:s1] *= f
                    y[:, s1:] = 0.0
            out += y * g
    elif track.kind == "audio":
        for clip in track.clips:
            r = _audio_clip(project, clip, sr, n, carica)
            if r is None:
                continue
            s0, seg = r
            m = min(seg.shape[-1], n - s0)
            out[:, s0:s0 + m] += seg[:, :m]
    return out


def hash_seed(*parti) -> int:
    return int.from_bytes(hashlib.blake2b("|".join(map(str, parti)).encode(), digest_size=4).digest(), "little")


def apply_chain(project: Project, x: np.ndarray, effects: list, automation: list, sr: int, seed: int) -> np.ndarray:
    ctx = {"bpm": project.bpm, "sr": sr, "seed": seed, "key": project.key, "mode": project.mode}
    n = x.shape[-1]
    for i, e in enumerate(effects):
        if not e.enabled or e.type not in fx.REGISTRY:
            continue
        curve = {}
        for a in automation:
            parti = a.target.split(".")
            if len(parti) == 3 and parti[0] == "fx" and parti[1] == str(i) and a.points:
                curve[parti[2]] = automation_curve(project, a.points, n, sr)
        x = fx.apply(e.type, x, sr, e.params, ctx, curve)
    return x


def fader(project: Project, x: np.ndarray, volume_db: float, pan: float, automation: list, sr: int) -> np.ndarray:
    n = x.shape[-1]
    vol = next((a for a in automation if a.target == "volume" and a.points), None)
    pn = next((a for a in automation if a.target == "pan" and a.points), None)
    g = np.power(10.0, automation_curve(project, vol.points, n, sr) / 20.0) if vol else _db(volume_db)
    if pn:
        p = np.clip(automation_curve(project, pn.points, n, sr), -1, 1)
        th = (p + 1) * np.pi / 4
        gl, gr = np.cos(th) * np.sqrt(2), np.sin(th) * np.sqrt(2)
    else:
        gl, gr = synth._pan_gains(pan)
    return np.stack([x[0] * g * gl, x[1] * g * gr])


def render_track(project: Project, track: Track, sr: int, n: int, base_dir: str | None,
                 bus_input: np.ndarray | None = None, key: str | None = None) -> np.ndarray:
    """Traccia completa, post-fader (in cache per impronta)."""
    k = key or track_key(project, track, sr, n, base_dir)
    hit = _cache_get(k)
    if hit is not None:
        return hit
    x = bus_input.astype(np.float64) if bus_input is not None else render_track_dry(project, track, sr, n, base_dir)
    if np.any(x):
        x = apply_chain(project, x, track.effects, track.automation, sr, hash_seed(track.id))
    x = fader(project, x, track.volume_db, track.pan, track.automation, sr).astype(np.float32)
    _cache_put(k, x)
    return x


# --------------------------------------------------------------------------
# mix
# --------------------------------------------------------------------------


def audible(project: Project) -> set[str]:
    """Tracce che arrivano al master, dato mute e solo."""
    solo = {t.id for t in project.tracks if t.solo and not t.mute}
    out = {t.id for t in project.tracks if t.kind != "bus" and not t.mute and (not solo or t.id in solo)}
    for t in project.tracks:
        if t.kind == "bus" and not t.mute:
            # un bus suona se gli arriva qualcosa da una traccia udibile
            if any(s.bus == t.id for x in project.tracks if x.id in out for s in x.sends):
                out.add(t.id)
    return out


def render_stems(project: Project, base_dir: str | None, sr: int | None = None,
                 n: int | None = None) -> tuple[dict[str, np.ndarray], int]:
    """Ogni traccia udibile post-fader (bus compresi), senza il master."""
    sr = sr or project.sample_rate
    n = n or length_samples(project, sr)
    ok = audible(project)
    stems: dict[str, np.ndarray] = {}
    chiavi: dict[str, str] = {}
    ingressi: dict[str, np.ndarray] = {}
    sorgenti: dict[str, list] = {}
    for t in project.tracks:
        if t.kind == "bus":
            continue
        k = track_key(project, t, sr, n, base_dir)
        chiavi[t.id] = k
        if t.id not in ok:
            continue
        y = render_track(project, t, sr, n, base_dir, key=k)
        stems[t.id] = y
        for s in t.sends:
            ingressi.setdefault(s.bus, np.zeros((2, n), dtype=np.float32))
            ingressi[s.bus] += y * np.float32(_db(s.level_db))
            sorgenti.setdefault(s.bus, []).append([k, round(s.level_db, 3)])
    for t in project.tracks:
        if t.kind != "bus" or t.id not in ok or t.id not in ingressi:
            continue
        kb = hashlib.sha1((track_key(project, t, sr, n, base_dir) +
                           json.dumps(sorgenti[t.id], sort_keys=True)).encode()).hexdigest()
        stems[t.id] = render_track(project, t, sr, n, base_dir, bus_input=ingressi[t.id], key=kb)
    return stems, n


def render(project: Project, base_dir: str | None = None, sr: int | None = None,
           start_beat: float | None = None, end_beat: float | None = None,
           master: bool = True) -> np.ndarray:
    """La canzone (2, N) float32. ``start_beat``/``end_beat`` tagliano dopo il render
    completo, cosi' code di riverbero e compressori restano giusti."""
    sr = sr or project.sample_rate
    stems, n = render_stems(project, base_dir, sr)
    x = np.zeros((2, n), dtype=np.float64)
    for y in stems.values():
        x += y
    if master:
        if project.master.effects and np.any(x):
            x = apply_chain(project, x, project.master.effects, [], sr, hash_seed("master"))
        x = x * _db(project.master.volume_db)
    if start_beat is not None or end_beat is not None:
        a = beat_sample(project, start_beat or 0.0, sr)
        b = n if end_beat is None else beat_sample(project, end_beat, sr)
        x = x[:, max(0, a):max(a, b)]
    return x.astype(np.float32)


def render_note(project: Project, track: Track, pitch: int, velocity: int = 100, seconds: float = 0.6,
                base_dir: str | None = None) -> np.ndarray:
    """Una nota sola sullo strumento della traccia (per sentire il tasto del piano roll)."""
    sr = project.sample_rate
    if track.instrument is None:
        return np.zeros((2, int(sr * 0.1)), dtype=np.float32)
    n = int(sr * (seconds + 1.5))
    y = synth.render_notes(track.instrument.type, track.instrument.params, [(0, int(sr * seconds), float(pitch), velocity)],
                           n, sr, _loader(project, base_dir, sr))
    y = apply_chain(project, y.astype(np.float64), track.effects, [], sr, hash_seed(track.id))
    return fader(project, y, track.volume_db, track.pan, [], sr).astype(np.float32)
