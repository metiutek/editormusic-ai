"""Riga di comando: le stesse operazioni dell'interfaccia, sullo stesso file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, analyze, audio_io, presets
from . import effects as fx
from .store import EditError, Store


def _stampa(x) -> None:
    print(json.dumps(x, indent=2, ensure_ascii=False, default=str))


def cmd_new(a) -> None:
    s = Store.create(name=a.name or Path(a.project).stem, bpm=a.bpm, key=a.key, mode=a.mode, path=a.project,
                     from_audio=a.from_audio)
    _stampa({"path": s.path, "bpm": s.project.bpm, "key": f"{s.project.key} {s.project.mode}"})


def cmd_info(a) -> None:
    _stampa(Store.open(a.project).summary("full" if a.full else "normal"))


def cmd_drums(a) -> None:
    _stampa(Store.open(a.project).add_drums(a.genre, a.track, a.bar, a.bars, a.intensity, a.fill_every))


def cmd_chords(a) -> None:
    _stampa(Store.open(a.project).add_chords(a.progression, a.track, a.bar, a.style, bars=a.bars, sound=a.sound))


def cmd_bass(a) -> None:
    _stampa(Store.open(a.project).add_bassline(a.progression, a.track, a.bar, a.style, bars=a.bars, sound=a.sound))


def cmd_melody(a) -> None:
    _stampa(Store.open(a.project).add_melody(a.melody, a.track, a.bar, a.sound))


def cmd_audio(a) -> None:
    s = Store.open(a.project)
    for f in a.files:
        _stampa(s.add_audio(path=f, bar=a.bar, adopt_tempo=a.adopt_tempo))


def cmd_master(a) -> None:
    _stampa(Store.open(a.project).auto_master(a.lufs, a.style))


def cmd_export(a) -> None:
    s = Store.open(a.project)
    if a.stems:
        _stampa(s.export_stems(a.output))
    elif a.output.lower().endswith((".mid", ".midi")):
        _stampa(s.export_midi(a.output))
    else:
        _stampa(s.export_audio(a.output, bit_depth=a.bits))


def cmd_review(a) -> None:
    _stampa(Store.open(a.project).review(a.lufs))


def cmd_analyze(a) -> None:
    p = Path(a.file)
    if p.suffix.lower() == ".json":
        _stampa(Store.open(str(p)).analyze())
        return
    x = audio_io.load(p, 22050)
    _stampa({**analyze.detect_tempo(x, 22050), "key": analyze.detect_key(x, 22050), **analyze.stats(x, 22050)})


def cmd_sounds(a) -> None:
    for x in presets.describe_sounds():
        print(f"{x['name']:18} {x['category']:7} {x['type']:6} {x['desc']}")


def cmd_chains(a) -> None:
    for x in presets.describe_chains():
        print(f"{x['name']:18} {', '.join(x['effects']):40} {x['desc']}")


def cmd_effects(a) -> None:
    for e in fx.describe():
        print(f"{e['name']:14} {e['group']:10} {e['desc']}")
        if a.verbose:
            for k, p in e["params"].items():
                rng = f"[{p.get('min')}, {p.get('max')}]" if "min" in p else ""
                print(f"    {k:14} {p['type']:7} default={p['default']} {rng}  {p['desc']}")


def cmd_key(a) -> None:
    from . import cloud

    st = cloud.imposta(a.service, a.key, default=True if a.default else None)
    _stampa(st["services"][a.service] | {"default": st["default"]})


def cmd_uvr(a) -> None:
    from . import uvr, voce

    if a.azione == "install":
        r = voce.radice()
        py = str(voce._python(r)) if r else None
        print(f"base environment: {'Applio (' + py + ')' if py else 'this Python (Applio not found: torch will be downloaded)'}")
        _stampa(uvr.installa(py))
    else:
        _stampa({**uvr.stato(), "models": uvr.modelli()})


def cmd_ai(a) -> None:
    from . import ai

    _stampa(ai.status())


def cmd_doctor(a) -> None:
    import importlib.util

    righe = [("python", sys.version.split()[0], True)]
    for mod in ("numpy", "scipy", "soundfile", "mido", "PIL", "fastapi", "mcp"):
        ok = importlib.util.find_spec(mod) is not None
        righe.append((mod, "ok" if ok else "MISSING", ok))
    try:
        import soundfile as sf

        mp3 = "MP3" in sf.available_formats()
        righe.append(("mp3 read/write", f"libsndfile {sf.__libsndfile_version__}" if mp3 else
                      "libsndfile without MP3: export .wav/.flac", mp3))
    except Exception as exc:  # noqa: BLE001
        righe.append(("soundfile", str(exc), False))
    ff = audio_io.ffmpeg()
    righe.append(("ffmpeg", ff or "not found: m4a/aac/video audio need it (optional)", bool(ff)))
    righe.append(("chat (anthropic)", "ok" if importlib.util.find_spec("anthropic") else
                  "optional: pip install medit-mcp[chat] for an Anthropic key in the UI", True))
    from .api import FRONTEND

    ui = (FRONTEND / "index.html").is_file()
    righe.append(("web UI", str(FRONTEND) if ui else "not built: cd frontend && npm ci && npm run build", ui))
    from . import ai

    st = ai.status()
    c = st["comfyui"]
    righe.append(("ComfyUI", c["url"] + (f" (song: {c.get('song_model') or 'no ACE-Step'}, sound: "
                                          f"{c.get('audio_model') or 'no Stable Audio'})" if c["ok"] else " not running"),
                  bool(c["ok"])))
    u = st["uvr"]
    righe.append(("stems (UVR)", (u["python"] if u["ok"] else u["hint"]) + f" - models: {', '.join(u['models']) or 'none'}",
                  u["ok"]))
    righe.append(("stems (Demucs)", st["stems"].get("python") or st["stems"]["hint"], st["stems"]["ok"]))
    v = st["voice"]
    righe.append(("voice (Applio)", f"{v['path']} - {', '.join(v.get('models') or []) or 'no models'}"
                  if v.get("path") else v["hint"], v["ok"]))
    pronti = [k for k, x in st["cloud"]["services"].items() if x["ready"]]
    righe.append(("online services", ", ".join(pronti) or "none (medit key <service> <key>)", True))
    for nome, val, ok in righe:
        print(f"{'ok ' if ok else '-- '} {nome:18} {val}")


def cmd_ui(a) -> None:
    from . import api

    s = None
    if a.project:
        p = Path(a.project)
        s = Store.open(str(p)) if p.exists() else Store.create(name=p.stem, path=str(p))
    else:
        s = Store.create(name="untitled")
    api.serve(s, host=a.host, port=a.port, browser=not a.no_browser)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="medit", description="AI music editor (DAW) - web UI, chat and MCP server")
    ap.add_argument("--version", action="version", version=f"medit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ui", help="open the web editor")
    s.add_argument("project", nargs="?")
    s.add_argument("--port", type=int, default=8780)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_ui)

    s = sub.add_parser("new", help="create a song")
    s.add_argument("project")
    s.add_argument("--name")
    s.add_argument("--bpm", type=float, default=120)
    s.add_argument("--key", default="C")
    s.add_argument("--mode", default="major")
    s.add_argument("--from-audio")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("info", help="show a song")
    s.add_argument("project")
    s.add_argument("--full", action="store_true")
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("drums", help="add a drum pattern")
    s.add_argument("project")
    s.add_argument("genre")
    s.add_argument("--track")
    s.add_argument("--bar", type=float, default=1)
    s.add_argument("--bars", type=float, default=4)
    s.add_argument("--intensity", default="normal")
    s.add_argument("--fill-every", type=int, default=0)
    s.set_defaults(fn=cmd_drums)

    for nome, fn, stile in (("chords", cmd_chords, "block"), ("bass", cmd_bass, "root")):
        s = sub.add_parser(nome, help=f"add {nome} from a progression")
        s.add_argument("project")
        s.add_argument("progression")
        s.add_argument("--track")
        s.add_argument("--bar", type=float, default=1)
        s.add_argument("--bars", type=float)
        s.add_argument("--style", default=stile)
        s.add_argument("--sound")
        s.set_defaults(fn=fn)

    s = sub.add_parser("melody", help="add a melody in text notation (C5:1 D5:0.5 ...)")
    s.add_argument("project")
    s.add_argument("melody")
    s.add_argument("--track")
    s.add_argument("--bar", type=float, default=1)
    s.add_argument("--sound")
    s.set_defaults(fn=cmd_melody)

    s = sub.add_parser("audio", help="put audio files on new tracks")
    s.add_argument("project")
    s.add_argument("files", nargs="+")
    s.add_argument("--bar", type=float, default=1)
    s.add_argument("--adopt-tempo", action="store_true")
    s.set_defaults(fn=cmd_audio)

    s = sub.add_parser("master", help="master to a loudness")
    s.add_argument("project")
    s.add_argument("--lufs", type=float, default=-14)
    s.add_argument("--style", default="streaming")
    s.set_defaults(fn=cmd_master)

    s = sub.add_parser("export", help="render to audio (.wav .flac .mp3 .ogg), .mid, or --stems to a folder")
    s.add_argument("project")
    s.add_argument("output")
    s.add_argument("--bits", type=int, default=24)
    s.add_argument("--stems", action="store_true")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("review", help="what is wrong with a song")
    s.add_argument("project")
    s.add_argument("--lufs", type=float, default=-14)
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("analyze", help="BPM, key and loudness of an audio file (or a song .json)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("sounds", help="list instrument presets")
    s.set_defaults(fn=cmd_sounds)
    s = sub.add_parser("chains", help="list effect chains")
    s.set_defaults(fn=cmd_chains)
    s = sub.add_parser("effects", help="list effects")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_effects)
    s = sub.add_parser("key", help="save the API key of an online music service (elevenlabs, replicate)")
    s.add_argument("service")
    s.add_argument("key")
    s.add_argument("--default", action="store_true", help="use it when backend is auto")
    s.set_defaults(fn=cmd_key)
    s = sub.add_parser("uvr", help="Ultimate Vocal Remover models: list them, or install the runner")
    s.add_argument("azione", choices=["models", "install"], nargs="?", default="models")
    s.set_defaults(fn=cmd_uvr)
    s = sub.add_parser("ai", help="what AI is available here")
    s.set_defaults(fn=cmd_ai)
    s = sub.add_parser("doctor", help="check what is installed")
    s.set_defaults(fn=cmd_doctor)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (EditError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
