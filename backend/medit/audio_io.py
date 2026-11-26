"""Leggere e scrivere file audio.

``soundfile`` (libsndfile, ruote con la libreria dentro) legge e scrive WAV,
FLAC, OGG/Opus, AIFF e MP3. Per il resto (m4a, aac, l'audio di un video) serve
ffmpeg: si cerca in ``MEDIT_FFMPEG``, nel PATH e in ``~/.vedit/bin`` (dove lo
mette l'editor video gemello).

Tutto l'audio dentro l'editor e' float32 stereo ``(2, N)`` alla frequenza del
documento: i file mono si duplicano, gli altri si ricampionano all'apertura.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

WRITE_FORMATS = {".wav": "WAV", ".flac": "FLAC", ".ogg": "OGG", ".mp3": "MP3", ".aiff": "AIFF", ".aif": "AIFF",
                 ".opus": "OGG"}
# con ffmpeg anche questi
FFMPEG_WRITE = {".m4a", ".aac"}


class AudioError(ValueError):
    pass


def ffmpeg() -> str | None:
    if env := os.environ.get("MEDIT_FFMPEG"):
        return env if Path(env).is_file() else None
    trovato = shutil.which("ffmpeg")
    if trovato:
        return trovato
    for nome in ("ffmpeg.exe", "ffmpeg"):
        f = Path.home() / ".vedit" / "bin" / nome
        if f.is_file():
            return str(f)
    return None


def _stereo(x: np.ndarray) -> np.ndarray:
    """(N,) o (N, C) di soundfile -> (2, N)."""
    if x.ndim == 1:
        return np.stack([x, x])
    if x.shape[1] == 1:
        return np.stack([x[:, 0], x[:, 0]])
    return np.ascontiguousarray(x[:, :2].T)


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to or x.shape[-1] == 0:
        return x
    g = np.gcd(int(sr_from), int(sr_to))
    return resample_poly(x, sr_to // g, sr_from // g, axis=-1).astype(np.float32)


def info(path: str | Path) -> dict:
    """Durata, frequenza e canali senza leggere tutto il file (con ffmpeg se serve)."""
    p = Path(path)
    if not p.is_file():
        raise AudioError(f"audio file not found: {path}")
    try:
        i = sf.info(str(p))
        return {"duration": float(i.duration), "sample_rate": int(i.samplerate), "channels": int(i.channels)}
    except (RuntimeError, sf.LibsndfileError):
        x, sr = _ffmpeg_decode(p, None)
        return {"duration": x.shape[-1] / sr, "sample_rate": sr, "channels": 2}


def _ffmpeg_decode(p: Path, sr: int | None) -> tuple[np.ndarray, int]:
    exe = ffmpeg()
    if not exe:
        raise AudioError(f"cannot read {p.name}: this format needs ffmpeg (install it, or convert the file to WAV/FLAC/MP3)")
    sr = sr or 44100
    cmd = [exe, "-v", "error", "-i", str(p), "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise AudioError(f"ffmpeg could not read {p.name}: {r.stderr.decode(errors='replace')[-300:]}")
    x = np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).T.copy()
    return x, sr


_CACHE: dict[tuple, np.ndarray] = {}
_CACHE_MAX_BYTES = 1_500_000_000


def load(path: str | Path, sr: int) -> np.ndarray:
    """File audio -> (2, N) float32 a ``sr``. In cache per (percorso, data di modifica, sr)."""
    p = Path(path)
    if not p.is_file():
        raise AudioError(f"audio file not found: {path}")
    chiave = (str(p.resolve()), p.stat().st_mtime_ns, sr)
    if chiave in _CACHE:
        return _CACHE[chiave]
    try:
        dati, sr0 = sf.read(str(p), dtype="float32", always_2d=False)
        x = _stereo(np.asarray(dati, dtype=np.float32))
        x = resample(x, sr0, sr)
    except (RuntimeError, sf.LibsndfileError):
        x, _ = _ffmpeg_decode(p, sr)
    x = np.ascontiguousarray(x, dtype=np.float32)
    peso = sum(v.nbytes for v in _CACHE.values())
    while _CACHE and peso + x.nbytes > _CACHE_MAX_BYTES:
        peso -= _CACHE.pop(next(iter(_CACHE))).nbytes
    _CACHE[chiave] = x
    return x


def write(path: str | Path, x: np.ndarray, sr: int, bit_depth: int = 24, quality: float = 0.9) -> dict:
    """Scrive (2, N) float. WAV/AIFF 16/24/32, FLAC 16/24, MP3/OGG con ``quality`` 0-1."""
    p = Path(path)
    ext = p.suffix.lower()
    p.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(x, dtype=np.float64)
    if ext in FFMPEG_WRITE:
        exe = ffmpeg()
        if not exe:
            raise AudioError(f"{ext} export needs ffmpeg; use .wav, .flac, .mp3 or .ogg")
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "mix.wav"
            write(tmp, x, sr, 24)
            kbps = int(128 + 192 * quality)
            r = subprocess.run([exe, "-v", "error", "-y", "-i", str(tmp), "-c:a", "aac", "-b:a", f"{kbps}k", str(p)],
                               capture_output=True, timeout=600)
            if r.returncode != 0:
                raise AudioError(f"ffmpeg failed: {r.stderr.decode(errors='replace')[-300:]}")
        return {"path": str(p), "format": ext[1:]}
    if ext not in WRITE_FORMATS:
        raise AudioError(f"unknown audio format {ext!r}; use {', '.join(sorted(WRITE_FORMATS | FFMPEG_WRITE))}")
    fmt = WRITE_FORMATS[ext]
    dati = np.clip(x, -1.0, 1.0).T
    subtype = None
    if fmt in ("WAV", "AIFF"):
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}.get(int(bit_depth), "PCM_24")
    elif fmt == "FLAC":
        subtype = "PCM_16" if int(bit_depth) == 16 else "PCM_24"
    elif fmt == "MP3":
        subtype = "MPEG_LAYER_III"
    elif ext == ".opus":
        subtype = "OPUS"
    elif fmt == "OGG":
        subtype = "VORBIS"
    if subtype in ("PCM_16",):
        # dither TPDF prima di ridurre a 16 bit: niente distorsione di quantizzazione
        rng = np.random.default_rng(0)
        dati = dati + (rng.random(dati.shape) - rng.random(dati.shape)) / 32768.0
    tmp = p.with_name(f"~{os.getpid()}_{p.name}")
    try:
        with sf.SoundFile(str(tmp), "w", samplerate=int(sr), channels=dati.shape[1], format=fmt, subtype=subtype) as f:
            if fmt in ("MP3", "OGG"):
                try:
                    f.compression_level = float(1.0 - quality)
                except (AttributeError, RuntimeError, sf.LibsndfileError):
                    pass
            f.write(dati)
        os.replace(tmp, p)
    except (RuntimeError, sf.LibsndfileError) as exc:
        tmp.unlink(missing_ok=True)
        raise AudioError(f"writing {p.name} failed: {exc}") from exc
    return {"path": str(p), "format": ext[1:]}


def wav_bytes(x: np.ndarray, sr: int) -> bytes:
    """WAV 16 bit in memoria, per far suonare il browser."""
    import io

    buf = io.BytesIO()
    sf.write(buf, np.clip(np.asarray(x, dtype=np.float32), -1, 1).T, int(sr), format="WAV", subtype="PCM_16")
    return buf.getvalue()
