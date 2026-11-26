"""Separazione in stem (voce, batteria, basso, resto) con Demucs.

Demucs vuole torch: e' un extra (``pip install medit-mcp[stems]``) oppure un
altro Python che lo ha gia' (``MEDIT_DEMUCS_PYTHON``). Gira in un processo a
parte, cosi' torch non entra mai nel processo dell'editor.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

MODELS = ("htdemucs", "htdemucs_ft", "mdx_extra")
STEMS4 = ("vocals", "drums", "bass", "other")


class SeparaError(RuntimeError):
    pass


def python() -> str | None:
    if env := os.environ.get("MEDIT_DEMUCS_PYTHON"):
        return env if Path(env).is_file() else None
    if importlib.util.find_spec("demucs") is not None:
        return sys.executable
    return None


def stato() -> dict:
    p = python()
    if p:
        return {"ok": True, "python": p}
    return {"ok": False, "hint": "pip install \"medit-mcp[stems]\" (Demucs + torch, ~2 GB; a GPU helps but is "
                                 "not needed), or point MEDIT_DEMUCS_PYTHON to a Python that has demucs"}


def separa(src: Path, outdir: Path, two_stems: bool = False, model: str = "htdemucs",
           timeout: float = 3600.0) -> dict[str, Path]:
    """File audio -> {nome stem: file wav}. two_stems = solo voce e base (vocals, no_vocals)."""
    py = python()
    if not py:
        raise SeparaError(stato()["hint"])
    if model not in MODELS:
        raise SeparaError(f"model must be one of {', '.join(MODELS)}")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [py, "-m", "demucs", "-n", model, "-o", str(outdir)]
    if two_stems:
        cmd += ["--two-stems", "vocals"]
    cmd.append(str(src))
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired as exc:
        raise SeparaError("Demucs took too long") from exc
    cartella = outdir / model / src.stem
    nomi = ("vocals", "no_vocals") if two_stems else STEMS4
    out = {n: cartella / f"{n}.wav" for n in nomi if (cartella / f"{n}.wav").is_file()}
    if p.returncode != 0 or not out:
        coda = (p.stderr or p.stdout or b"").decode("utf-8", "replace")[-600:]
        raise SeparaError(f"Demucs failed: {coda}")
    return out
