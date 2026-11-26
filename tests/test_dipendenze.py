"""Ogni import di terze parti del backend deve essere dichiarato in pyproject.toml."""

import ast
import sys
import tomllib
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
NOMI = {"PIL": "pillow", "yaml": "pyyaml"}
FACOLTATIVI = {"anthropic"}   # extra "chat": importato solo dentro le funzioni che lo usano


def test_imports_are_declared():
    conf = tomllib.loads((RADICE / "pyproject.toml").read_text(encoding="utf-8"))
    dichiarate = {d.split(">")[0].split("[")[0].split("=")[0].strip().lower() for d in conf["project"]["dependencies"]}
    for extra in conf["project"]["optional-dependencies"].values():
        dichiarate |= {d.split(">")[0].split("[")[0].strip().lower() for d in extra}
    mancanti = set()
    for f in (RADICE / "backend" / "medit").glob("*.py"):
        for nodo in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Import):
                nomi = [a.name.split(".")[0] for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                nomi = [nodo.module.split(".")[0]]
            else:
                continue
            for n in nomi:
                if n in sys.stdlib_module_names or n == "medit" or n in FACOLTATIVI:
                    continue
                if NOMI.get(n, n).lower().replace("_", "-") not in dichiarate:
                    mancanti.add(f"{f.name}: {n}")
    assert not mancanti, mancanti
