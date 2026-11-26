"""File MIDI standard: importare (in tracce e clip) ed esportare (tutte le note).

Le note in uscita sono quelle che si sentono: loop espansi, trasposizione delle
clip, clip mute escluse. In entrata ogni traccia/canale con note diventa una
traccia MIDI con il suono interno piu' vicino al programma General MIDI.
"""

from __future__ import annotations

import math
from pathlib import Path

import mido

from .model import Project

TPB = 480

# categoria del suono interno -> programma GM, per chi apre il .mid altrove
_GM_PER_CATEGORIA = {"keys": 0, "pad": 89, "lead": 81, "pluck": 104, "guitar": 25, "bass": 33, "drums": 0}


def _note_suonate(project: Project, track) -> list[tuple[float, float, int, int]]:
    out = []
    for c in track.clips:
        if c.muted or c.kind != "midi":
            continue
        L = c.loop_length if c.loop_length > 0 else c.length
        rip = int(math.ceil(c.length / L - 1e-9)) if c.loop_length > 0 else 1
        for k in range(rip):
            for n in c.notes:
                if c.loop_length > 0 and n.start >= L - 1e-9:
                    continue
                t = k * L + n.start
                if t >= c.length - 1e-9:
                    continue
                p = n.pitch + c.transpose
                if 0 <= p <= 127:
                    out.append((c.start + t, min(n.length, c.length - t), p, n.velocity))
    return sorted(out)


def export(project: Project, path: str, tracks: list[str] | None = None) -> dict:
    from . import presets

    mf = mido.MidiFile(type=1, ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    mf.tracks.append(meta)
    meta.append(mido.MetaMessage("track_name", name=project.name, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(project.bpm), time=0))
    num, den = (project.time_sig + [4, 4])[:2]
    meta.append(mido.MetaMessage("time_signature", numerator=int(num), denominator=int(den), time=0))
    # i marker delle sezioni vanno in ordine di tempo, con i delta giusti
    eventi_meta = [(0, m) for m in meta[:3]] + [(int(round(s.start * TPB)), mido.MetaMessage("marker", text=s.name))
                                                 for s in sorted(project.sections, key=lambda s: s.start)]
    meta.clear()
    prec = 0
    for t, m in sorted(eventi_meta, key=lambda x: x[0]):
        meta.append(m.copy(time=t - prec))
        prec = t
    scritte = 0
    canale_libero = 0
    for tr in project.tracks:
        if tr.kind != "midi" or (tracks and tr.id not in tracks and tr.name not in tracks):
            continue
        note = _note_suonate(project, tr)
        if not note:
            continue
        mt = mido.MidiTrack()
        mt.append(mido.MetaMessage("track_name", name=tr.name or tr.id, time=0))
        batteria = tr.instrument is not None and tr.instrument.type == "drums"
        if batteria:
            ch = 9
        else:
            ch = canale_libero % 16
            if ch == 9:
                canale_libero += 1
                ch = canale_libero % 16
            canale_libero += 1
            cat = ""
            if tr.instrument and tr.instrument.preset:
                try:
                    cat = presets.sound(tr.instrument.preset).get("category", "")
                except ValueError:
                    cat = ""
            mt.append(mido.Message("program_change", channel=ch, program=_GM_PER_CATEGORIA.get(cat, 0), time=0))
        ev = []
        for s, d, p, v in note:
            ev.append((int(round(s * TPB)), 1, p, v))
            ev.append((int(round((s + d) * TPB)), 0, p, 0))
        ev.sort(key=lambda e: (e[0], e[1]))
        prec = 0
        for t, on, p, v in ev:
            msg = "note_on" if on else "note_off"
            mt.append(mido.Message(msg, channel=ch, note=int(p), velocity=int(v) if on else 0, time=t - prec))
            prec = t
        mf.tracks.append(mt)
        scritte += 1
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    mf.save(path)
    return {"path": str(Path(path).resolve()), "tracks": scritte}


def read(path: str) -> dict:
    """{"bpm", "time_sig", "tracks": [{"name", "program", "drums", "notes": [(beat, len, pitch, vel)]}]}."""
    try:
        mf = mido.MidiFile(path)
    except (OSError, ValueError, EOFError) as exc:
        raise ValueError(f"cannot read MIDI file {path}: {exc}") from exc
    tpb = mf.ticks_per_beat or TPB
    bpm = 0.0
    time_sig = None
    tracce: dict[tuple[int, int], dict] = {}
    for i, tr in enumerate(mf.tracks):
        nome = ""
        t = 0
        aperte: dict[tuple[int, int], list[tuple[int, int]]] = {}
        programmi: dict[int, int] = {}
        for msg in tr:
            t += msg.time
            if msg.type == "track_name":
                nome = msg.name
            elif msg.type == "set_tempo" and not bpm:
                bpm = round(mido.tempo2bpm(msg.tempo), 2)
            elif msg.type == "time_signature" and time_sig is None:
                time_sig = [msg.numerator, msg.denominator]
            elif msg.type == "program_change":
                programmi[msg.channel] = msg.program
            elif msg.type == "note_on" and msg.velocity > 0:
                aperte.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                lista = aperte.get((msg.channel, msg.note))
                if lista:
                    t0, vel = lista.pop(0)
                    chiave = (i, msg.channel)
                    voce = tracce.setdefault(chiave, {"name": nome, "program": programmi.get(msg.channel, 0),
                                                      "drums": msg.channel == 9, "notes": []})
                    voce["notes"].append((t0 / tpb, max(1, t - t0) / tpb, msg.note, vel))
        for chiave, voce in tracce.items():
            if chiave[0] == i and not voce["name"]:
                voce["name"] = nome
    out = []
    for (i, ch), v in sorted(tracce.items()):
        v["notes"].sort()
        if not v["name"]:
            v["name"] = "Drums" if v["drums"] else f"MIDI {len(out) + 1}"
        out.append(v)
    return {"bpm": bpm or 120.0, "time_sig": time_sig or [4, 4], "tracks": out}
