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
import time
import urllib.request
from pathlib import Path

F0_METHODS = ("rmvpe", "crepe", "crepe-tiny", "fcpe", "hybrid[rmvpe+fcpe]", "hybrid[crepe+rmvpe]")
EMBEDDERS = ("contentvec", "spin", "spin-v2", "chinese-hubert-base", "japanese-hubert-base", "korean-hubert-base")
UI_PORT = 6969


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
             protect: float = 0.33, autotune: bool = False, autotune_strength: float = 1.0, clean: bool = False,
             clean_strength: float = 0.7, split_audio: bool = False, formant_shift: float = 0.0,
             volume_envelope: float = 1.0, embedder: str = "contentvec",
             timeout: float = 1800.0) -> Path:
    """Tutte le opzioni di ``core.py infer`` che servono a una voce cantata. ``formant_shift`` in
    semitoni sposta il timbro (piu' giovane/maturo) senza cambiare le note."""
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
    if embedder not in EMBEDDERS:
        raise VoceError(f"embedder must be one of {', '.join(EMBEDDERS)}")
    cmd += ["--volume-envelope", f"{max(0.0, min(1.0, volume_envelope)):.2f}", "--embedder-model", embedder]
    if autotune:
        cmd += ["--f0-autotune", "--f0-autotune-strength", f"{max(0.0, min(1.0, autotune_strength)):.2f}"]
    if clean:
        cmd += ["--clean-audio", "--clean-strength", f"{max(0.0, min(1.0, clean_strength)):.2f}"]
    if split_audio:
        cmd.append("--split-audio")
    if formant_shift:
        # il timbro si sposta col fattore di Applio; la quefrency (finestra del cepstro) resta 1
        cmd += ["--formant-shifting", "--formant-qfrency", "1.0",
                "--formant-timbre", f"{2 ** (max(-12.0, min(12.0, formant_shift)) / 12):.4f}"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run(cmd, cwd=str(r), capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise VoceError("Applio took too long") from exc
    if p.returncode != 0 or not dst.is_file():
        coda = (p.stderr or p.stdout or b"").decode("utf-8", "replace")[-600:]
        raise VoceError(f"Applio failed: {coda}")
    return dst


# --------------------------------------------------------------------------
# l'interfaccia di Applio (Gradio), avviata da medit e mostrata dentro l'editor
# --------------------------------------------------------------------------

_ui: dict = {}


def ui_url(port: int = UI_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def ui_attiva(port: int = UI_PORT) -> bool:
    try:
        with urllib.request.urlopen(ui_url(port), timeout=1.5) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001 - spenta, o ancora in avvio
        return False


def ui_avvia(port: int = UI_PORT) -> dict:
    """Avvia l'interfaccia di Applio (training, TTS, modelli, tutto) senza aprire il browser."""
    if ui_attiva(port):
        return {"url": ui_url(port), "running": True, "started_by_medit": bool(_ui.get("proc"))}
    r = radice()
    if r is None:
        raise VoceError(stato()["hint"])
    proc = _ui.get("proc")
    if proc is None or proc.poll() is not None:
        log = open(Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit")) / "applio_ui.log", "wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _ui["proc"] = subprocess.Popen([str(_python(r)), "app.py", "--port", str(port)], cwd=str(r), stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=flags,
                                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        _ui["t0"] = time.time()
    return {"url": ui_url(port), "running": False, "starting": True,
            "note": "Applio takes 20-60 s to start; the page refreshes by itself"}


def ui_ferma() -> dict:
    proc = _ui.pop("proc", None)
    if proc is None or proc.poll() is not None:
        return {"stopped": False, "reason": "Applio was not started by medit"}
    proc.terminate()
    return {"stopped": True}


def ui_stato(port: int = UI_PORT) -> dict:
    proc = _ui.get("proc")
    return {"url": ui_url(port), "running": ui_attiva(port),
            "starting": bool(proc is not None and proc.poll() is None and not ui_attiva(port)),
            "started_by_medit": bool(proc is not None and proc.poll() is None)}
