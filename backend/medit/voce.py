"""La voce dell'utente: conversione con Applio (RVC) sui suoi modelli.

Applio e' un programma a parte, con il suo ambiente Python e i suoi modelli in
``logs/<nome>/``. medit lo chiama da riga di comando (``core.py infer``): niente
torch dentro medit. Si trova da solo in ``~/Downloads/Applio``, ``~/Applio``,
``~/Documents/Applio``, oppure in ``MEDIT_APPLIO`` / ``~/.medit/applio.json``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

F0_METHODS = ("rmvpe", "crepe", "crepe-tiny", "fcpe", "hybrid[rmvpe+fcpe]")


class VoceError(RuntimeError):
    pass


def _conf_file() -> Path:
    base = Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "applio.json"


def _python(radice: Path) -> Path | None:
    for p in (radice / "env" / "python.exe", radice / "env" / "bin" / "python", radice / ".venv" / "Scripts" / "python.exe",
              radice / ".venv" / "bin" / "python"):
        if p.is_file():
            return p
    return None


def radice() -> Path | None:
    candidati = []
    if env := os.environ.get("MEDIT_APPLIO"):
        candidati.append(Path(env))
    try:
        conf = json.loads(_conf_file().read_text(encoding="utf-8"))
        if conf.get("path"):
            candidati.append(Path(conf["path"]))
    except (OSError, ValueError):
        pass
    if not os.environ.get("MEDIT_APPLIO"):
        h = Path.home()
        candidati += [h / "Downloads" / "Applio", h / "Applio", h / "Documents" / "Applio"]
    for c in candidati:
        if (c / "core.py").is_file() and _python(c):
            return c
    return None


def imposta(path: str) -> dict:
    p = Path(path)
    if not (p / "core.py").is_file() or not _python(p):
        raise VoceError(f"{path} is not an Applio folder (core.py and its env are missing)")
    _conf_file().write_text(json.dumps({"path": str(p.resolve())}), encoding="utf-8")
    return stato()


def modelli() -> list[dict]:
    """Modelli finiti in logs/: il .pth piccolo (non i checkpoint G_/D_) e il suo .index."""
    r = radice()
    if r is None:
        return []
    out = []
    logs = r / "logs"
    for d in sorted(logs.iterdir()) if logs.is_dir() else []:
        if not d.is_dir():
            continue
        pth = [p for p in d.glob("*.pth") if not p.name.startswith(("G_", "D_"))]
        if not pth:
            continue
        pth.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        idx = sorted(d.glob("*.index"), key=lambda p: ("added" not in p.name, p.name))
        out.append({"name": d.name, "pth": str(pth[0]), "index": str(idx[0]) if idx else ""})
    return out


def stato() -> dict:
    r = radice()
    if r is None:
        return {"ok": False, "hint": "install Applio (github.com/IAHispano/Applio) or tell medit where it is "
                                     "(MEDIT_APPLIO or applio_path)"}
    m = modelli()
    return {"ok": bool(m), "path": str(r), "models": [x["name"] for x in m],
            **({} if m else {"hint": "Applio has no trained voice models in logs/"})}


def converti(src: Path, dst: Path, model: str, pitch: int = 0, f0_method: str = "rmvpe", index_rate: float = 0.5,
             protect: float = 0.33, autotune: bool = False, timeout: float = 1800.0) -> Path:
    r = radice()
    if r is None:
        raise VoceError(stato()["hint"])
    voci = {m["name"]: m for m in modelli()}
    if model not in voci:
        raise VoceError(f"no voice model {model!r}; available: {', '.join(voci) or 'none'}")
    if f0_method not in F0_METHODS:
        raise VoceError(f"f0_method must be one of {', '.join(F0_METHODS)}")
    m = voci[model]
    cmd = [str(_python(r)), "core.py", "infer", "--input-path", str(src), "--output-path", str(dst),
           "--pth-path", m["pth"], "--index-path", m["index"], "--pitch", str(int(max(-24, min(24, pitch)))),
           "--f0-method", f0_method, "--index-rate", f"{max(0.0, min(1.0, index_rate)):.2f}",
           "--protect", f"{max(0.0, min(0.5, protect)):.2f}", "--export-format", "WAV"]
    if autotune:
        cmd.append("--f0-autotune")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run(cmd, cwd=str(r), capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise VoceError("Applio took too long") from exc
    if p.returncode != 0 or not dst.is_file():
        coda = (p.stderr or p.stdout or b"").decode("utf-8", "replace")[-600:]
        raise VoceError(f"Applio failed: {coda}")
    return dst
