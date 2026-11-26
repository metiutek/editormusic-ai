"""Ritara i livelli dei suoni inclusi: stampa i gain_db da mettere in presets._CALIBRAZIONE.

    python scripts/calibra_suoni.py [gains.json]
"""
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "backend"))
from medit import analyze, presets, synth, theory  # noqa: E402

sr = 44100
bpm = 110
spb = 60 / bpm
TARGET = {"drums": -19.0, "bass": -21.0, "keys": -23.0, "pad": -25.0, "lead": -22.0, "pluck": -23.0, "guitar": -23.0}
prog = theory.parse_progression("Am F C G Am F C G")
out = {}
for name, s in presets.SOUNDS.items():
    cat = s["category"]
    if cat == "drums":
        notes, _ = theory.drum_notes("pop", 8)
    elif cat == "bass":
        notes = theory.bass_notes(prog, "pulse", 2)
    elif cat == "lead":
        notes = theory.parse_melody("E5:1 D5:0.5 C5:0.5 A4:2 C5:1 D5:1 E5:2 G5:1 E5:3 " * 2)
    elif cat in ("pluck",):
        notes = theory.arp_notes(prog, "up", 0.25)
    elif cat == "guitar":
        notes = theory.chords_notes(prog, "strum")
    else:
        notes = theory.chords_notes(prog, "block")
    ev = [(int(n["start"] * spb * sr), int(n["length"] * spb * sr), n["pitch"], n["velocity"]) for n in notes]
    y = synth.render_notes(s["type"], s["params"], ev, int(32 * spb * sr) + sr * 2, sr)
    lu = analyze.loudness(y, sr)["lufs"]
    delta = TARGET[cat] - lu
    out[name] = round(s["params"].get("gain_db", 0.0) + delta, 1)
    print(f"{name:18} {cat:7} {lu:7.2f} -> gain_db {out[name]:+.1f}  peak {20 * __import__('numpy').log10(abs(y).max() + 1e-9):+.1f}")
if len(sys.argv) > 1:
    json.dump(out, open(sys.argv[1], "w"), indent=1)
else:
    print(json.dumps(out, indent=1))
