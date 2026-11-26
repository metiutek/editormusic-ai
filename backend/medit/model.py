"""Modello dati del documento (una canzone).

Un documento e' JSON puro: nessuno stato nascosto, tutto serializzabile. Il
render e' una funzione pura del documento (piu' i file audio degli asset),
quindi lo stesso documento produce sempre gli stessi campioni.

Niente e' distruttivo: un effetto e' una voce in ``effects``, un taglio di una
clip audio e' ``offset``/``length`` sopra un file che non viene mai riscritto,
una nota si sposta cambiando due numeri.

Tempo: tutto e' in **beat** (semiminime), con origine 0 all'inizio della
canzone. Il tempo in secondi dipende solo da ``bpm``: cambiare tempo non sposta
niente nella griglia. Le note stanno in beat *relativi all'inizio della clip*.
Gli strumenti (MCP, UI) parlano in battute 1-based per l'arrangiamento
(``bar=1`` = inizio) e in beat per le note: la conversione sta in ``Project``.
"""

from __future__ import annotations

import types
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

AUDIO_EXTS = {".wav", ".flac", ".ogg", ".mp3", ".aif", ".aiff", ".m4a", ".aac", ".opus", ".wma"}
# contenitori video: se c'e' ffmpeg se ne prende l'audio
MEDIA_EXTS = AUDIO_EXTS | {".mp4", ".mkv", ".mov", ".webm", ".avi"}
MIDI_EXTS = {".mid", ".midi"}

TRACK_KINDS = ("midi", "audio", "bus")
CLIP_KINDS = ("midi", "audio")
INSTRUMENT_TYPES = ("synth", "fm", "pluck", "drums", "sampler")

# tavolozza delle tracce: si sceglie in ordine, l'utente la cambia a piacere
TRACK_COLORS = ("#e05a5a", "#e0915a", "#d9c24f", "#7bc96f", "#4fb8a8", "#4f8fd9",
                "#7f6fd9", "#c46fd9", "#d96fa0", "#9aa0a6")


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# (de)serializzazione generica dei dataclass
# --------------------------------------------------------------------------


def to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def _unwrap_optional(ftype: Any) -> Any:
    if get_origin(ftype) in (Union, types.UnionType):
        args = [a for a in get_args(ftype) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ftype


def from_dict(cls: type, data: Any) -> Any:
    """Costruisce un dataclass da dict ignorando le chiavi sconosciute.

    Tollerante in avanti: un documento salvato da una versione futura si apre
    comunque, perdendo solo i campi che non conosciamo.
    """
    if not is_dataclass(cls):
        return data
    if data is None:
        return cls()
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        ftype = _unwrap_optional(hints[f.name])
        if val is not None and is_dataclass(ftype):
            val = from_dict(ftype, val)
        elif get_origin(ftype) is list and val is not None:
            (inner,) = get_args(ftype) or (Any,)
            if is_dataclass(inner):
                val = [from_dict(inner, v) for v in val]
        kwargs[f.name] = val
    return cls(**kwargs)


# --------------------------------------------------------------------------
# parti del documento
# --------------------------------------------------------------------------


@dataclass
class Asset:
    """Un file audio usato dal documento. Non viene mai modificato.

    ``generated`` marca i file prodotti dall'editor (stem separati, rese
    congelate, generazioni IA): stanno nella cartella degli asset del documento.
    ``bpm`` e ``key`` sono quelli misurati all'importazione (o dichiarati), per
    allineare un loop alla canzone. ``source`` ricorda da dove arriva.
    """
    id: str
    path: str
    name: str = ""
    duration: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    generated: bool = False
    source: str = ""
    bpm: float = 0.0
    key: str = ""


@dataclass
class Note:
    pitch: int = 60
    start: float = 0.0     # beat dall'inizio della clip
    length: float = 1.0    # beat
    velocity: int = 100    # 1..127


@dataclass
class Effect:
    type: str
    params: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Automation:
    """Una curva nel tempo: ``points`` = [[beat, valore], ...], lineare fra i punti.

    ``target``: ``volume`` (dB), ``pan`` (-1..1), oppure ``fx.<indice>.<param>``
    per un parametro automatizzabile di un effetto della traccia.
    """
    target: str = "volume"
    points: list[list[float]] = field(default_factory=list)


@dataclass
class Clip:
    """Un blocco sulla timeline. MIDI: ``notes``; audio: un pezzo di ``asset``.

    ``loop_length`` > 0 ripete il contenuto (le prime ``loop_length`` beat) fino
    a riempire ``length``: un pattern di 1 battuta diventa 8 battute senza
    copiare note. Audio: ``offset`` in secondi nel file sorgente, ``transpose``
    cambia altezza (e durata, come un giradischi) ricampionando.
    """
    id: str
    name: str = ""
    kind: str = "midi"
    start: float = 0.0      # beat dall'inizio della canzone
    length: float = 4.0     # beat
    notes: list[Note] = field(default_factory=list)
    asset: str | None = None
    offset: float = 0.0     # secondi nel file (solo audio)
    gain_db: float = 0.0
    fade_in: float = 0.0    # beat
    fade_out: float = 0.0   # beat
    loop_length: float = 0.0
    transpose: int = 0
    muted: bool = False
    color: str | None = None

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class Instrument:
    """Lo strumento di una traccia MIDI: un tipo di sintesi + parametri.

    ``preset`` e' solo il nome da cui e' partito (per mostrarlo); i suoni veri
    sono in ``params``, completi: il documento suona uguale anche se i preset
    cambiano in una versione futura.
    """
    type: str = "synth"
    preset: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class Send:
    bus: str
    level_db: float = -12.0


@dataclass
class Track:
    id: str
    name: str = ""
    kind: str = "midi"
    color: str = "#4f8fd9"
    volume_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    instrument: Instrument | None = None
    clips: list[Clip] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)
    automation: list[Automation] = field(default_factory=list)
    sends: list[Send] = field(default_factory=list)
    # ruolo nel mix (drums, bass, chords, lead, vocal, pad, fx...): aiuta
    # l'analisi e il bilanciamento automatico a sapere cosa aspettarsi
    role: str = ""


@dataclass
class Section:
    """Parte della canzone (intro, strofa, ritornello...) con il suo testo."""
    id: str
    name: str = "verse"
    start: float = 0.0      # beat
    length: float = 16.0    # beat
    lyrics: str = ""
    color: str | None = None

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class Master:
    volume_db: float = 0.0
    effects: list[Effect] = field(default_factory=list)


@dataclass
class Project:
    name: str = "untitled"
    bpm: float = 120.0
    time_sig: list[int] = field(default_factory=lambda: [4, 4])
    key: str = "C"
    mode: str = "major"
    sample_rate: int = 44100
    # swing globale delle clip MIDI quantizzate (0 = dritto, 0.5 = shuffle pieno)
    swing: float = 0.0
    tracks: list[Track] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    master: Master = field(default_factory=Master)
    # regione di loop della riproduzione, in beat: [inizio, fine] o None
    loop: list[float] | None = None
    version: int = 1

    def to_dict(self) -> dict:
        return to_dict(self)

    @classmethod
    def from_obj(cls, data: dict) -> "Project":
        return from_dict(cls, data)

    # ---- tempo ------------------------------------------------------------
    @property
    def beats_per_bar(self) -> float:
        num, den = (self.time_sig + [4, 4])[:2]
        return num * 4.0 / den

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / self.bpm

    def bar_to_beat(self, bar: float) -> float:
        """Battuta 1-based (anche frazionaria: 2.5 = meta' della seconda) -> beat."""
        return (bar - 1.0) * self.beats_per_bar

    def beat_to_bar(self, beat: float) -> float:
        return beat / self.beats_per_bar + 1.0

    def beat_to_s(self, beat: float) -> float:
        return beat * self.seconds_per_beat

    def s_to_beat(self, s: float) -> float:
        return s / self.seconds_per_beat

    def end_beat(self) -> float:
        """Dove finisce il contenuto: l'ultima clip o l'ultima sezione."""
        fine = 0.0
        for t in self.tracks:
            for c in t.clips:
                fine = max(fine, c.end)
        for s in self.sections:
            fine = max(fine, s.end)
        return fine

    # ---- ricerca --------------------------------------------------------
    def track(self, ref: str) -> Track:
        for t in self.tracks:
            if t.id == ref:
                return t
        # anche per nome: l'agente ricorda "Drums" e non "T3fa9c1d2"
        low = str(ref).lower()
        for t in self.tracks:
            if t.name and t.name.lower() == low:
                return t
        raise KeyError(f"track not found: {ref}")

    def clip(self, ref: str) -> tuple[Track, Clip]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == ref:
                    return t, c
        low = str(ref).lower()
        for t in self.tracks:
            for c in t.clips:
                if c.name and c.name.lower() == low:
                    return t, c
        raise KeyError(f"clip not found: {ref}")

    def section(self, ref: str) -> Section:
        for s in self.sections:
            if s.id == ref:
                return s
        low = str(ref).lower()
        for s in self.sections:
            if s.name.lower() == low:
                return s
        raise KeyError(f"section not found: {ref}")

    def asset(self, asset_id: str) -> Asset:
        for a in self.assets:
            if a.id == asset_id:
                return a
        for a in self.assets:
            if a.name and a.name == asset_id:
                return a
        raise KeyError(f"asset not found: {asset_id}")
