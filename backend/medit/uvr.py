"""Modelli di Ultimate Vocal Remover (MDX-Net, VR, MDX23C, Roformer, Demucs).

UVR e' un'app "congelata" senza riga di comando, ma i suoi modelli sono file
normali. Li esegue ``audio-separator`` (la libreria che implementa le
architetture di UVR) in un processo a parte. Dove trova il Python giusto:

1. ``MEDIT_UVR_PYTHON``;
2. ``~/.medit/uvr-env``: lo crea ``medit uvr install`` **partendo dall'ambiente di
   Applio** (``--system-site-packages``): riusa il suo torch con CUDA e ci
   aggiunge solo audio-separator e onnxruntime. Applio non viene toccato;
3. il Python di medit, se ha ``audio_separator``.

I modelli si cercano nelle cartelle di UVR installato
(``%LOCALAPPDATA%/Programs/Ultimate Vocal Remover/models/...``) e in
``~/.medit/uvr_models``, dove audio-separator scarica quelli che mancano.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ESTENSIONI = {".onnx", ".pth", ".ckpt"}
# un buon modello per voce/base anche se UVR non e' installato (si scarica al primo uso)
DEFAULT_SCARICABILE = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
# preferiti, nell'ordine, fra quelli presenti
PREFERITI = ("model_bs_roformer", "mel_band_roformer", "UVR-MDX-NET-Inst_HQ", "Kim_Vocal", "UVR_MDXNET",
             "MDX23C", "HP")

_SCRIPT = r"""
import json, sys
from audio_separator.separator import Separator
src, out, model, mdir = sys.argv[1:5]
s = Separator(output_dir=out, model_file_dir=mdir, output_format="WAV")
s.load_model(model_filename=model)
print("MEDIT_OUT " + json.dumps([str(x) for x in s.separate(src)]))
"""


class UvrError(RuntimeError):
    pass


def _home() -> Path:
    return Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))


def env_dir() -> Path:
    return _home() / "uvr-env"


def _env_python() -> Path | None:
    for p in (env_dir() / "Scripts" / "python.exe", env_dir() / "bin" / "python"):
        if p.is_file():
            return p
    return None


def python() -> str | None:
    if env := os.environ.get("MEDIT_UVR_PYTHON"):
        return env if Path(env).is_file() else None
    p = _env_python()
    if p:
        return str(p)
    if importlib.util.find_spec("audio_separator") is not None:
        return sys.executable
    return None


def uvr_install() -> Path | None:
    """La cartella models di UVR installato, se c'e'."""
    if env := os.environ.get("MEDIT_UVR_MODELS"):
        p = Path(env)
        return p if p.is_dir() else None
    candidati = []
    if la := os.environ.get("LOCALAPPDATA"):
        candidati.append(Path(la) / "Programs" / "Ultimate Vocal Remover" / "models")
    candidati += [Path.home() / "Ultimate Vocal Remover" / "models",
                  Path("C:/Program Files/Ultimate Vocal Remover/models")]
    for c in candidati:
        if c.is_dir():
            return c
    return None


def cartelle() -> list[Path]:
    out = []
    u = uvr_install()
    if u:
        for sub in ("MDX_Net_Models", "VR_Models", "Demucs_Models"):
            if (u / sub).is_dir():
                out.append(u / sub)
        mdxc = u / "MDX_Net_Models" / "model_data" / "mdx_c_configs"
        if mdxc.is_dir():
            out.append(mdxc)
    scaricati = _home() / "uvr_models"
    out.append(scaricati)
    return out


def _arch(f: Path) -> str:
    n = f.name.lower()
    if f.suffix == ".onnx":
        return "MDX-Net"
    if "roformer" in n:
        return "Roformer"
    if f.suffix == ".ckpt":
        return "MDX23C"
    if f.parent.name == "Demucs_Models" or n.startswith(("htdemucs", "hdemucs")):
        return "Demucs"
    return "VR"


def _scopo(nome: str) -> str:
    n = nome.lower()
    if "denoise" in n or "noise" in n:
        return "noise removal"
    if "reverb" in n or "echo" in n:
        return "reverb/echo removal"
    if "karaoke" in n:
        return "lead vs backing vocals"
    if "crowd" in n:
        return "crowd removal"
    return "vocals / instrumental"


def modelli() -> list[dict]:
    """I modelli presenti sul disco (UVR installato + scaricati), con architettura e scopo."""
    visti, out = set(), []
    for d in cartelle():
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in ESTENSIONI and f.name not in visti:
                visti.add(f.name)
                out.append({"name": f.name, "arch": _arch(f), "use": _scopo(f.name), "dir": str(d),
                            "size_mb": round(f.stat().st_size / 1e6)})
    return out


def scegli(model: str | None) -> tuple[str, Path]:
    """(nome file, cartella) del modello: quello chiesto, o il migliore per voce/base presente."""
    locali = modelli()
    if model:
        for m in locali:
            if m["name"] == model or Path(m["name"]).stem == model:
                return m["name"], Path(m["dir"])
        # non c'e': audio-separator lo scarica (se lo conosce) nella cartella di medit
        return model, _home() / "uvr_models"
    voce = [m for m in locali if m["use"] == "vocals / instrumental"]
    for pref in PREFERITI:
        for m in voce:
            if m["name"].startswith(pref) or pref.lower() in m["name"].lower():
                return m["name"], Path(m["dir"])
    if voce:
        return voce[0]["name"], Path(voce[0]["dir"])
    return DEFAULT_SCARICABILE, _home() / "uvr_models"


def stato() -> dict:
    py = python()
    u = uvr_install()
    out = {"ok": bool(py), "python": py, "uvr_models_dir": str(u) if u else None,
           "models": [m["name"] for m in modelli()]}
    if not py:
        out["hint"] = ("run `medit uvr install`: it adds audio-separator (+ onnxruntime) on top of Applio's "
                       "environment (its torch with CUDA is reused, Applio is not modified)")
    return out


def _nome_stem(f: Path) -> str:
    gruppi = re.findall(r"\(([^)]+)\)", f.stem)
    return gruppi[-1] if gruppi else f.stem


def separa(src: Path, outdir: Path, model: str | None = None, timeout: float = 3600.0) -> dict[str, Path]:
    """File audio -> {stem: file}. Gli stem sono quelli del modello: Vocals/Instrumental,
    No Noise/Noise, No Reverb/Reverb, Drums/Bass/Other..."""
    py = python()
    if not py:
        raise UvrError(stato()["hint"])
    nome, mdir = scegli(model)
    mdir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    prima = set(outdir.glob("*.wav"))
    try:
        p = subprocess.run([py, "-c", _SCRIPT, str(src), str(outdir), nome, str(mdir)], capture_output=True,
                           timeout=timeout, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired as exc:
        raise UvrError("UVR separation took too long") from exc
    nuovi = sorted(set(outdir.glob("*.wav")) - prima)
    log = "\n".join((x or b"").decode("utf-8", "replace") for x in (p.stdout, p.stderr))
    try:
        (outdir / "uvr.log").write_text(log, encoding="utf-8")   # per capire cosa e' successo
    except OSError:
        pass
    # audio-separator a volte esce con un errore *dopo* aver scritto gli stem (pulizia di CUDA,
    # avvisi): se gli stem ci sono tutti, il lavoro e' buono
    if not nuovi or (p.returncode != 0 and len(nuovi) < 2):
        raise UvrError(f"UVR separation with {nome} failed: {log.strip()[-700:]}")
    return {_nome_stem(f): f for f in nuovi}


def torch_di(python_base: str) -> str | None:
    """La versione di torch dell'ambiente base (es. '2.11.0+cu130'), o None."""
    try:
        p = subprocess.run([python_base, "-c", "import torch; print(torch.__version__)"], capture_output=True,
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    v = p.stdout.decode().strip().splitlines()
    return v[-1] if p.returncode == 0 and v else None


def comando_installazione(applio_python: str | None, torch_base: str | None = None) -> list[list[str]]:
    """I comandi che creano ~/.medit/uvr-env sopra l'ambiente di Applio (o un Python qualunque).

    Il torch della base (con CUDA) non va mai sostituito: niente ``--upgrade`` e un vincolo sulla sua
    versione. torchvision (che Applio non ha) si prende abbinato, dall'indice PyTorch della stessa CUDA.
    """
    base = applio_python or sys.executable
    py_env = str(env_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    cmd = [[base, "-m", "venv", "--system-site-packages", str(env_dir())]]
    vincoli = []
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:\+(\w+))?", torch_base or "")
    if m:
        tv = f"0.{int(m.group(2)) + 15}.{m.group(3)}"
        vincoli = [f"torch=={m.group(1)}.{m.group(2)}.{m.group(3)}", f"torchvision=={tv}"]
        indice = f"https://download.pytorch.org/whl/{m.group(4) or 'cpu'}"
        cmd.append([py_env, "-m", "pip", "install", "--no-deps", f"torchvision=={tv}", "--index-url", indice])
    f = env_dir().parent / "uvr-constraints.txt"
    cmd.append([py_env, "-m", "pip", "install", "audio-separator", "onnxruntime", *(["-c", str(f)] if vincoli else [])])
    comando_installazione.vincoli = (f, vincoli)
    return cmd


def installa(applio_python: str | None, stampa=print) -> dict:
    tb = torch_di(applio_python) if applio_python else None
    comandi = comando_installazione(applio_python, tb)
    f, vincoli = comando_installazione.vincoli
    if vincoli:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(vincoli) + "\n", encoding="utf-8")
        stampa(f"keeping torch {tb} from the base environment")
    for cmd in comandi:
        stampa("$ " + " ".join(cmd))
        p = subprocess.run(cmd)
        if p.returncode != 0:
            raise UvrError(f"failed: {' '.join(cmd)}")
    return stato()


__all__ = ["modelli", "stato", "separa", "installa"]
