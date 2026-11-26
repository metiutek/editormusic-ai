"""Operazioni di editing sul documento + persistenza.

Questo modulo e' l'unica superficie di modifica: il server MCP, l'API della UI,
l'assistente in chat e la riga di comando chiamano gli stessi metodi, quindi UI
e agente non possono divergere. Ogni mutazione prende uno snapshot per
undo/redo e (se il documento ha un file) salva su disco.

Convenzioni dei parametri (le stesse per UI, MCP e chat):
- l'arrangiamento si indica in **battute 1-based** (``bar=1`` = inizio, ``bar=5.5``
  = meta' della quinta battuta) e lunghezze in battute (``bars``);
- le note stanno in **beat relativi all'inizio della clip** (0 = inizio clip);
- una traccia, una clip o una sezione si indicano con l'id o con il nome.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from . import ai, analyze, audio_io, cloud, comfy, midi_io, presets, render, separa, synth, theory, trascrivi, uvr, voce
from . import effects as fx
from .model import (
    AUDIO_EXTS,
    INSTRUMENT_TYPES,
    MEDIA_EXTS,
    MIDI_EXTS,
    TRACK_COLORS,
    TRACK_KINDS,
    Asset,
    Automation,
    Clip,
    Effect,
    Instrument,
    Note,
    Project,
    Section,
    Send,
    Track,
    new_id,
    to_dict,
)

MAX_HISTORY = 100

SECTION_COLORS = {"intro": "#6b7cff", "verse": "#4fb8a8", "pre": "#d9c24f", "pre-chorus": "#d9c24f",
                  "chorus": "#e05a5a", "hook": "#e05a5a", "drop": "#e05a5a", "bridge": "#c46fd9",
                  "break": "#9aa0a6", "breakdown": "#9aa0a6", "build": "#e0915a", "outro": "#7f6fd9",
                  "solo": "#e0915a", "post-chorus": "#d96fa0"}

# la traccia da creare quando un generatore non ne riceve una
_AUTO_TRACCE = {"chords": ("Chords", "piano", "chords"), "bass": ("Bass", "saw bass", "bass"),
                "arp": ("Arp", "pluck", "arp"), "drums": ("Drums", "acoustic kit", "drums"),
                "melody": ("Lead", "soft lead", "lead")}
_KIT_PER_GENERE = {"trap": "trap kit", "hiphop": "808 kit", "lofi": "lofi kit", "house": "electro kit",
                   "techno": "electro kit", "reggaeton": "808 kit", "afrobeats": "808 kit", "disco": "electro kit"}


# formati che soundfile legge da solo; gli altri si convertono una volta in WAV
_NATIVI = {".wav", ".flac", ".ogg", ".mp3", ".aif", ".aiff"}


class EditError(ValueError):
    """Errore di editing con messaggio comprensibile all'utente."""


def _home() -> Path:
    base = Path(os.environ.get("MEDIT_HOME") or (Path.home() / ".medit"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _r(x: float, k: int = 4) -> float:
    return round(float(x), k)


class Store:
    def __init__(self, project: Project, path: str | None = None, autosave: bool = True):
        self.project = project
        self.path = str(Path(path).resolve()) if path else None
        self.autosave = autosave
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._batch = 0
        self.version = 0
        self.on_change = None
        self._scratch: Path | None = None
        # un metodo che ne chiama altri (add_bus -> add_track + apply_chain) resta UNA modifica
        self._in_edit = False
        # una scrittura alla volta: le generazioni IA lavorano minuti fuori dal lucchetto e
        # scrivono il risultato dentro, senza intrecciarsi con la UI o con l'agente
        self.lock = threading.RLock()

    # ---- ciclo di vita -------------------------------------------------
    @classmethod
    def create(cls, name: str = "untitled", bpm: float = 120.0, key: str = "C", mode: str = "major",
               time_sig: list[int] | None = None, path: str | None = None, sample_rate: int = 44100,
               from_audio: str | None = None) -> "Store":
        try:
            root, mod = theory.parse_key(key, mode)
        except theory.TheoryError as exc:
            raise EditError(str(exc)) from exc
        if not 20 <= float(bpm) <= 400:
            raise EditError("bpm must be between 20 and 400")
        if sample_rate not in (22050, 32000, 44100, 48000, 88200, 96000):
            raise EditError("sample_rate must be 22050, 32000, 44100, 48000, 88200 or 96000")
        ts = list(time_sig or [4, 4])
        if len(ts) != 2 or ts[1] not in (2, 4, 8, 16) or not 1 <= ts[0] <= 32:
            raise EditError("time_sig is [beats, note value], e.g. [4, 4], [3, 4], [6, 8]")
        nomi = theory.note_names_for(root, mod)
        s = cls(Project(name=name, bpm=float(bpm), key=nomi[root], mode=mod, time_sig=ts,
                        sample_rate=int(sample_rate)), path)
        if from_audio:
            def importa():
                r = s.add_audio(path=from_audio, bar=1, detect=True, adopt_tempo=True)
                return r
            s._autosave_off(importa)
            s._undo.clear()
        if path:
            s.save()
        return s

    def _autosave_off(self, fn):
        old, self.autosave = self.autosave, False
        try:
            return fn()
        finally:
            self.autosave = old

    @classmethod
    def open(cls, path: str) -> "Store":
        f = Path(path)
        if not f.exists():
            raise EditError(f"document not found: {path}")
        ext = f.suffix.lower()
        if ext in MEDIA_EXTS:
            # aprire un audio = canzone nuova con quel file su una traccia, non salvata
            return cls.create(name=f.stem, from_audio=str(f))
        if ext in MIDI_EXTS:
            s = cls.create(name=f.stem)
            s._autosave_off(lambda: s.import_midi(str(f), adopt_tempo=True))
            s._undo.clear()
            return s
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise EditError(f"{f.name} is not a medit song (.json)") from exc
        if "tracks" not in data:
            raise EditError(f"{f.name} is not a medit song: no tracks")
        return cls(Project.from_obj(data), str(f.resolve()))

    def save(self, path: str | None = None) -> str:
        """Salvataggio atomico: ``os.replace``, mai un file a meta'."""
        target = Path(path or self.path or "")
        if not str(target):
            raise EditError("no save path: pass path=")
        if target.suffix.lower() != ".json":
            raise EditError("a medit song is a .json file; to write audio use export_audio")
        target.parent.mkdir(parents=True, exist_ok=True)
        vecchia_base = self.base_dir
        self.path = str(target.resolve())
        self._riloca_asset(vecchia_base)
        blob = json.dumps(self.project.to_dict(), indent=1, ensure_ascii=False)
        last: OSError | None = None
        for attempt in range(10):
            tmp = target.with_name(f"~{uuid.uuid4().hex[:8]}_{target.name}")
            try:
                tmp.write_text(blob, encoding="utf-8")
                os.replace(tmp, target)
                break
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                last = exc
                time.sleep(0.02 * (attempt + 1))
        else:
            raise EditError(f"saving to {target} failed: {last}")
        return self.path

    def _riloca_asset(self, vecchia_base: str | None) -> None:
        for a in self.project.assets:
            p = render.resolve(a.path, vecchia_base)
            a.path = self._percorso_asset(p)

    def _percorso_asset(self, p: Path) -> str:
        p = p.resolve()
        if self.base_dir:
            try:
                return p.relative_to(self.base_dir).as_posix()
            except ValueError:
                pass
        return str(p)

    @property
    def base_dir(self) -> str | None:
        return str(Path(self.path).parent) if self.path else None

    def assets_dir(self) -> Path:
        """Dove finiscono le rese, gli stem, le generazioni."""
        if self.path:
            d = Path(self.path).with_name(Path(self.path).stem + "_assets")
        else:
            if self._scratch is None:
                self._scratch = _home() / "scratch" / uuid.uuid4().hex[:12]
            d = self._scratch
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- undo/redo -----------------------------------------------------
    def _touch(self) -> None:
        if self._batch:
            return
        self._undo.append(self.project.to_dict())
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()

    def _done(self) -> None:
        if self._batch:
            return
        self.version += 1
        if self.autosave and self.path:
            self.save()
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - un osservatore rotto non annulla la modifica
                pass

    @contextmanager
    def batch(self):
        """Piu' operazioni come una: un undo, un salvataggio, tutto o niente."""
        if self._batch:
            self._batch += 1
            try:
                yield self
            finally:
                self._batch -= 1
            return
        self.lock.acquire()
        try:
            self._undo.append(self.project.to_dict())
            if len(self._undo) > MAX_HISTORY:
                self._undo.pop(0)
            self._redo.clear()
            self._batch = 1
            try:
                yield self
            except Exception:
                self.project = Project.from_obj(self._undo.pop())
                self.version += 1
                raise
            finally:
                self._batch = 0
            self._done()
        finally:
            self.lock.release()

    @contextmanager
    def _edit(self):
        """Una modifica: snapshot prima, salvataggio dopo, e se fallisce si torna com'era.

        Rientrante: dentro un'altra modifica (o un batch) non aggiunge passi di undo.
        """
        if self._batch or self._in_edit:
            yield
            return
        with self.lock:
            yield from self._edit_fuori()

    def _edit_fuori(self):
        prima = self.project.to_dict()
        self._undo.append(prima)
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        redo = self._redo
        self._redo = []
        self._in_edit = True
        try:
            yield
        except Exception:
            self.project = Project.from_obj(prima)
            self._undo.pop()
            self._redo = redo
            raise
        finally:
            self._in_edit = False
        self._done()

    def undo(self) -> dict:
        with self.lock:
            if not self._undo:
                raise EditError("nothing to undo")
            self._redo.append(self.project.to_dict())
            self.project = Project.from_obj(self._undo.pop())
            self._done()
        return {"undo": len(self._undo), "redo": len(self._redo)}

    def redo(self) -> dict:
        with self.lock:
            if not self._redo:
                raise EditError("nothing to redo")
            self._undo.append(self.project.to_dict())
            self.project = Project.from_obj(self._redo.pop())
            self._done()
        return {"undo": len(self._undo), "redo": len(self._redo)}

    # ---- conversioni ---------------------------------------------------
    @property
    def bpb(self) -> float:
        return self.project.beats_per_bar

    def _beat(self, bar: float) -> float:
        bar = float(bar)
        if bar < 1:
            raise EditError(f"bar {bar:g} is before the start: bars start at 1")
        return self.project.bar_to_beat(bar)

    def _bars(self, bars: float, what: str = "bars") -> float:
        bars = float(bars)
        if bars <= 0:
            raise EditError(f"{what} must be > 0")
        if bars > 2000:
            raise EditError(f"{what} = {bars:g} is too long")
        return bars * self.bpb

    def _bar(self, beat: float) -> float:
        return _r(self.project.beat_to_bar(beat), 3)

    # ---- lettura -------------------------------------------------------
    def summary(self, detail: str = "normal") -> dict:
        p = self.project
        fine = p.end_beat()
        out = {"name": p.name, "bpm": p.bpm, "key": p.key, "mode": p.mode, "time_sig": p.time_sig,
               "swing": p.swing, "sample_rate": p.sample_rate,
               "bars": _r(fine / self.bpb, 2), "duration_s": _r(p.beat_to_s(fine), 1),
               "path": self.path, "undo": len(self._undo), "redo": len(self._redo)}
        out["sections"] = [{"id": s.id, "name": s.name, "bar": self._bar(s.start), "bars": _r(s.length / self.bpb, 3),
                            **({"lyrics": s.lyrics} if s.lyrics and detail != "brief" else {})}
                           for s in sorted(p.sections, key=lambda s: s.start)]
        out["tracks"] = [self.track_view(t, detail) for t in p.tracks]
        out["master"] = {"volume_db": p.master.volume_db,
                         "effects": [self._fx_view(e, detail) for e in p.master.effects]}
        if p.loop:
            out["loop"] = [self._bar(p.loop[0]), self._bar(p.loop[1])]
        if detail == "full":
            out["assets"] = [to_dict(a) for a in p.assets]
        elif p.assets:
            out["assets"] = [{"id": a.id, "name": a.name, "duration": _r(a.duration, 2)}
                             | ({"bpm": a.bpm} if a.bpm else {}) | ({"key": a.key} if a.key else {})
                             for a in p.assets]
        return out

    def _fx_view(self, e: Effect, detail: str) -> dict | str:
        if detail == "brief":
            return e.type + ("" if e.enabled else " (off)")
        spec = fx.REGISTRY.get(e.type, {}).get("params", {})
        diversi = {k: v for k, v in e.params.items() if k not in spec or spec[k]["default"] != v}
        out = {"type": e.type}
        if diversi or detail == "full":
            out["params"] = e.params if detail == "full" else diversi
        if not e.enabled:
            out["enabled"] = False
        return out

    def track_view(self, t: Track, detail: str = "normal") -> dict:
        out: dict[str, Any] = {"id": t.id, "name": t.name, "kind": t.kind}
        if t.role:
            out["role"] = t.role
        if t.instrument:
            out["instrument"] = t.instrument.preset or t.instrument.type
            if detail == "full":
                out["instrument_type"] = t.instrument.type
                out["instrument_params"] = t.instrument.params
        out["volume_db"] = t.volume_db
        if t.pan:
            out["pan"] = t.pan
        if t.mute:
            out["mute"] = True
        if t.solo:
            out["solo"] = True
        if t.effects:
            out["effects"] = [self._fx_view(e, detail) for e in t.effects]
        if t.sends:
            out["sends"] = [{"bus": s.bus, "level_db": s.level_db} for s in t.sends]
        if t.automation:
            out["automation"] = [{"target": a.target, "points": len(a.points)} if detail != "full" else
                                 {"target": a.target, "points": [[self._bar(b), v] for b, v in a.points]}
                                 for a in t.automation]
        if detail != "brief":
            out["clips"] = [self.clip_view(c, detail) for c in sorted(t.clips, key=lambda c: c.start)]
        else:
            out["clips"] = len(t.clips)
        if detail == "full":
            out["color"] = t.color
        return out

    def clip_view(self, c: Clip, detail: str = "normal") -> dict:
        out: dict[str, Any] = {"id": c.id, "name": c.name, "bar": self._bar(c.start), "bars": _r(c.length / self.bpb, 3)}
        if c.kind == "midi":
            out["notes"] = len(c.notes)
            if c.notes:
                ps = [n.pitch + c.transpose for n in c.notes]
                out["range"] = f"{theory.pitch_name(min(ps))}-{theory.pitch_name(max(ps))}"
            if detail == "full":
                out["note_list"] = self._note_list(c)
        else:
            out["asset"] = c.asset
            if c.offset:
                out["offset_s"] = _r(c.offset, 3)
        if c.loop_length:
            out["loop_bars"] = _r(c.loop_length / self.bpb, 3)
        for k in ("gain_db", "fade_in", "fade_out", "transpose"):
            v = getattr(c, k)
            if v:
                out[k] = v
        if c.muted:
            out["muted"] = True
        return out

    @staticmethod
    def _note_list(c: Clip) -> list:
        return [[theory.pitch_name(n.pitch), _r(n.start), _r(n.length), n.velocity]
                for n in sorted(c.notes, key=lambda n: (n.start, n.pitch))]

    def get_notes(self, clip: str) -> dict:
        t, c = self._clip(clip, edit=False)
        return {"clip": c.id, "track": t.name, "bar": self._bar(c.start), "bars": _r(c.length / self.bpb, 3),
                "format": "[pitch, start_beat, length_beats, velocity] - start from the clip start",
                "notes": self._note_list(c)}

    # ---- ricerca -------------------------------------------------------
    def _track(self, ref: str) -> Track:
        try:
            return self.project.track(ref)
        except KeyError as exc:
            nomi = ", ".join(f"{t.name} ({t.id})" for t in self.project.tracks) or "none"
            raise EditError(f"{exc.args[0]}; tracks: {nomi}") from None

    def _clip(self, ref: str, edit: bool = True) -> tuple[Track, Clip]:
        try:
            return self.project.clip(ref)
        except KeyError as exc:
            raise EditError(str(exc.args[0])) from None

    def _section(self, ref: str) -> Section:
        try:
            return self.project.section(ref)
        except KeyError as exc:
            nomi = ", ".join(s.name for s in self.project.sections) or "none"
            raise EditError(f"{exc.args[0]}; sections: {nomi}") from None

    def _nome_traccia(self, base: str) -> str:
        nomi = {t.name.lower() for t in self.project.tracks}
        if base.lower() not in nomi:
            return base
        k = 2
        while f"{base} {k}".lower() in nomi:
            k += 1
        return f"{base} {k}"

    def _colore(self) -> str:
        usati = [t.color for t in self.project.tracks]
        for c in TRACK_COLORS:
            if c not in usati:
                return c
        return TRACK_COLORS[len(usati) % len(TRACK_COLORS)]

    # ---- canzone -------------------------------------------------------
    def set_song(self, name: str | None = None, bpm: float | None = None, key: str | None = None,
                 mode: str | None = None, time_sig: list[int] | None = None, swing: float | None = None,
                 loop: list[float] | None = None, clear_loop: bool = False) -> dict:
        with self._edit():
            p = self.project
            if name is not None:
                p.name = str(name)
            if bpm is not None:
                if not 20 <= float(bpm) <= 400:
                    raise EditError("bpm must be between 20 and 400")
                p.bpm = float(bpm)
            if key is not None or mode is not None:
                try:
                    root, mod = theory.parse_key(key or p.key, mode or (p.mode if key is None or " " not in str(key) else None))
                except theory.TheoryError as exc:
                    raise EditError(str(exc)) from exc
                p.key, p.mode = theory.note_names_for(root, mod)[root], mod
            if time_sig is not None:
                ts = list(time_sig)
                if len(ts) != 2 or ts[1] not in (2, 4, 8, 16) or not 1 <= ts[0] <= 32:
                    raise EditError("time_sig is [beats, note value], e.g. [4, 4], [3, 4], [6, 8]")
                p.time_sig = ts
            if swing is not None:
                p.swing = float(np.clip(swing, 0, 1))
            if clear_loop:
                p.loop = None
            elif loop is not None:
                if len(loop) != 2 or float(loop[1]) <= float(loop[0]):
                    raise EditError("loop is [first_bar, last_bar]")
                p.loop = [self._beat(loop[0]), self._beat(float(loop[1]) + 1)]
        return {"bpm": self.project.bpm, "key": self.project.key, "mode": self.project.mode,
                "time_sig": self.project.time_sig, "swing": self.project.swing}

    # ---- tracce --------------------------------------------------------
    def _instrument(self, sound: str | None, type: str | None, params: dict | None) -> Instrument:
        if sound:
            try:
                s = presets.sound(sound)
            except ValueError as exc:
                raise EditError(str(exc)) from exc
            par = dict(s["params"])
            if params:
                par.update(synth.validate(s["type"], params))
            return Instrument(type=s["type"], preset=sound, params=par)
        kind = type or "synth"
        if kind not in INSTRUMENT_TYPES:
            raise EditError(f"unknown instrument type {kind!r}; available: {', '.join(INSTRUMENT_TYPES)}")
        try:
            return Instrument(type=kind, preset="", params=synth.validate(kind, params or {}))
        except ValueError as exc:
            raise EditError(str(exc)) from exc

    def add_track(self, kind: str = "midi", name: str | None = None, sound: str | None = None,
                  instrument: str | None = None, params: dict | None = None, color: str | None = None,
                  volume_db: float = 0.0, pan: float = 0.0, role: str = "", index: int | None = None) -> dict:
        """kind: midi (with an instrument), audio (for audio files), bus (effect return)."""
        if kind not in TRACK_KINDS:
            raise EditError(f"track kind must be one of {', '.join(TRACK_KINDS)}")
        with self._edit():
            inst = None
            if kind == "midi":
                inst = self._instrument(sound or (None if instrument else "piano"), instrument, params)
                if not role:
                    cat = presets.sound(sound).get("category", "") if sound else ""
                    role = {"drums": "drums", "bass": "bass", "pad": "pad", "lead": "lead", "keys": "chords",
                            "guitar": "chords", "pluck": "arp"}.get(cat, "")
            base = name or ({"bus": "Bus", "audio": "Audio"}.get(kind) or (sound or "Synth").title())
            t = Track(id=new_id("T"), name=self._nome_traccia(base), kind=kind, color=color or self._colore(),
                      volume_db=float(volume_db), pan=float(np.clip(pan, -1, 1)), instrument=inst, role=role)
            if index is None:
                self.project.tracks.append(t)
            else:
                self.project.tracks.insert(int(index), t)
        return {"id": t.id, "name": t.name, "kind": kind, **({"instrument": inst.preset or inst.type} if inst else {})}

    def set_track(self, track: str, name: str | None = None, volume_db: float | None = None, pan: float | None = None,
                  mute: bool | None = None, solo: bool | None = None, color: str | None = None,
                  role: str | None = None) -> dict:
        with self._edit():
            t = self._track(track)
            if name is not None:
                t.name = str(name)
            if volume_db is not None:
                if not -96 <= float(volume_db) <= 24:
                    raise EditError("volume_db must be between -96 and +24")
                t.volume_db = _r(volume_db, 2)
            if pan is not None:
                t.pan = float(np.clip(pan, -1, 1))
            if mute is not None:
                t.mute = bool(mute)
            if solo is not None:
                t.solo = bool(solo)
            if color is not None:
                t.color = color
            if role is not None:
                t.role = role
        return self.track_view(t, "brief")

    def remove_track(self, track: str) -> dict:
        with self._edit():
            t = self._track(track)
            self.project.tracks.remove(t)
            for x in self.project.tracks:
                x.sends = [s for s in x.sends if s.bus != t.id]
        return {"removed": t.name}

    def duplicate_track(self, track: str, name: str | None = None) -> dict:
        with self._edit():
            t = self._track(track)
            n = copy.deepcopy(t)
            n.id = new_id("T")
            n.name = self._nome_traccia(name or t.name)
            n.solo = False
            for c in n.clips:
                c.id = new_id("C")
            self.project.tracks.insert(self.project.tracks.index(t) + 1, n)
        return {"id": n.id, "name": n.name}

    def move_track(self, track: str, index: int) -> dict:
        with self._edit():
            t = self._track(track)
            self.project.tracks.remove(t)
            i = int(np.clip(index, 0, len(self.project.tracks)))
            self.project.tracks.insert(i, t)
        return {"track": t.name, "index": i}

    def set_instrument(self, track: str, sound: str | None = None, type: str | None = None,
                       params: dict | None = None) -> dict:
        """Cambia suono (``sound`` = un preset) o ritocca i parametri (``params`` si fondono)."""
        with self._edit():
            t = self._track(track)
            if t.kind != "midi":
                raise EditError(f"{t.name!r} is an {t.kind} track: only MIDI tracks have an instrument")
            if sound or (type and (t.instrument is None or type != t.instrument.type)):
                t.instrument = self._instrument(sound, type, params)
            else:
                if t.instrument is None:
                    t.instrument = self._instrument("piano", None, None)
                try:
                    t.instrument.params.update(synth.validate(t.instrument.type, params or {}))
                except ValueError as exc:
                    raise EditError(str(exc)) from exc
        return {"track": t.name, "instrument": t.instrument.preset or t.instrument.type, "type": t.instrument.type}

    def save_sound(self, name: str, track: str, desc: str = "") -> dict:
        t = self._track(track)
        if not t.instrument:
            raise EditError(f"{t.name!r} has no instrument")
        try:
            return presets.save_sound(name, t.instrument.type, dict(t.instrument.params), desc)
        except ValueError as exc:
            raise EditError(str(exc)) from exc

    # ---- bus e mandate -------------------------------------------------
    def add_bus(self, name: str = "Reverb", chain: str | None = "big reverb bus", volume_db: float = 0.0) -> dict:
        with self._edit():
            r = self.add_track(kind="bus", name=name, volume_db=volume_db)
            if chain:
                self.apply_chain(r["id"], chain)
        return r

    def set_send(self, track: str, bus: str, level_db: float | None = -12.0, remove: bool = False) -> dict:
        with self._edit():
            t = self._track(track)
            b = self._track(bus)
            if b.kind != "bus":
                raise EditError(f"{b.name!r} is not a bus: create one with add_bus")
            if t.id == b.id or t.kind == "bus":
                raise EditError("buses cannot send to buses")
            t.sends = [s for s in t.sends if s.bus != b.id]
            if not remove and level_db is not None:
                t.sends.append(Send(bus=b.id, level_db=_r(level_db, 2)))
        return {"track": t.name, "sends": [{"bus": self.project.track(s.bus).name, "level_db": s.level_db} for s in t.sends]}

    # ---- clip ----------------------------------------------------------
    def _new_clip_name(self, t: Track, base: str | None) -> str:
        if base:
            return base
        return f"{t.name} {len(t.clips) + 1}"

    def _norm_note(self, n: Any) -> Note:
        try:
            if isinstance(n, (list, tuple)):
                pitch, start, length = n[0], n[1], n[2]
                vel = n[3] if len(n) > 3 else 100
            elif isinstance(n, dict):
                pitch = n.get("pitch", n.get("note"))
                start = n.get("start", n.get("time", 0))
                length = n.get("length", n.get("duration", n.get("len", 1)))
                vel = n.get("velocity", n.get("vel", 100))
            else:
                raise TypeError
            p = theory.parse_pitch(pitch)
        except (TypeError, IndexError, KeyError, theory.TheoryError) as exc:
            raise EditError(f"bad note {n!r}: use {{'pitch': 'C4', 'start': 0, 'length': 1, 'velocity': 100}} "
                            f"or ['C4', 0, 1, 100] ({exc})") from None
        if float(length) <= 0:
            raise EditError(f"note {n!r}: length must be > 0 beats")
        if float(start) < 0:
            raise EditError(f"note {n!r}: start must be >= 0 (beats from the clip start)")
        return Note(pitch=p, start=_r(start), length=_r(length), velocity=int(np.clip(int(vel), 1, 127)))

    def add_clip(self, track: str, bar: float = 1, bars: float | None = None, name: str | None = None,
                 notes: list | None = None, melody: str | None = None, loop_bars: float = 0) -> dict:
        """Clip MIDI vuota o con note. Senza ``bars`` e' lunga quanto le note (min 1 battuta)."""
        with self._edit():
            t = self._track(track)
            if t.kind != "midi":
                raise EditError(f"{t.name!r} is an {t.kind} track: use add_audio for audio")
            lista = [self._norm_note(n) for n in (notes or [])]
            if melody:
                try:
                    lista += [self._norm_note(n) for n in theory.parse_melody(melody)]
                except theory.TheoryError as exc:
                    raise EditError(str(exc)) from exc
            fine = max((n.start + n.length for n in lista), default=0.0)
            if bars is not None:
                length = self._bars(bars)
            else:
                length = max(self.bpb, math.ceil(fine / self.bpb - 1e-9) * self.bpb)
            c = Clip(id=new_id("C"), name=self._new_clip_name(t, name), kind="midi", start=self._beat(bar),
                     length=length, notes=lista, loop_length=self._bars(loop_bars) if loop_bars else 0.0)
            t.clips.append(c)
        return {"id": c.id, "track": t.name, "bar": self._bar(c.start), "bars": _r(c.length / self.bpb, 3),
                "notes": len(c.notes)}

    def _importa_audio(self, path: str, detect: bool = True) -> Asset:
        f = Path(path)
        if not f.is_file():
            raise EditError(f"audio file not found: {path}")
        if f.suffix.lower() not in MEDIA_EXTS:
            raise EditError(f"{f.suffix} is not an audio file; supported: {', '.join(sorted(AUDIO_EXTS))}")
        p = str(f.resolve())
        for a in self.project.assets:
            if render.resolve(a.path, self.base_dir).resolve() == Path(p):
                return a
        try:
            inf = audio_io.info(p)
        except audio_io.AudioError as exc:
            raise EditError(str(exc)) from exc
        if f.suffix.lower() not in _NATIVI:
            # m4a, video...: una copia WAV nella cartella del documento, letta per sempre senza ffmpeg
            x = audio_io.load(p, self.project.sample_rate)
            dest = self.assets_dir() / f"{f.stem}_{uuid.uuid4().hex[:6]}.wav"
            audio_io.write(dest, x, self.project.sample_rate, 24)
            p = str(dest)
            inf = audio_io.info(p)
        a = Asset(id=new_id("A"), path=self._percorso_asset(Path(p)), name=f.stem, duration=inf["duration"],
                  sample_rate=inf["sample_rate"], channels=inf["channels"])
        if detect and inf["duration"] >= 4:
            try:
                x = audio_io.load(p, 22050)
                tb = analyze.detect_tempo(x, 22050)
                kd = analyze.detect_key(x, 22050)
                if tb["confidence"] >= 0.2:
                    a.bpm = tb["bpm"]
                if kd["confidence"] >= 0.15:
                    a.key = f"{kd['key']} {kd['mode']}"
            except (audio_io.AudioError, ValueError):
                pass
        self.project.assets.append(a)
        return a

    def import_audio(self, path: str) -> dict:
        """Aggiunge un file agli asset (senza metterlo sulla timeline): BPM e tonalita' misurati."""
        with self._edit():
            a = self._importa_audio(path)
        return to_dict(a)

    def add_audio(self, path: str | None = None, asset: str | None = None, track: str | None = None,
                  bar: float = 1, bars: float | None = None, name: str | None = None, offset: float = 0.0,
                  detect: bool = True, adopt_tempo: bool = False) -> dict:
        """Un file audio (o un asset gia' importato) su una traccia audio. ``adopt_tempo`` porta
        la canzone al BPM misurato del file (utile per lavorare sopra un beat)."""
        with self._edit():
            if asset:
                try:
                    a = self.project.asset(asset)
                except KeyError as exc:
                    raise EditError(str(exc.args[0])) from None
            elif path:
                a = self._importa_audio(path, detect)
            else:
                raise EditError("pass path= (an audio file) or asset=")
            if adopt_tempo and a.bpm:
                bpm = a.bpm
                while bpm < 70:
                    bpm *= 2
                while bpm > 180:
                    bpm /= 2
                self.project.bpm = _r(bpm, 2)
                if a.key and not self.project.tracks:
                    k, _, m = a.key.partition(" ")
                    self.project.key, self.project.mode = k, m or "major"
            if track:
                t = self._track(track)
                if t.kind != "audio":
                    raise EditError(f"{t.name!r} is a {t.kind} track: audio goes on an audio track")
            else:
                r = self.add_track(kind="audio", name=name or a.name)
                t = self.project.track(r["id"])
            durata = max(0.01, a.duration - float(offset))
            length = self._bars(bars) if bars else self.project.s_to_beat(durata)
            c = Clip(id=new_id("C"), name=name or a.name, kind="audio", start=self._beat(bar), length=_r(length),
                     asset=a.id, offset=float(offset))
            t.clips.append(c)
        out = {"id": c.id, "track": t.name, "track_id": t.id, "asset": a.id, "bar": self._bar(c.start),
               "bars": _r(c.length / self.bpb, 3), "duration_s": _r(a.duration, 2)}
        if a.bpm:
            out["detected_bpm"] = a.bpm
        if a.key:
            out["detected_key"] = a.key
        return out

    def set_clip(self, clip: str, name: str | None = None, bar: float | None = None, bars: float | None = None,
                 track: str | None = None, offset: float | None = None, gain_db: float | None = None,
                 fade_in: float | None = None, fade_out: float | None = None, loop_bars: float | None = None,
                 transpose: int | None = None, muted: bool | None = None, color: str | None = None) -> dict:
        """Sposta, allunga, taglia o regola una clip. fade_in/fade_out in beat, offset in secondi (audio)."""
        with self._edit():
            t, c = self._clip(clip)
            if name is not None:
                c.name = str(name)
            if bar is not None:
                c.start = self._beat(bar)
            if bars is not None:
                c.length = _r(self._bars(bars))
            if track is not None:
                dest = self._track(track)
                if dest.kind == "bus" or (dest.kind == "midi") != (c.kind == "midi"):
                    raise EditError(f"a {c.kind} clip cannot go on the {dest.kind} track {dest.name!r}")
                t.clips.remove(c)
                dest.clips.append(c)
                t = dest
            if offset is not None:
                if c.kind != "audio":
                    raise EditError("offset is for audio clips; for MIDI move the notes (edit_notes shift)")
                c.offset = max(0.0, float(offset))
            if gain_db is not None:
                c.gain_db = _r(gain_db, 2)
            if fade_in is not None:
                c.fade_in = max(0.0, _r(fade_in))
            if fade_out is not None:
                c.fade_out = max(0.0, _r(fade_out))
            if loop_bars is not None:
                c.loop_length = self._bars(loop_bars) if loop_bars else 0.0
            if transpose is not None:
                c.transpose = int(np.clip(transpose, -48, 48))
            if muted is not None:
                c.muted = bool(muted)
            if color is not None:
                c.color = color or None
        return self.clip_view(c)

    def _split(self, t: Track, c: Clip, at: float) -> Clip:
        """Taglia ``c`` al beat ``at`` (dentro la clip): restituisce la parte destra, gia' sulla traccia."""
        rel = at - c.start
        b = copy.deepcopy(c)
        b.id = new_id("C")
        b.name = c.name or "clip"
        b.start = _r(at)
        b.length = _r(c.end - at)
        c.length = _r(rel)
        if c.kind == "midi":
            # con un loop le ripetizioni diventano note vere, se no la destra ripartirebbe dall'inizio
            note = self._note_espanse(c, rel + b.length) if c.loop_length else list(c.notes)
            c.loop_length = b.loop_length = 0.0
            c.notes = [Note(n.pitch, n.start, _r(min(n.length, rel - n.start)), n.velocity) for n in note if n.start < rel]
            b.notes = [Note(n.pitch, _r(n.start - rel), n.length, n.velocity) for n in note if n.start >= rel]
        else:
            if c.loop_length:
                L = self.project.beat_to_s(c.loop_length)
                b.offset = c.offset + (self.project.beat_to_s(rel) % L) * 2 ** (c.transpose / 12)
            else:
                b.offset = c.offset + self.project.beat_to_s(rel) * 2 ** (c.transpose / 12)
        c.fade_out = 0.0
        b.fade_in = 0.0
        t.clips.append(b)
        return b

    def split_clip(self, clip: str, at_bar: float) -> dict:
        with self._edit():
            t, c = self._clip(clip)
            at = self._beat(at_bar)
            if not c.start + 1e-6 < at < c.end - 1e-6:
                raise EditError(f"bar {at_bar:g} is not inside the clip (bars {self._bar(c.start):g}-{self._bar(c.end):g})")
            b = self._split(t, c, at)
        return {"left": self.clip_view(c), "right": self.clip_view(b)}

    def _note_espanse(self, c: Clip, length: float) -> list[Note]:
        L = c.loop_length or c.length
        out = []
        for k in range(int(math.ceil(length / L))):
            for n in c.notes:
                if n.start >= L:
                    continue
                s = k * L + n.start
                if s < length:
                    out.append(Note(n.pitch, _r(s), n.length, n.velocity))
        return out

    def duplicate_clip(self, clip: str, times: int = 1, bar: float | None = None) -> dict:
        """Copie una dopo l'altra (o a ``bar``). Per ripetere un pattern senza copie usa loop_bars."""
        with self._edit():
            t, c = self._clip(clip)
            nuovi = []
            inizio = self._beat(bar) if bar is not None else c.end
            for k in range(max(1, int(times))):
                n = copy.deepcopy(c)
                n.id = new_id("C")
                n.start = _r(inizio + k * c.length)
                t.clips.append(n)
                nuovi.append({"id": n.id, "bar": self._bar(n.start)})
        return {"copies": nuovi}

    def remove_clip(self, clip: str) -> dict:
        with self._edit():
            t, c = self._clip(clip)
            t.clips.remove(c)
        return {"removed": c.name or c.id, "track": t.name}

    def _tracce_sel(self, tracks: list[str] | None) -> list[Track]:
        return [self._track(x) for x in tracks] if tracks else list(self.project.tracks)

    def copy_bars(self, from_bar: float, bars: float, to_bar: float, tracks: list[str] | None = None,
                  sections: bool = True) -> dict:
        """Copia tutto cio' che sta in [from_bar, from_bar+bars) a ``to_bar``: per ripetere una
        strofa o un ritornello intero. Le clip a cavallo vengono tagliate sul bordo."""
        with self._edit():
            a = self._beat(from_bar)
            L = self._bars(bars)
            dest = self._beat(to_bar)
            copiate = 0
            for t in self._tracce_sel(tracks):
                for c in list(t.clips):
                    if c.end <= a or c.start >= a + L:
                        continue
                    n = copy.deepcopy(c)
                    n.id = new_id("C")
                    inizio = max(c.start, a)
                    fine = min(c.end, a + L)
                    taglio = inizio - c.start
                    if n.kind == "midi":
                        if c.loop_length:
                            note = self._note_espanse(c, c.length)
                            n.loop_length = 0.0
                        else:
                            note = list(c.notes)
                        n.notes = [Note(x.pitch, _r(x.start - taglio), _r(min(x.length, fine - c.start - x.start)), x.velocity)
                                   for x in note if taglio <= x.start < fine - c.start]
                    else:
                        n.offset = c.offset + self.project.beat_to_s(taglio) * 2 ** (c.transpose / 12)
                    n.start = _r(dest + (inizio - a))
                    n.length = _r(fine - inizio)
                    t.clips.append(n)
                    copiate += 1
            if sections:
                for s in list(self.project.sections):
                    if a <= s.start < a + L:
                        self.project.sections.append(Section(id=new_id("S"), name=s.name, start=_r(dest + s.start - a),
                                                             length=min(s.length, a + L - s.start), lyrics=s.lyrics,
                                                             color=s.color))
        return {"copied_clips": copiate, "to_bar": to_bar}

    def insert_bars(self, at_bar: float, bars: float) -> dict:
        """Apre ``bars`` battute vuote a ``at_bar``: tutto cio' che viene dopo si sposta."""
        with self._edit():
            at = self._beat(at_bar)
            L = self._bars(bars)
            for t in self.project.tracks:
                for c in list(t.clips):
                    if c.start + 1e-6 < at < c.end - 1e-6:
                        self._split(t, c, at)
                for c in t.clips:
                    if c.start >= at - 1e-6:
                        c.start = _r(c.start + L)
                for a in t.automation:
                    a.points = [[x + L if x >= at else x, v] for x, v in a.points]
            for s in self.project.sections:
                if s.start >= at - 1e-6:
                    s.start = _r(s.start + L)
                elif s.end > at:
                    s.length = _r(s.length + L)
        return {"inserted_bars": bars, "at_bar": at_bar}

    def delete_bars(self, at_bar: float, bars: float) -> dict:
        """Toglie ``bars`` battute a ``at_bar`` (con quello che contengono) e chiude il buco."""
        with self._edit():
            a = self._beat(at_bar)
            L = self._bars(bars)
            b = a + L
            for t in self.project.tracks:
                for bordo in (a, b):
                    for c in list(t.clips):
                        if c.start + 1e-6 < bordo < c.end - 1e-6:
                            self._split(t, c, bordo)
                tenute = []
                for c in t.clips:
                    if c.start >= a - 1e-6 and c.end <= b + 1e-6:
                        continue   # dentro il buco
                    if c.start >= b - 1e-6:
                        c.start = _r(c.start - L)
                    tenute.append(c)
                t.clips = tenute
                for au in t.automation:
                    au.points = [[x - L if x >= b else x, v] for x, v in au.points if not a <= x < b]
            sezioni = []
            for s in self.project.sections:
                if a - 1e-6 <= s.start and s.end <= b + 1e-6:
                    continue
                if s.start >= b - 1e-6:
                    s.start = _r(s.start - L)
                else:
                    taglio = max(0.0, min(s.end, b) - max(s.start, a))
                    s.length = _r(max(self.bpb, s.length - taglio))
                sezioni.append(s)
            self.project.sections = sezioni
        return {"deleted_bars": bars, "at_bar": at_bar}

    # ---- note ----------------------------------------------------------
    def _midi_clip(self, clip: str) -> tuple[Track, Clip]:
        t, c = self._clip(clip)
        if c.kind != "midi":
            raise EditError(f"{c.name or c.id} is an audio clip: it has no notes")
        return t, c

    def add_notes(self, clip: str, notes: list | None = None, melody: str | None = None, at: float = 0.0,
                  extend: bool = True) -> dict:
        """Aggiunge note (``at`` = beat di partenza nella clip per la melodia). ``extend`` allunga la
        clip se le note escono dalla fine."""
        with self._edit():
            t, c = self._midi_clip(clip)
            nuove = [self._norm_note(n) for n in (notes or [])]
            if melody:
                try:
                    nuove += [self._norm_note(dict(n, start=n["start"] + at)) for n in theory.parse_melody(melody)]
                except theory.TheoryError as exc:
                    raise EditError(str(exc)) from exc
            if not nuove:
                raise EditError("pass notes=[...] or melody='C5:1 D5:0.5 ...'")
            c.notes.extend(nuove)
            fine = max(n.start + n.length for n in c.notes)
            if extend and fine > c.length and not c.loop_length:
                c.length = math.ceil(fine / self.bpb - 1e-9) * self.bpb
        return {"clip": c.id, "added": len(nuove), "notes": len(c.notes), "bars": _r(c.length / self.bpb, 3)}

    def set_notes(self, clip: str, notes: list, extend: bool = True) -> dict:
        """Sostituisce tutte le note della clip (``extend`` allunga la clip se escono dalla fine)."""
        with self._edit():
            t, c = self._midi_clip(clip)
            c.notes = [self._norm_note(n) for n in notes]
            fine = max((n.start + n.length for n in c.notes), default=0.0)
            if extend and fine > c.length + 1e-9 and not c.loop_length:
                c.length = math.ceil(fine / self.bpb - 1e-9) * self.bpb
        return {"clip": c.id, "notes": len(c.notes), "bars": _r(c.length / self.bpb, 3)}

    def _filtro_note(self, c: Clip, pitch: Any = None, start: float | None = None, end: float | None = None,
                     indices: list[int] | None = None) -> list[int]:
        ordinate = sorted(range(len(c.notes)), key=lambda i: (c.notes[i].start, c.notes[i].pitch))
        sel = []
        p = None
        if pitch is not None:
            p = [theory.parse_pitch(x) for x in (pitch if isinstance(pitch, list) else [pitch])]
        for pos, i in enumerate(ordinate):
            n = c.notes[i]
            if indices is not None and pos not in indices:
                continue
            if p is not None and n.pitch not in p:
                continue
            if start is not None and n.start < start - 1e-9:
                continue
            if end is not None and n.start >= end - 1e-9:
                continue
            sel.append(i)
        return sel

    def remove_notes(self, clip: str, pitch: Any = None, start: float | None = None, end: float | None = None,
                     indices: list[int] | None = None, all: bool = False) -> dict:
        """Toglie note: per altezza, per intervallo di beat [start, end), per posizione nell'elenco
        di get_notes (``indices``), o tutte (``all=true``)."""
        with self._edit():
            t, c = self._midi_clip(clip)
            if all:
                tolte = len(c.notes)
                c.notes = []
            else:
                if pitch is None and start is None and end is None and indices is None:
                    raise EditError("say which notes: pitch, start/end, indices, or all=true")
                sel = set(self._filtro_note(c, pitch, start, end, indices))
                tolte = len(sel)
                c.notes = [n for i, n in enumerate(c.notes) if i not in sel]
        return {"clip": c.id, "removed": tolte, "notes": len(c.notes)}

    def edit_notes(self, clip: str, transpose: int = 0, shift: float = 0.0, velocity: int | None = None,
                   velocity_scale: float = 1.0, length_scale: float = 1.0, length: float | None = None,
                   pitch: Any = None, start: float | None = None, end: float | None = None,
                   indices: list[int] | None = None, legato: bool = False) -> dict:
        """Modifica le note scelte (tutte se non filtri): trasporta, sposta (beat), velocity,
        durate; ``legato`` allunga ogni nota fino alla successiva."""
        with self._edit():
            t, c = self._midi_clip(clip)
            sel = self._filtro_note(c, pitch, start, end, indices)
            for i in sel:
                n = c.notes[i]
                n.pitch = int(np.clip(n.pitch + int(transpose), 0, 127))
                n.start = _r(max(0.0, n.start + float(shift)))
                if velocity is not None:
                    n.velocity = int(np.clip(velocity, 1, 127))
                n.velocity = int(np.clip(round(n.velocity * velocity_scale), 1, 127))
                if length is not None:
                    n.length = _r(max(0.01, length))
                n.length = _r(max(0.01, n.length * length_scale))
            if legato:
                ordinate = sorted((c.notes[i] for i in sel), key=lambda n: n.start)
                for a, b in zip(ordinate, ordinate[1:]):
                    if b.start > a.start:
                        a.length = _r(b.start - a.start)
        return {"clip": c.id, "edited": len(sel)}

    def transpose(self, target: str, semitones: int) -> dict:
        """Trasporta una clip o tutte le clip di una traccia (note MIDI; l'audio cambia altezza
        e velocita' come un giradischi)."""
        with self._edit():
            try:
                clips = [self.project.clip(target)[1]]
            except KeyError:
                clips = list(self._track(target).clips)
            for c in clips:
                if c.kind == "midi":
                    for n in c.notes:
                        n.pitch = int(np.clip(n.pitch + int(semitones), 0, 127))
                else:
                    c.transpose = int(np.clip(c.transpose + int(semitones), -48, 48))
        return {"transposed": len(clips), "semitones": semitones}

    def quantize(self, clip: str, grid: float = 0.25, strength: float = 1.0, swing: float = 0.0,
                 lengths: bool = False) -> dict:
        """Porta le note sulla griglia (in beat: 0.25 = sedicesimi, 0.5 = ottavi, 1/3 = terzine)."""
        if grid <= 0:
            raise EditError("grid must be > 0 beats")
        with self._edit():
            t, c = self._midi_clip(clip)
            q = theory.quantize([to_dict(n) for n in c.notes], grid, strength, swing, lengths)
            c.notes = [Note(**n) for n in q]
        return {"clip": c.id, "notes": len(c.notes), "grid": grid}

    def humanize(self, clip: str, timing: float = 0.015, velocity: float = 8, seed: int = 0) -> dict:
        """Piccole imprecisioni di tempo (beat) e velocity: suona meno da macchina."""
        with self._edit():
            t, c = self._midi_clip(clip)
            c.notes = [Note(**n) for n in theory.humanize([to_dict(n) for n in c.notes], timing, velocity, seed)]
        return {"clip": c.id, "notes": len(c.notes)}

    def fit_to_scale(self, target: str, key: str | None = None, mode: str | None = None) -> dict:
        """Porta sulla scala (della canzone, o key/mode) le note che ne escono."""
        with self._edit():
            try:
                pcs = theory.scale_pcs(key or self.project.key, mode or (self.project.mode if not key else "major"))
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            try:
                clips = [self.project.clip(target)[1]]
            except KeyError:
                clips = [c for c in self._track(target).clips if c.kind == "midi"]
            mosse = 0
            for c in clips:
                for n in c.notes:
                    p = theory.snap_to_scale(n.pitch + c.transpose, pcs) - c.transpose
                    if p != n.pitch:
                        n.pitch = int(np.clip(p, 0, 127))
                        mosse += 1
        return {"moved_notes": mosse}

    # ---- composizione ---------------------------------------------------
    def _traccia_per(self, track: str | None, ruolo: str, sound: str | None = None) -> Track:
        if track:
            try:
                t = self.project.track(track)
            except KeyError:
                t = None
            if t is not None:
                if t.kind != "midi":
                    raise EditError(f"{t.name!r} is an {t.kind} track: notes need a MIDI track")
                if sound:
                    t.instrument = self._instrument(sound, None, None)
                return t
        nome, suono, role = _AUTO_TRACCE[ruolo]
        r = self.add_track(kind="midi", name=track or nome, sound=sound or suono, role=role)
        return self.project.track(r["id"])

    def _progressione(self, progression: str, bars: float | None, beats_per_chord: float | None):
        try:
            prog = theory.parse_progression(progression, self.project.key, self.project.mode, self.bpb, beats_per_chord)
        except theory.TheoryError as exc:
            raise EditError(str(exc)) from exc
        if bars:
            totale = self._bars(bars)
            giro = sum(d for _, d in prog)
            out, t = [], 0.0
            while t < totale - 1e-9:
                for sym, d in prog:
                    if t >= totale - 1e-9:
                        break
                    dd = min(d, totale - t)
                    out.append((sym, dd))
                    t += dd
                if giro <= 0:
                    break
            prog = out
        return prog

    def _clip_da_note(self, t: Track, note: list[dict], bar: float, name: str, length: float | None = None) -> Clip:
        fine = max((n["start"] + n["length"] for n in note), default=self.bpb)
        L = length if length is not None else max(self.bpb, math.ceil(fine / self.bpb - 1e-6) * self.bpb)
        c = Clip(id=new_id("C"), name=name, kind="midi", start=self._beat(bar), length=_r(L),
                 notes=[self._norm_note(n) for n in note])
        t.clips.append(c)
        return c

    def add_chords(self, progression: str, track: str | None = None, bar: float = 1, style: str = "block",
                   octave: int = 4, bars: float | None = None, beats_per_chord: float | None = None,
                   velocity: int = 90, spread: bool = False, sound: str | None = None, name: str | None = None) -> dict:
        """Accordi da una progressione: "Am F C G", "vi IV I V", "| Am | F | C G |", "Am:2 F:2".
        ``bars`` ripete il giro fino a riempirle. Voicing con condotta delle voci."""
        with self._edit():
            prog = self._progressione(progression, bars, beats_per_chord)
            t = self._traccia_per(track, "chords", sound)
            try:
                note = theory.chords_notes(prog, style, center=(octave + 1) * 12, velocity=velocity, spread=spread)
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            c = self._clip_da_note(t, note, bar, name or "Chords", sum(d for _, d in prog))
        return {"clip": c.id, "track": t.name, "track_id": t.id, "chords": [s for s, _ in prog][:32],
                "bar": self._bar(c.start), "bars": _r(c.length / self.bpb, 3), "notes": len(c.notes)}

    def add_bassline(self, progression: str, track: str | None = None, bar: float = 1, style: str = "root",
                     octave: int = 2, bars: float | None = None, beats_per_chord: float | None = None,
                     velocity: int = 100, sound: str | None = None, name: str | None = None) -> dict:
        with self._edit():
            prog = self._progressione(progression, bars, beats_per_chord)
            t = self._traccia_per(track, "bass", sound)
            try:
                note = theory.bass_notes(prog, style, octave, velocity)
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            c = self._clip_da_note(t, note, bar, name or "Bass", sum(d for _, d in prog))
        return {"clip": c.id, "track": t.name, "track_id": t.id, "bar": self._bar(c.start),
                "bars": _r(c.length / self.bpb, 3), "notes": len(c.notes)}

    def add_arpeggio(self, progression: str, track: str | None = None, bar: float = 1, pattern: str = "up",
                     rate: float = 0.25, octaves: int = 1, octave: int = 4, bars: float | None = None,
                     beats_per_chord: float | None = None, velocity: int = 85, gate: float = 0.8,
                     sound: str | None = None, name: str | None = None, seed: int = 0) -> dict:
        with self._edit():
            prog = self._progressione(progression, bars, beats_per_chord)
            t = self._traccia_per(track, "arp", sound)
            try:
                note = theory.arp_notes(prog, pattern, rate, octaves, (octave + 1) * 12 + 4, velocity, gate, seed)
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            c = self._clip_da_note(t, note, bar, name or "Arp", sum(d for _, d in prog))
        return {"clip": c.id, "track": t.name, "track_id": t.id, "bar": self._bar(c.start),
                "bars": _r(c.length / self.bpb, 3), "notes": len(c.notes)}

    def add_melody(self, melody: str, track: str | None = None, bar: float = 1, sound: str | None = None,
                   name: str | None = None, bars: float | None = None) -> dict:
        """Una melodia in notazione: "C5:1 D5:0.5 E5:0.5 r:1 G5:2" (nota:beat, r = pausa,
        [C4 E4 G4]:2 = accordo, ! accento, ~ legatura)."""
        with self._edit():
            try:
                note = theory.parse_melody(melody)
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            t = self._traccia_per(track, "melody", sound)
            c = self._clip_da_note(t, note, bar, name or "Melody", self._bars(bars) if bars else None)
        return {"clip": c.id, "track": t.name, "track_id": t.id, "bar": self._bar(c.start),
                "bars": _r(c.length / self.bpb, 3), "notes": len(c.notes)}

    def add_drums(self, genre: str = "pop", track: str | None = None, bar: float = 1, bars: float = 4,
                  intensity: str = "normal", fill_every: int = 0, swing: float | None = None,
                  humanize: float = 0.2, crash: bool | None = None, seed: int = 0, velocity: int = 105,
                  sound: str | None = None, name: str | None = None, loop: bool = False) -> dict:
        """Un pattern di batteria per genere. ``loop=true`` scrive una battuta (o due) ripetuta
        con loop_bars: piu' leggero da modificare a mano."""
        with self._edit():
            if track is None and sound is None:
                sound = _KIT_PER_GENERE.get(genre, "acoustic kit")
            t = self._traccia_per(track, "drums", sound)
            if t.instrument is None or t.instrument.type != "drums":
                t.instrument = self._instrument(sound or _KIT_PER_GENERE.get(genre, "acoustic kit"), None, None)
            nb = (2 if fill_every else 1) if loop else bars
            try:
                note, sw = theory.drum_notes(genre, int(math.ceil(nb)), self.bpb, intensity, fill_every if not loop else 0,
                                             swing, humanize, seed, crash, velocity)
            except theory.TheoryError as exc:
                raise EditError(str(exc)) from exc
            c = self._clip_da_note(t, note, bar, name or f"{genre.title()} beat", self._bars(bars))
            if loop:
                c.loop_length = _r(nb * self.bpb)
                c.notes = [n for n in c.notes if n.start < c.loop_length]
        return {"clip": c.id, "track": t.name, "track_id": t.id, "bar": self._bar(c.start),
                "bars": _r(c.length / self.bpb, 3), "notes": len(c.notes), "swing": sw,
                "pattern": theory.DRUM_PATTERNS[genre]["desc"]}

    # ---- sezioni e testi -----------------------------------------------
    def add_section(self, name: str, bar: float, bars: float, lyrics: str = "", color: str | None = None) -> dict:
        with self._edit():
            s = Section(id=new_id("S"), name=str(name), start=self._beat(bar), length=_r(self._bars(bars)),
                        lyrics=lyrics or "", color=color or SECTION_COLORS.get(str(name).lower().split()[0], None))
            self.project.sections.append(s)
            self.project.sections.sort(key=lambda x: x.start)
        return {"id": s.id, "name": s.name, "bar": self._bar(s.start), "bars": bars}

    def set_section(self, section: str, name: str | None = None, bar: float | None = None, bars: float | None = None,
                    lyrics: str | None = None, color: str | None = None) -> dict:
        with self._edit():
            s = self._section(section)
            if name is not None:
                s.name = str(name)
            if bar is not None:
                s.start = self._beat(bar)
            if bars is not None:
                s.length = _r(self._bars(bars))
            if lyrics is not None:
                s.lyrics = lyrics
            if color is not None:
                s.color = color
            self.project.sections.sort(key=lambda x: x.start)
        return {"id": s.id, "name": s.name, "bar": self._bar(s.start), "bars": _r(s.length / self.bpb, 3),
                "lyrics_lines": len([r for r in s.lyrics.splitlines() if r.strip()])}

    def remove_section(self, section: str) -> dict:
        with self._edit():
            s = self._section(section)
            self.project.sections.remove(s)
        return {"removed": s.name}

    def structure(self, sections: list[dict], start_bar: float = 1, replace: bool = True) -> dict:
        """Imposta tutta la struttura in un colpo: [{"name": "intro", "bars": 4}, {"name": "verse",
        "bars": 8, "lyrics": "..."}, ...], una dopo l'altra da ``start_bar``."""
        with self._edit():
            if replace:
                self.project.sections = []
            bar = float(start_bar)
            fatte = []
            for d in sections:
                if "name" not in d or "bars" not in d:
                    raise EditError("each section needs name and bars")
                r = self.add_section(d["name"], bar, d["bars"], d.get("lyrics", ""), d.get("color"))
                fatte.append({"name": r["name"], "bar": r["bar"], "bars": d["bars"]})
                bar += float(d["bars"])
        return {"sections": fatte, "total_bars": bar - start_bar}

    # ---- effetti -------------------------------------------------------
    def _catena(self, target: str) -> tuple[list[Effect], str, Track | None]:
        if str(target).lower() == "master":
            return self.project.master.effects, "master", None
        t = self._track(target)
        return t.effects, t.name, t

    def add_effect(self, target: str, type: str, params: dict | None = None, index: int | None = None) -> dict:
        """Effetto su una traccia (o ``target="master"``), in fondo alla catena o a ``index``."""
        with self._edit():
            lista, nome, _ = self._catena(target)
            try:
                par = fx.validate(type, params, partial=True)
            except ValueError as exc:
                raise EditError(str(exc)) from exc
            e = Effect(type=type, params=par)
            if index is None:
                lista.append(e)
                i = len(lista) - 1
            else:
                i = int(np.clip(index, 0, len(lista)))
                lista.insert(i, e)
        return {"target": nome, "index": i, "effect": type, "chain": [x.type for x in lista]}

    def update_effect(self, target: str, index: int, params: dict | None = None, enabled: bool | None = None) -> dict:
        with self._edit():
            lista, nome, _ = self._catena(target)
            e = self._fx_at(lista, index, nome)
            if params:
                try:
                    e.params.update(fx.validate(e.type, params, partial=True))
                except ValueError as exc:
                    raise EditError(str(exc)) from exc
            if enabled is not None:
                e.enabled = bool(enabled)
        return {"target": nome, "index": index, "effect": e.type, "params": e.params, "enabled": e.enabled}

    @staticmethod
    def _fx_at(lista: list, index: int, nome: str) -> Effect:
        if not -len(lista) <= int(index) < len(lista):
            raise EditError(f"{nome} has {len(lista)} effects: index {index} does not exist")
        return lista[int(index)]

    def remove_effect(self, target: str, index: int) -> dict:
        with self._edit():
            lista, nome, t = self._catena(target)
            e = self._fx_at(lista, index, nome)
            i = lista.index(e)
            lista.remove(e)
            if t is not None:
                # l'automazione degli effetti segue gli indici
                nuove = []
                for a in t.automation:
                    parti = a.target.split(".")
                    if len(parti) == 3 and parti[0] == "fx":
                        k = int(parti[1])
                        if k == i:
                            continue
                        if k > i:
                            a.target = f"fx.{k - 1}.{parti[2]}"
                    nuove.append(a)
                t.automation = nuove
        return {"target": nome, "removed": e.type, "chain": [x.type for x in lista]}

    def move_effect(self, target: str, index: int, to: int) -> dict:
        with self._edit():
            lista, nome, _ = self._catena(target)
            e = self._fx_at(lista, index, nome)
            lista.remove(e)
            lista.insert(int(np.clip(to, 0, len(lista))), e)
        return {"target": nome, "chain": [x.type for x in lista]}

    def apply_chain(self, target: str, name: str, replace: bool = False) -> dict:
        """Una catena pronta (vocal, bass, drum bus, master streaming...) su una traccia o sul master."""
        try:
            ch = presets.chain(name)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        with self._edit():
            lista, nome, _ = self._catena(target)
            if replace:
                lista.clear()
            for e in ch["effects"]:
                lista.append(Effect(type=e["type"], params=fx.validate(e["type"], e.get("params"), partial=True)))
        return {"target": nome, "chain": [x.type for x in lista]}

    def save_chain(self, name: str, target: str, desc: str = "") -> dict:
        lista, _, _ = self._catena(target)
        try:
            return presets.save_chain(name, [{"type": e.type, "params": e.params} for e in lista if e.enabled], desc)
        except ValueError as exc:
            raise EditError(str(exc)) from exc

    def set_master(self, volume_db: float | None = None) -> dict:
        with self._edit():
            if volume_db is not None:
                self.project.master.volume_db = _r(volume_db, 2)
        return {"volume_db": self.project.master.volume_db, "effects": [e.type for e in self.project.master.effects]}

    # ---- automazione ---------------------------------------------------
    def set_automation(self, track: str, target: str, points: list) -> dict:
        """Curva nel tempo: ``points`` = [[bar, valore], ...] (lineare fra i punti).
        target: volume (dB), pan (-1..1), o fx.<indice>.<param> (es. fx.0.cutoff, fx.1.mix)."""
        with self._edit():
            t = self._track(track)
            if target not in ("volume", "pan"):
                parti = target.split(".")
                if len(parti) != 3 or parti[0] != "fx" or not parti[1].isdigit():
                    raise EditError("target is volume, pan or fx.<index>.<param> (e.g. fx.0.cutoff)")
                i = int(parti[1])
                if i >= len(t.effects):
                    raise EditError(f"{t.name!r} has no effect at index {i}")
                tipo = t.effects[i].type
                if parti[2] not in fx.AUTOMATABLE[tipo]:
                    raise EditError(f"{tipo}.{parti[2]} cannot be automated; automatable: "
                                    f"{', '.join(fx.AUTOMATABLE[tipo]) or 'nothing'}")
            try:
                pts = sorted([[self._beat(float(b)), float(v)] for b, v in points])
            except (TypeError, ValueError):
                raise EditError("points is [[bar, value], ...]") from None
            if not pts:
                raise EditError("points is [[bar, value], ...] with at least one point")
            t.automation = [a for a in t.automation if a.target != target]
            t.automation.append(Automation(target=target, points=pts))
        return {"track": t.name, "target": target, "points": len(pts)}

    def clear_automation(self, track: str, target: str | None = None) -> dict:
        with self._edit():
            t = self._track(track)
            prima = len(t.automation)
            t.automation = [a for a in t.automation if target is not None and a.target != target]
        return {"track": t.name, "removed": prima - len(t.automation)}

    # ---- analisi e mastering ---------------------------------------------
    def render(self, start_bar: float | None = None, end_bar: float | None = None, master: bool = True) -> np.ndarray:
        a = self._beat(start_bar) if start_bar else None
        b = self._beat(end_bar + 1) if end_bar else None
        return render.render(self.project, self.base_dir, start_beat=a, end_beat=b, master=master)

    def analyze(self, track: str | None = None, start_bar: float | None = None, end_bar: float | None = None) -> dict:
        """Numeri del mix (o di una traccia sola, post-fader): LUFS, picchi, bande, stereo."""
        sr = self.project.sample_rate
        if track:
            t = self._track(track)
            stems, n = render.render_stems(self.project, self.base_dir)
            x = stems.get(t.id)
            if x is None:
                x = render.render_track(self.project, t, sr, render.length_samples(self.project), self.base_dir)
            if start_bar or end_bar:
                a = render.beat_sample(self.project, self._beat(start_bar or 1), sr)
                b = render.beat_sample(self.project, self._beat(end_bar + 1), sr) if end_bar else x.shape[-1]
                x = x[:, a:b]
            return {"track": t.name, **analyze.stats(x, sr)}
        return analyze.stats(self.render(start_bar, end_bar), sr)

    def review(self, target_lufs: float = -14.0) -> list[dict]:
        return analyze.review(self.project, self.base_dir, target_lufs=target_lufs)

    def auto_master(self, target_lufs: float = -14.0, style: str = "streaming", ceiling_db: float = -1.0) -> dict:
        """Master fino alla loudness voluta: catena pronta (se manca un limiter) + guadagno del
        limiter cercato misurando. style: streaming (gentle) o loud."""
        if not -30 <= target_lufs <= -5:
            raise EditError("target_lufs must be between -30 and -5")
        p = self.project
        sr = p.sample_rate
        with self._edit():
            if not any(e.type == "limiter" for e in p.master.effects):
                self.apply_chain("master", "master loud" if style == "loud" else "master streaming")
            lim = next(e for e in reversed(p.master.effects) if e.type == "limiter")
            lim.params["ceiling_db"] = float(ceiling_db)
            stems, n = render.render_stems(p, self.base_dir, sr)
            somma = np.zeros((2, n))
            for y in stems.values():
                somma += y
            if not np.any(somma):
                raise EditError("the song is silent: nothing to master")

            def misura(g: float) -> float:
                lim.params["gain_db"] = float(g)
                y = render.apply_chain(p, somma, p.master.effects, [], sr, render.hash_seed("master"))
                y = y * 10 ** (p.master.volume_db / 20)
                return analyze.loudness(y, sr)["lufs"]

            g = float(lim.params.get("gain_db", 0.0))
            l0 = misura(g)
            for _ in range(6):
                err = target_lufs - l0
                if abs(err) < 0.3:
                    break
                g = float(np.clip(g + err * (1.0 if err < 0 else 1.15), -12, 24))
                l0 = misura(g)
            lim.params["gain_db"] = _r(g, 2)
        y = render.render(p, self.base_dir)
        st = analyze.stats(y, sr)
        return {"lufs": st["lufs"], "true_peak_db": st["true_peak_db"], "limiter_gain_db": _r(g, 2),
                "chain": [e.type for e in p.master.effects], "target_lufs": target_lufs}

    def balance_mix(self, target_lufs: float = -20.0) -> dict:
        """Gain staging: porta ogni traccia a una loudness tipica per il suo ruolo (prima del
        mix fine a orecchio). Le tracce bus restano come sono."""
        rel = {"drums": 0.0, "bass": -2.0, "vocal": 1.0, "lead": -2.0, "chords": -5.0, "pad": -8.0,
               "arp": -6.0, "fx": -10.0}
        p = self.project
        sr = p.sample_rate
        cambi = {}
        with self._edit():
            n = render.length_samples(p, sr)
            for t in p.tracks:
                if t.kind == "bus" or not t.clips:
                    continue
                y = render.render_track(p, t, sr, n, self.base_dir)
                lu = analyze.loudness(y, sr)["lufs"]
                if lu <= -69:
                    continue
                ruolo = t.role or ("drums" if t.instrument and t.instrument.type == "drums" else "")
                obiettivo = target_lufs + rel.get(ruolo, -4.0)
                nuovo = float(np.clip(t.volume_db + (obiettivo - lu), -40, 12))
                cambi[t.name] = {"from": t.volume_db, "to": _r(nuovo, 1), "role": ruolo or "?"}
                t.volume_db = _r(nuovo, 1)
        return {"changed": cambi}

    # ---- import/export -------------------------------------------------
    def export_audio(self, path: str, start_bar: float | None = None, end_bar: float | None = None,
                     bit_depth: int = 24, quality: float = 0.9, sample_rate: int | None = None) -> dict:
        """Scrive la canzone (.wav .flac .mp3 .ogg .aiff .m4a)."""
        x = self.render(start_bar, end_bar)
        sr = self.project.sample_rate
        if sample_rate and sample_rate != sr:
            x = audio_io.resample(x, sr, int(sample_rate))
            sr = int(sample_rate)
        try:
            out = audio_io.write(path, x, sr, bit_depth, quality)
        except audio_io.AudioError as exc:
            raise EditError(str(exc)) from exc
        st = analyze.stats(x, sr, detail=False)
        return {**out, "duration_s": st["duration_s"], "lufs": st["lufs"], "peak_db": st["peak_db"]}

    def export_stems(self, folder: str, format: str = "wav", bit_depth: int = 24) -> dict:
        """Una traccia per file (post-fader, senza master), tutte lunghe uguali: per mixare altrove."""
        d = Path(folder)
        d.mkdir(parents=True, exist_ok=True)
        stems, n = render.render_stems(self.project, self.base_dir)
        scritti = []
        for tid, y in stems.items():
            t = self.project.track(tid)
            nome = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in t.name).strip() or tid
            f = d / f"{len(scritti) + 1:02d} {nome}.{format.lstrip('.')}"
            try:
                audio_io.write(f, y, self.project.sample_rate, bit_depth)
            except audio_io.AudioError as exc:
                raise EditError(str(exc)) from exc
            scritti.append(str(f))
        return {"folder": str(d.resolve()), "stems": scritti}

    def export_midi(self, path: str, tracks: list[str] | None = None) -> dict:
        return midi_io.export(self.project, path, tracks)

    def import_midi(self, path: str, bar: float = 1, adopt_tempo: bool = False) -> dict:
        """Un file .mid: una traccia per strumento (canale 10 = batteria), suoni interni scelti dal
        programma General MIDI."""
        try:
            m = midi_io.read(path)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        with self._edit():
            if adopt_tempo:
                self.project.bpm = float(m["bpm"])
                self.project.time_sig = list(m["time_sig"])
            start = self._beat(bar)
            create = []
            for tr in m["tracks"]:
                if not tr["notes"]:
                    continue
                suono = "acoustic kit" if tr["drums"] else presets.gm_sound(tr["program"])
                r = self.add_track(kind="midi", name=tr["name"][:40] or "MIDI", sound=suono)
                t = self.project.track(r["id"])
                fine = max(s + d for s, d, _, _ in tr["notes"])
                L = max(self.bpb, math.ceil(fine / self.bpb - 1e-9) * self.bpb)
                c = Clip(id=new_id("C"), name=Path(path).stem, kind="midi", start=start, length=_r(L),
                         notes=[Note(int(p), _r(s), _r(d), int(v)) for s, d, p, v in tr["notes"]])
                t.clips.append(c)
                create.append({"track": t.name, "sound": suono, "notes": len(c.notes)})
        return {"tracks": create, "bpm": m["bpm"]}

    def remove_asset(self, asset: str) -> dict:
        with self._edit():
            try:
                a = self.project.asset(asset)
            except KeyError as exc:
                raise EditError(str(exc.args[0])) from None
            if any(c.asset == a.id for t in self.project.tracks for c in t.clips):
                raise EditError(f"{a.name} is used by a clip: remove the clip first")
            self.project.assets.remove(a)
        return {"removed": a.name}

    # ---- IA: generazione, stem, voce, trascrizione ---------------------------
    # Il lavoro lungo (ComfyUI, rete, Demucs, Applio) avviene FUORI da _edit; il
    # risultato entra con una sola modifica: un undo, niente lucchetti tenuti per minuti.
    # Niente e' distruttivo: tracce nuove, l'originale al massimo silenziato.

    def _asset_da(self, src: bytes | Path, name: str, ext: str, source: str) -> Asset:
        d = self.assets_dir() / "generated"
        d.mkdir(parents=True, exist_ok=True)
        base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:40] or "audio"
        dest = d / f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        if isinstance(src, (bytes, bytearray)):
            dest.write_bytes(src)
        else:
            shutil.copyfile(src, dest)
        if ext.lower() not in _NATIVI:
            x = audio_io.load(dest, self.project.sample_rate)
            wav = dest.with_suffix(".wav")
            audio_io.write(wav, x, self.project.sample_rate, 24)
            dest.unlink(missing_ok=True)
            dest = wav
        try:
            inf = audio_io.info(dest)
        except audio_io.AudioError as exc:
            raise EditError(f"the generated file is not readable audio: {exc}") from exc
        a = Asset(id=new_id("A"), path=self._percorso_asset(dest), name=name, duration=inf["duration"],
                  sample_rate=inf["sample_rate"], channels=inf["channels"], generated=True, source=source)
        self.project.assets.append(a)
        return a

    def _testo_canzone(self) -> str:
        """Il testo delle sezioni nel formato a etichette di ACE-Step: [Verse] / [Chorus]..."""
        blocchi = []
        for s in sorted(self.project.sections, key=lambda s: s.start):
            if s.lyrics.strip():
                blocchi.append(f"[{s.name.strip().title()}]\n{s.lyrics.strip()}")
        return "\n\n".join(blocchi)

    def _audio_clip(self, clip: str) -> tuple[Track, Clip, np.ndarray]:
        t, c = self._clip(clip)
        if c.kind != "audio":
            raise EditError(f"{c.name or c.id} is a MIDI clip: this needs an audio clip")
        sr = self.project.sample_rate
        n = render.beat_sample(self.project, c.end, sr) + sr
        # anche una clip silenziata (l'originale dopo separate_stems): qui serve il suo audio
        sorgente = copy.copy(c)
        sorgente.muted = False
        r = render._audio_clip(self.project, sorgente, sr, n, render._loader(self.project, self.base_dir, sr))
        if r is None:
            raise EditError(f"the audio of {c.name or c.id} cannot be read (file missing?)")
        return t, c, r[1]

    def generate_song(self, prompt: str, lyrics: str | None = None, seconds: float | None = None, bar: float = 1,
                      instrumental: bool = False, backend: str = "auto", seed: int = -1, language: str = "en",
                      name: str | None = None, track: str | None = None) -> dict:
        """Una canzone intera (anche cantata) da uno stile e un testo: ACE-Step 1.5 in ComfyUI o
        ElevenLabs. Senza ``lyrics`` usa i testi delle sezioni; durata = la struttura, se c'e'."""
        p = self.project
        if not prompt or not prompt.strip():
            raise EditError("describe the song: genre, mood, instruments, voice")
        try:
            motore = ai.scegli(backend, "song")
        except ai.AIError as exc:
            raise EditError(str(exc)) from exc
        testo = "[Instrumental]" if instrumental else (lyrics if lyrics is not None else self._testo_canzone())
        if seconds is None:
            seconds = p.beat_to_s(max(s.end for s in p.sections)) if p.sections else 60.0
        seconds = float(np.clip(seconds, 5, 600))
        chiave = f"{p.key} {p.mode if p.mode in ('major', 'minor') else 'major'}"
        try:
            if motore == "comfyui":
                data, ext = comfy.generate_song(prompt.strip(), testo or "[Instrumental]", seconds, p.bpm, chiave,
                                                p.time_sig[0], language, seed), ".flac"
            else:
                descr = f"{prompt.strip()}. {p.bpm:g} BPM, key of {chiave}."
                if instrumental:
                    descr += " Instrumental, no vocals."
                elif testo:
                    descr += f" Sung lyrics:\n{testo}"
                data, ext = cloud.genera(motore, descr, seconds)
        except (comfy.ComfyError, cloud.CloudError) as exc:
            raise EditError(str(exc)) from exc
        with self._edit():
            a = self._asset_da(data, name or "AI song", ext, f"{motore}: {prompt.strip()[:200]}")
            r = self.add_audio(asset=a.id, track=track, bar=bar, name=name or "AI song")
        return {**r, "backend": motore, "seconds": round(a.duration, 2), "lyrics_used": bool(testo and not instrumental)}

    def generate_audio(self, prompt: str, bars: float | None = None, seconds: float | None = None, bar: float = 1,
                       track: str | None = None, backend: str = "auto", seed: int = -1, name: str | None = None) -> dict:
        """Un suono da una descrizione: loop di batteria, strumento, atmosfera, effetto. Con ``bars``
        la durata e' quella delle battute al tempo della canzone (il tempo entra nel prompt)."""
        p = self.project
        if not prompt or not prompt.strip():
            raise EditError("describe the sound")
        try:
            motore = ai.scegli(backend, "sound")
        except ai.AIError as exc:
            raise EditError(str(exc)) from exc
        if bars:
            seconds = p.beat_to_s(self._bars(bars))
        seconds = float(np.clip(seconds or 8.0, 1, 600 if motore != "comfyui" else 47))
        descr = f"{prompt.strip()}, {p.bpm:g} BPM" if bars else prompt.strip()
        try:
            if motore == "comfyui":
                data, ext = comfy.generate_audio(descr, seconds, s=seed), ".flac"
            else:
                data, ext = cloud.genera(motore, descr, seconds)
        except (comfy.ComfyError, cloud.CloudError) as exc:
            raise EditError(str(exc)) from exc
        with self._edit():
            a = self._asset_da(data, name or prompt.strip()[:30], ext, f"{motore}: {prompt.strip()[:200]}")
            r = self.add_audio(asset=a.id, track=track, bar=bar, bars=bars, name=name or prompt.strip()[:30])
        return {**r, "backend": motore, "seconds": round(a.duration, 2)}

    # nomi e ruoli delle tracce per gli stem di Demucs e di UVR
    _STEM_NOMI = {"vocals": ("Vocals", "vocal"), "drums": ("Drums", "drums"), "bass": ("Bass", "bass"),
                  "other": ("Other", ""), "no_vocals": ("Instrumental", ""), "instrumental": ("Instrumental", ""),
                  "piano": ("Piano", "chords"), "guitar": ("Guitar", "chords"), "no noise": ("Clean", "vocal"),
                  "noise": ("Noise", "fx"), "no reverb": ("Dry", ""), "reverb": ("Reverb", "fx"),
                  "no echo": ("Dry", ""), "echo": ("Echo", "fx"), "backing vocals": ("Backing vocals", "vocal"),
                  "lead vocals": ("Lead vocal", "vocal")}

    def stem_engines(self) -> dict:
        """Motori di separazione disponibili e i modelli UVR sul disco."""
        return {"uvr": {**uvr.stato(), "models": uvr.modelli()}, "demucs": separa.stato()}

    def _motore_stem(self, engine: str) -> str:
        if engine not in ("auto", "uvr", "demucs"):
            raise EditError("engine must be auto, uvr or demucs")
        if engine == "auto":
            if uvr.python():
                return "uvr"
            if separa.python():
                return "demucs"
            raise EditError("no stem separator: " + uvr.stato()["hint"] + "; or " + separa.stato()["hint"])
        return engine

    def separate_stems(self, clip: str, two_stems: bool = False, model: str | None = None,
                       engine: str = "auto") -> dict:
        """Divide una clip audio negli stem del modello: con UVR (i modelli di Ultimate Vocal Remover:
        voce/base, rumore, riverbero...) o con Demucs (voce, batteria, basso, resto). Una traccia per
        stem nella stessa posizione; la clip originale resta, silenziata."""
        t, c = self._clip(clip)
        if c.kind != "audio" or not c.asset:
            raise EditError(f"{c.name or c.id} is not an audio clip")
        motore = self._motore_stem(engine)
        a = self.project.asset(c.asset)
        src = render.resolve(a.path, self.base_dir)
        if motore == "uvr":
            nome_modello, _ = uvr.scegli(model)
            cartella = self.assets_dir() / "stems" / f"{a.id}_uvr_{Path(nome_modello).stem}"
            gia = sorted(cartella.glob("*.wav")) if cartella.is_dir() else []
            try:
                stems = ({uvr._nome_stem(f): f for f in gia} if gia else uvr.separa(src, cartella, nome_modello))
            except uvr.UvrError as exc:
                raise EditError(str(exc)) from exc
            origine = f"uvr {nome_modello} of {a.name}"
        else:
            nome_modello = model or "htdemucs"
            cartella = self.assets_dir() / "stems" / f"{a.id}_{nome_modello}{'_2' if two_stems else ''}"
            try:
                stems = separa.separa(src, cartella, two_stems, nome_modello)
            except separa.SeparaError as exc:
                raise EditError(str(exc)) from exc
            origine = f"demucs {nome_modello} of {a.name}"
        create = []
        with self._edit():
            for chiave, f in stems.items():
                nome, ruolo = self._STEM_NOMI.get(chiave.lower(), (chiave.title(), ""))
                sa = self._asset_da(f, f"{a.name} {nome}", ".wav", origine)
                r = self.add_track(kind="audio", name=f"{nome} ({c.name or a.name})"[:40], role=ruolo,
                                   index=self.project.tracks.index(t) + 1 + len(create))
                n = copy.deepcopy(c)
                n.id = new_id("C")
                n.asset = sa.id
                n.name = nome
                n.muted = False
                self.project.track(r["id"]).clips.append(n)
                create.append({"stem": chiave, "track": r["name"], "track_id": r["id"], "clip": n.id, "role": ruolo})
            c.muted = True
        return {"engine": motore, "model": nome_modello, "stems": create, "original_muted": c.id}

    def audio_to_midi(self, clip: str, mode: str = "melody", sound: str | None = None, grid: float = 0.25,
                      name: str | None = None) -> dict:
        """Note da un audio: ``melody`` (una voce alla volta: canto, fischio, basso, solista) o
        ``drums`` (beatbox -> cassa/rullante/charleston). Nuova traccia MIDI allineata alla clip."""
        if mode not in ("melody", "drums"):
            raise EditError("mode must be melody or drums")
        t, c, seg = self._audio_clip(clip)
        sr = self.project.sample_rate
        note = trascrivi.melody(seg, sr) if mode == "melody" else trascrivi.drums(seg, sr)
        if not note:
            raise EditError("no notes found: is the clip silent, or polyphonic (try separate_stems first)?")
        spb = self.project.seconds_per_beat
        battute = [{"pitch": n["pitch"], "start": n["start"] / spb, "length": max(0.05, n["length"] / spb),
                    "velocity": n["velocity"]} for n in note]
        if grid:
            battute = theory.quantize(battute, grid, 1.0, 0.0, lengths=mode == "melody")
        with self._edit():
            r = self.add_track(kind="midi", name=name or f"{c.name or 'Audio'} MIDI",
                               sound=sound or ("acoustic kit" if mode == "drums" else "soft lead"),
                               role="drums" if mode == "drums" else "lead")
            nc = Clip(id=new_id("C"), name=name or f"{c.name or 'Audio'} notes", kind="midi", start=c.start,
                      length=c.length, notes=[self._norm_note(n) for n in battute if n["start"] < c.length])
            self.project.track(r["id"]).clips.append(nc)
        return {"track": r["name"], "track_id": r["id"], "clip": nc.id, "notes": len(nc.notes),
                "range": (f"{theory.pitch_name(min(n.pitch for n in nc.notes))}-"
                          f"{theory.pitch_name(max(n.pitch for n in nc.notes))}") if nc.notes else ""}

    def convert_voice(self, clip: str, model: str, pitch: int = 0, f0_method: str = "rmvpe", index_rate: float = 0.5,
                      protect: float = 0.33, autotune: bool = False, autotune_strength: float = 1.0,
                      clean: bool = False, clean_strength: float = 0.7, split_audio: bool = False,
                      formant_shift: float = 0.0, volume_envelope: float = 1.0, embedder: str = "contentvec") -> dict:
        """La voce di una clip (meglio una voce isolata: separate_stems prima) rifatta con un modello
        RVC di Applio, per esempio la voce dell'utente. pitch in semitoni (-12 per una voce maschile
        su una femminile). Nuova traccia; l'originale resta, silenziato."""
        t, c, seg = self._audio_clip(clip)
        d = self.assets_dir() / "voice"
        d.mkdir(parents=True, exist_ok=True)
        src = d / f"in_{c.id}_{uuid.uuid4().hex[:6]}.wav"
        audio_io.write(src, seg, self.project.sample_rate, 24)
        out = d / f"{model}_{c.id}_{uuid.uuid4().hex[:6]}.wav"
        try:
            voce.converti(src, out, model, pitch, f0_method, index_rate, protect, autotune, autotune_strength, clean,
                          clean_strength, split_audio, formant_shift, volume_envelope, embedder)
        except voce.VoceError as exc:
            raise EditError(str(exc)) from exc
        finally:
            src.unlink(missing_ok=True)
        with self._edit():
            a = self._asset_da(out, f"{c.name or 'voice'} ({model})", ".wav", f"applio {model} pitch {pitch}")
            out.unlink(missing_ok=True)
            r = self.add_track(kind="audio", name=f"{model} voice"[:40], role="vocal",
                               index=self.project.tracks.index(t) + 1)
            nc = Clip(id=new_id("C"), name=f"{c.name or 'voice'} ({model})", kind="audio", start=c.start,
                      length=c.length, asset=a.id)
            self.project.track(r["id"]).clips.append(nc)
            c.muted = True
        return {"track": r["name"], "track_id": r["id"], "clip": nc.id, "model": model, "original_muted": c.id}

    def voice_cover(self, clip: str, model: str, pitch: int = 0, uvr_model: str | None = None,
                    engine: str = "auto", **opzioni) -> dict:
        """Il flusso UVR -> Applio in un colpo: separa voce e base della clip, rifa' la voce con il
        modello dell'utente e la rimette sulla base. Restano tutte le tracce (originale, stem, voce
        nuova), cosi' si torna indietro su ogni passo; suonano la base e la voce nuova."""
        motore = self._motore_stem(engine)
        s = self.separate_stems(clip, two_stems=True, model=uvr_model if motore == "uvr" else None, engine=motore)
        voci = [x for x in s["stems"] if x["role"] == "vocal"]
        if not voci:
            raise EditError(f"the separation gave no vocal stem ({', '.join(x['stem'] for x in s['stems'])}): "
                            "pick a vocals/instrumental model")
        v = self.convert_voice(voci[0]["clip"], model, pitch, **opzioni)
        return {"stems": s["stems"], "voice": v, "engine": s["engine"], "model": s["model"],
                "note": "playing: instrumental + converted voice; the original and the separated vocal are muted"}

    # ---- versioni ------------------------------------------------------
    def _cartella_versioni(self) -> Path:
        if self.path:
            d = Path(self.path).with_name(Path(self.path).stem + ".versions")
        else:
            d = self.assets_dir() / "versions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _nome_versione(name: str) -> str:
        pulito = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (name or "")).strip()
        if not pulito:
            raise EditError("the version needs a name")
        return pulito.replace(" ", "_")[:60]

    def _file_versione(self, name: str) -> Path:
        f = self._cartella_versioni() / f"{self._nome_versione(name)}.json"
        if not f.exists():
            nomi = [v["name"] for v in self.snapshots()]
            raise EditError(f"no version named {name!r}; saved: {', '.join(nomi) or 'none'}")
        return f

    def snapshot(self, name: str, note: str = "") -> dict:
        """Salva una versione nominata. Non tocca il documento: niente undo."""
        f = self._cartella_versioni() / f"{self._nome_versione(name)}.json"
        dati = self.project.to_dict()
        dati["_snapshot"] = {"name": name, "note": note.strip(), "time": time.strftime("%Y-%m-%d %H:%M")}
        f.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
        return {"name": name, "tracks": len(self.project.tracks)}

    def snapshots(self) -> list[dict]:
        out = []
        for f in sorted(self._cartella_versioni().glob("*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                dati = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            meta = dati.get("_snapshot") or {}
            out.append({"name": meta.get("name", f.stem), "note": meta.get("note", ""), "time": meta.get("time", ""),
                        "tracks": len(dati.get("tracks") or []), "bpm": dati.get("bpm")})
        return out

    def _progetto_versione(self, name: str) -> Project:
        dati = json.loads(self._file_versione(name).read_text(encoding="utf-8"))
        dati.pop("_snapshot", None)
        return Project.from_obj(dati)

    def restore_snapshot(self, name: str) -> dict:
        nuovo = self._progetto_versione(name)
        with self._edit():
            self.project = nuovo
        return {"restored": name, "tracks": len(self.project.tracks)}

    def delete_snapshot(self, name: str) -> dict:
        self._file_versione(name).unlink()
        return {"deleted": name}

    def compare_versions(self, a: str, b: str | None = None) -> dict:
        """Cosa cambia fra due versioni (o una versione e il documento): tracce, clip, note, tempo,
        e quanto cambia la loudness."""
        pa = self._progetto_versione(a)
        pb = self.project if b is None else self._progetto_versione(b)
        eb = "current" if b is None else b

        def indice(p: Project) -> dict[str, dict]:
            return {t.id: to_dict(t) for t in p.tracks}

        ia, ib = indice(pa), indice(pb)
        cambiate = []
        for k in sorted(set(ia) & set(ib)):
            diversi = sorted(c for c in set(ia[k]) | set(ib[k]) if ia[k].get(c) != ib[k].get(c))
            if diversi:
                cambiate.append({"track": ib[k]["name"], "fields": diversi,
                                 "notes": [sum(len(c["notes"]) for c in ia[k]["clips"]),
                                           sum(len(c["notes"]) for c in ib[k]["clips"])]})
        song = {k: [getattr(pa, k), getattr(pb, k)] for k in ("bpm", "key", "mode", "time_sig", "swing")
                if getattr(pa, k) != getattr(pb, k)}
        out = {"a": a, "b": eb, "song": song,
               "added": [ib[k]["name"] for k in ib if k not in ia][:20],
               "removed": [ia[k]["name"] for k in ia if k not in ib][:20],
               "changed": cambiate[:20],
               "sections": [[s.name for s in pa.sections], [s.name for s in pb.sections]]
               if [s.name for s in pa.sections] != [s.name for s in pb.sections] else None}
        try:
            la = analyze.loudness(render.render(pa, self.base_dir, sr=22050), 22050)["lufs"]
            lb = analyze.loudness(render.render(pb, self.base_dir, sr=22050), 22050)["lufs"]
            out["lufs"] = [la, lb]
        except (OSError, KeyError, ValueError):
            pass
        out["same"] = not (out["added"] or out["removed"] or out["changed"] or song or out["sections"])
        return out


__all__ = ["Store", "EditError"]
