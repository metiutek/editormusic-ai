"""Teoria musicale: note, scale, accordi, progressioni e pattern.

E' la parte "compositiva" dell'editor, ed e' deterministica: un agente
scrive ``"vi IV I V"`` in La minore o ``"Am:4 F:4 C:4 G:4"`` e ottiene note
vere, con la condotta delle voci fatta come la farebbe un tastierista. Gli
stessi generatori servono alla UI (pulsanti "chords", "drums", "bass").

Niente qui tocca il documento: le funzioni restituiscono liste di note
(``dict`` con pitch/start/length/velocity, beat relativi), e ``Store`` le mette
in una clip.
"""

from __future__ import annotations

import random
import re
from typing import Any

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
# tonalita' che si scrivono con i bemolle (fondamentale, maggiore/minore)
_BEMOLLI_MAGG = {5, 10, 3, 8, 1, 6}
_BEMOLLI_MIN = {2, 7, 0, 5, 10, 3}
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

SCALES: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "pentatonic_major": (0, 2, 4, 7, 9),
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "chromatic": tuple(range(12)),
}
MODES = tuple(SCALES)

# qualita' -> intervalli dalla fondamentale
CHORD_QUALITIES: dict[str, tuple[int, ...]] = {
    "": (0, 4, 7), "maj": (0, 4, 7), "M": (0, 4, 7),
    "m": (0, 3, 7), "min": (0, 3, 7), "-": (0, 3, 7),
    "dim": (0, 3, 6), "o": (0, 3, 6), "aug": (0, 4, 8), "+": (0, 4, 8),
    "5": (0, 7), "sus2": (0, 2, 7), "sus4": (0, 5, 7), "sus": (0, 5, 7),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "M7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
    "min7": (0, 3, 7, 10), "mmaj7": (0, 3, 7, 11), "dim7": (0, 3, 6, 9), "o7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10), "ø": (0, 3, 6, 10), "7sus4": (0, 5, 7, 10), "aug7": (0, 4, 8, 10),
    "add9": (0, 4, 7, 14), "madd9": (0, 3, 7, 14), "9": (0, 4, 7, 10, 14), "maj9": (0, 4, 7, 11, 14),
    "m9": (0, 3, 7, 10, 14), "11": (0, 4, 7, 10, 14, 17), "m11": (0, 3, 7, 10, 14, 17),
    "13": (0, 4, 7, 10, 14, 21), "7b9": (0, 4, 7, 10, 13), "7#9": (0, 4, 7, 10, 15),
}

# nomi delle percussioni General MIDI usate dai pattern e dal kit di batteria
DRUMS = {
    "kick": 36, "kick2": 35, "rim": 37, "snare": 38, "clap": 39, "snare2": 40,
    "tom_low": 45, "tom_mid": 47, "tom_high": 50, "hat": 42, "hat_pedal": 44, "hat_open": 46,
    "crash": 49, "ride": 51, "ride_bell": 53, "tambourine": 54, "cowbell": 56, "crash2": 57,
    "shaker": 70, "perc": 75,
}
DRUM_NAMES = {v: k for k, v in DRUMS.items()}


class TheoryError(ValueError):
    pass


# --------------------------------------------------------------------------
# note
# --------------------------------------------------------------------------


def pitch_class(name: str) -> int:
    """'C' -> 0, 'F#' -> 6, 'Bb' -> 10."""
    m = re.fullmatch(r"\s*([A-Ga-g])([#b♯♭]*)\s*", str(name))
    if not m:
        raise TheoryError(f"not a note name: {name!r} (use C, F#, Bb...)")
    pc = _PC[m.group(1).upper()]
    for ch in m.group(2):
        pc += 1 if ch in "#♯" else -1
    return pc % 12


def parse_pitch(x: Any) -> int:
    """60, '60', 'C4', 'F#3', 'Bb5' -> numero MIDI (C4 = 60, il Do centrale)."""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        p = int(round(x))
    else:
        s = str(x).strip()
        if re.fullmatch(r"-?\d+", s):
            p = int(s)
        else:
            m = re.fullmatch(r"([A-Ga-g][#b♯♭]*)(-?\d+)", s)
            if not m:
                raise TheoryError(f"not a pitch: {x!r} (use a MIDI number or a name like C4, F#3, Bb5)")
            p = pitch_class(m.group(1)) + (int(m.group(2)) + 1) * 12
            # Cb4 / B#3: l'alterazione attraversa l'ottava
            letter = m.group(1)[0].upper()
            base = _PC[letter] + (int(m.group(2)) + 1) * 12
            if p - base > 6:
                p -= 12
            elif base - p > 6:
                p += 12
    if not 0 <= p <= 127:
        raise TheoryError(f"pitch {x!r} out of the MIDI range 0-127")
    return p


def pitch_name(p: int) -> str:
    return f"{NOTE_NAMES[p % 12]}{p // 12 - 1}"


# --------------------------------------------------------------------------
# scale
# --------------------------------------------------------------------------


def parse_key(key: str, mode: str | None = None) -> tuple[int, str]:
    """'A minor', 'Am', 'F#', ('C', 'dorian') -> (classe di altezza, modo)."""
    k = str(key).strip()
    m = re.fullmatch(r"([A-Ga-g][#b♯♭]?)\s*(m|min|minor|maj|major|[a-z_]+)?", k)
    if not m:
        raise TheoryError(f"not a key: {key!r} (use e.g. C, A minor, F# dorian)")
    root = pitch_class(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix in ("m", "min", "minor"):
        mod = "minor"
    elif suffix in ("", "maj", "major"):
        mod = mode or "major"
    else:
        mod = suffix
    mod = (mode if mode and suffix in ("", "maj", "major") else mod).lower().replace(" ", "_")
    if mod not in SCALES:
        raise TheoryError(f"unknown mode {mod!r}; available: {', '.join(SCALES)}")
    return root, mod


def note_names_for(root: int, mode: str = "major") -> tuple[str, ...]:
    """Diesis o bemolle, come si scrive la tonalita' (Fa maggiore: Bb, non A#)."""
    minore = mode in ("minor", "harmonic_minor", "melodic_minor", "dorian", "phrygian", "pentatonic_minor", "blues")
    return FLAT_NAMES if root in (_BEMOLLI_MIN if minore else _BEMOLLI_MAGG) else NOTE_NAMES


def scale_pcs(key: str, mode: str = "major") -> list[int]:
    root, mod = parse_key(key, mode)
    return [(root + i) % 12 for i in SCALES[mod]]


def in_scale(p: int, pcs: list[int]) -> bool:
    return p % 12 in pcs


def snap_to_scale(p: int, pcs: list[int]) -> int:
    """La nota della scala piu' vicina (a parita', quella sotto)."""
    if p % 12 in pcs:
        return p
    for d in range(1, 7):
        if (p - d) % 12 in pcs:
            return p - d
        if (p + d) % 12 in pcs:
            return p + d
    return p


def scale_info(key: str, mode: str = "major") -> dict:
    """Le note della scala e gli accordi diatonici (triadi e settime)."""
    root, mod = parse_key(key, mode)
    steps = SCALES[mod]
    nomi = note_names_for(root, mod)
    notes = [nomi[(root + s) % 12] for s in steps]
    chords = []
    if len(steps) == 7:
        for i in range(7):
            tri = [steps[(i + k) % 7] + 12 * ((i + k) // 7) for k in (0, 2, 4, 6)]
            ints = tuple(x - tri[0] for x in tri)
            q3 = {(0, 4, 7): "", (0, 3, 7): "m", (0, 3, 6): "dim", (0, 4, 8): "aug"}.get(ints[:3], "")
            q7 = {(0, 4, 7, 11): "maj7", (0, 3, 7, 10): "m7", (0, 4, 7, 10): "7", (0, 3, 6, 10): "m7b5",
                  (0, 3, 6, 9): "dim7", (0, 3, 7, 11): "mmaj7", (0, 4, 8, 11): "maj7#5"}.get(ints, "")
            nome = nomi[(root + steps[i]) % 12]
            roman = ["I", "II", "III", "IV", "V", "VI", "VII"][i]
            if q3 in ("m", "dim"):
                roman = roman.lower()
            chords.append({"degree": roman + ("°" if q3 == "dim" else ""), "triad": nome + q3,
                           "seventh": nome + q7})
    return {"key": nomi[root], "mode": mod, "notes": notes, "chords": chords}


# --------------------------------------------------------------------------
# accordi
# --------------------------------------------------------------------------


def parse_chord(sym: str) -> dict:
    """'Am7', 'F/C', 'Cmaj7', 'G7sus4', 'Bb' -> {root, intervals, bass}."""
    s = str(sym).strip()
    m = re.fullmatch(r"([A-Ga-g][#b♯♭]?)([^/]*)(?:/([A-Ga-g][#b♯♭]?))?", s)
    if not m:
        raise TheoryError(f"not a chord: {sym!r} (use e.g. C, Am7, F/C, Gsus4)")
    root = pitch_class(m.group(1))
    q = m.group(2).strip()
    if q not in CHORD_QUALITIES:
        raise TheoryError(f"unknown chord quality {q!r} in {sym!r}; known: "
                          + ", ".join(sorted({k for k in CHORD_QUALITIES if k}))[:400])
    bass = pitch_class(m.group(3)) if m.group(3) else root
    return {"symbol": s, "root": root, "intervals": list(CHORD_QUALITIES[q]), "bass": bass}


_ROMANI = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}


def roman_to_chord(rn: str, key: str, mode: str = "major") -> str:
    """'vi' in C -> 'Am'; 'V7' -> 'G7'; 'bVII' -> 'Bb'; 'ii7' -> 'Dm7'; 'IV/I'."""
    root, mod = parse_key(key, mode)
    m = re.fullmatch(r"([b#]?)(vii|VII|iii|III|vi|VI|iv|IV|ii|II|v|V|i|I)(°|o|ø|dim|\+|aug)?([^/]*)(?:/(.+))?",
                     rn.strip())
    if not m:
        raise TheoryError(f"not a roman numeral: {rn!r} (use I, ii, V7, bVII, vi...)")
    acc, num, dimaug, rest, slash = m.groups()
    # le alterazioni (bVI, bVII, #IV) si contano sulla scala maggiore della
    # tonica, come nei libri: in La minore "i bVI bIII bVII" = Am F C G
    steps = SCALES["major"] if acc or len(SCALES[mod]) != 7 else SCALES[mod]
    deg = _ROMANI[num.lower()]
    pc = (root + steps[deg] + (-1 if acc == "b" else 1 if acc == "#" else 0)) % 12
    q = "m" if num.islower() else ""
    if dimaug in ("°", "o", "dim"):
        q = "dim"
    elif dimaug == "ø":
        q = "m7b5"
    elif dimaug in ("+", "aug"):
        q = "aug"
    rest = rest or ""
    if rest:
        if q == "m":
            q = "m" + rest if ("m" + rest) in CHORD_QUALITIES else rest
        elif q == "dim":
            q = "dim7" if rest == "7" else "dim"
        elif q == "aug":
            q = "aug7" if rest == "7" else "aug"
        elif q == "":
            q = rest
    nomi = note_names_for(root, mod) if not acc else (FLAT_NAMES if acc == "b" else NOTE_NAMES)
    nome = nomi[pc] + q
    if slash:
        nome += "/" + (nomi[(root + steps[_ROMANI[slash.lower()]]) % 12]
                       if slash.lower() in _ROMANI else slash)
    parse_chord(nome)
    return nome


def parse_progression(text: str, key: str = "C", mode: str = "major",
                      beats_per_bar: float = 4.0, default_beats: float | None = None) -> list[tuple[str, float]]:
    """Una progressione in una delle forme che si scrivono davvero:

    - ``"Am F C G"``: un accordo per battuta;
    - ``"Am:4 F:2 G:2"``: durata in beat dopo i due punti;
    - ``"| Am | F | C G |"``: battute separate da barre, piu' accordi = si dividono la battuta;
    - ``"vi IV I V"`` / ``"ii7 V7 Imaj7"``: gradi romani nella tonalita' del brano;
    - ``"-"`` o ``"%"`` ripetono l'accordo precedente.

    Restituisce [(simbolo, durata in beat), ...].
    """
    bar = default_beats or beats_per_bar
    text = str(text).strip()
    if not text:
        raise TheoryError("empty progression")

    def risolvi(tok: str, prec: str | None) -> str:
        if tok in ("-", "%", "."):
            if prec is None:
                raise TheoryError("a repeat sign needs a chord before it")
            return prec
        if re.match(r"^[b#]?[ivIV]", tok) and not re.match(r"^[A-G]", tok):
            return roman_to_chord(tok, key, mode)
        parse_chord(tok)
        return tok

    out: list[tuple[str, float]] = []
    prec = None
    if "|" in text:
        for misura in [m for m in text.split("|") if m.strip()]:
            toks = misura.split()
            for tok in toks:
                nome, _, dur = tok.partition(":")
                prec = risolvi(nome, prec)
                out.append((prec, float(dur) if dur else beats_per_bar / len(toks)))
        return out
    for tok in re.split(r"[\s,]+", text):
        if not tok:
            continue
        nome, _, dur = tok.partition(":")
        prec = risolvi(nome, prec)
        out.append((prec, float(dur) if dur else bar))
    return out


def voice_chord(sym: str, center: int = 60, prev: list[int] | None = None, spread: bool = False) -> list[int]:
    """Altezze MIDI dell'accordo vicino a ``center``; con ``prev`` sceglie il rivolto
    che si muove meno (condotta delle voci), come un pianista."""
    c = parse_chord(sym)
    base = [c["root"] + i for i in c["intervals"]]
    candidati = []
    n = len(base)
    for inv in range(n):
        v = sorted(base[inv:] + [x + 12 for x in base[:inv]])
        for ott in range(-3, 4):
            w = [x + 12 * ott + 60 - 12 for x in v]
            # vicino al centro
            candidati.append(w)
    def costo(w: list[int]) -> float:
        media = sum(w) / len(w)
        k = abs(media - center) * 0.6
        if prev:
            k += sum(min(abs(a - b) for b in prev) for a in w) / len(w) * 1.0
        if w[0] < 40:
            k += 20   # accordi troppo bassi impastano
        return k
    best = min(candidati, key=costo)
    if spread and len(best) >= 3:
        best = [best[0] - 12] + best[1:]
    return [max(0, min(127, x)) for x in best]


def chord_bass(sym: str, octave: int = 2) -> int:
    c = parse_chord(sym)
    return c["bass"] + (octave + 1) * 12


# --------------------------------------------------------------------------
# generatori: accordi
# --------------------------------------------------------------------------

CHORD_STYLES = {
    "block": "one chord held for its whole length",
    "pad": "held and slightly overlapping (legato), for pads and strings",
    "half": "struck every half note",
    "quarter": "struck on every beat",
    "eighths": "straight eighths, pop/rock piano",
    "offbeat": "on the 'and' of every beat (reggae/ska skank, house stabs)",
    "syncopated": "pop syncopation: 1, the 'and' of 2, 4",
    "ballad": "low root on the beat, chord on beats 1 and 3 in the right hand",
    "strum": "guitar strum down-up with a tiny spread between strings",
    "stabs": "short stabs on 1 and the 'and' of 2 (funk, EDM)",
}


def _n(p: int, s: float, l: float, v: int) -> dict:
    return {"pitch": int(p), "start": round(float(s), 4), "length": round(max(0.01, float(l)), 4),
            "velocity": int(max(1, min(127, v)))}


def chords_notes(prog: list[tuple[str, float]], style: str = "block", center: int = 60,
                 velocity: int = 90, spread: bool = False) -> list[dict]:
    if style not in CHORD_STYLES:
        raise TheoryError(f"unknown chord style {style!r}; available: {', '.join(CHORD_STYLES)}")
    out: list[dict] = []
    t = 0.0
    prev = None
    for sym, dur in prog:
        v = voice_chord(sym, center, prev, spread)
        prev = v

        def colpi(posizioni: list[float], lunghezza: float, vel: int = velocity):
            for pos in posizioni:
                if pos < dur - 1e-6:
                    for p in v:
                        out.append(_n(p, t + pos, min(lunghezza, dur - pos), vel))

        if style == "block":
            colpi([0], dur)
        elif style == "pad":
            colpi([0], dur + 0.05, velocity - 10)
        elif style == "half":
            colpi([x * 2.0 for x in range(int(dur / 2 + 0.999))], 1.9)
        elif style == "quarter":
            colpi([float(x) for x in range(int(dur + 0.999))], 0.9)
        elif style == "eighths":
            for i in range(int(dur * 2 + 0.999)):
                colpi([i * 0.5], 0.45, velocity if i % 2 == 0 else velocity - 18)
        elif style == "offbeat":
            colpi([x + 0.5 for x in range(int(dur + 0.999))], 0.3)
        elif style == "syncopated":
            for b in range(0, int(dur + 0.999), 4):
                colpi([b + 0.0], 1.4)
                colpi([b + 1.5], 1.4, velocity - 8)
                colpi([b + 3.0], 0.9, velocity - 12)
        elif style == "ballad":
            basso = chord_bass(sym, 2)
            for b in range(0, int(dur + 0.999), 2):
                if b < dur:
                    out.append(_n(basso + 12, t + b, min(2, dur - b), velocity))
            colpi([float(x) for x in range(0, int(dur + 0.999), 2)], 1.9, velocity - 10)
        elif style == "strum":
            pattern = [(0, 1), (1.0, 0), (1.5, 1), (2.5, 1), (3.0, 0), (3.5, 1)]
            for b in range(0, int(dur + 0.999), 4):
                for pos, giu in pattern:
                    if b + pos >= dur:
                        continue
                    voci = v if giu else list(reversed(v))
                    for k, p in enumerate(voci):
                        out.append(_n(p, t + b + pos + k * 0.012, 0.9 - k * 0.012,
                                      (velocity if giu else velocity - 22) - k * 2))
        elif style == "stabs":
            for b in range(0, int(dur + 0.999), 4):
                colpi([b + 0.0, b + 1.5], 0.25)
        t += dur
    return out


# --------------------------------------------------------------------------
# generatori: basso
# --------------------------------------------------------------------------

BASS_STYLES = {
    "root": "the root held for the whole chord",
    "pulse": "root on every eighth (rock, pop drive)",
    "quarter": "root on every beat",
    "octave": "root and its octave alternating in eighths (disco, dance)",
    "walking": "walking quarter notes towards the next chord (jazz, swing)",
    "syncopated": "pop/funk: 1, the 'and' of 2, 3 with a passing fifth",
    "808": "long 808 notes on 1 and the 'and' of 2 (trap, hip-hop)",
    "offbeat": "on every off-beat eighth (house)",
    "arp": "root-fifth-octave-fifth in eighths",
}


def bass_notes(prog: list[tuple[str, float]], style: str = "root", octave: int = 2,
               velocity: int = 100) -> list[dict]:
    if style not in BASS_STYLES:
        raise TheoryError(f"unknown bass style {style!r}; available: {', '.join(BASS_STYLES)}")
    out: list[dict] = []
    t = 0.0
    for i, (sym, dur) in enumerate(prog):
        r = chord_bass(sym, octave)
        c = parse_chord(sym)
        quinta = r + 7 if 7 in c["intervals"] or 6 in c["intervals"] else r + 7
        terza = r + c["intervals"][1] if len(c["intervals"]) > 1 else r + 4
        nxt = chord_bass(prog[(i + 1) % len(prog)][0], octave)
        if style == "root":
            out.append(_n(r, t, dur - 0.05, velocity))
        elif style == "pulse":
            for k in range(int(dur * 2 + 0.999)):
                out.append(_n(r, t + k * 0.5, 0.45, velocity if k % 2 == 0 else velocity - 15))
        elif style == "quarter":
            for k in range(int(dur + 0.999)):
                out.append(_n(r, t + k, 0.9, velocity))
        elif style == "octave":
            for k in range(int(dur * 2 + 0.999)):
                out.append(_n(r + (12 if k % 2 else 0), t + k * 0.5, 0.4, velocity))
        elif style == "walking":
            passi = [r, terza, quinta, nxt + (1 if nxt < r else -1)]
            for k in range(int(dur + 0.999)):
                out.append(_n(passi[k % 4], t + k, 0.9, velocity - (k % 2) * 10))
        elif style == "syncopated":
            for b in range(0, int(dur + 0.999), 4):
                for pos, p, l in ((0, r, 1.4), (1.5, r, 0.9), (2.5, quinta, 0.4), (3, r, 0.9)):
                    if b + pos < dur:
                        out.append(_n(p, t + b + pos, l, velocity - (0 if pos == 0 else 12)))
        elif style == "808":
            for b in range(0, int(dur + 0.999), 4):
                out.append(_n(r, t + b, min(1.5, dur - b), velocity))
                if b + 1.5 < dur:
                    out.append(_n(r, t + b + 1.5, min(2.4, dur - b - 1.5), velocity - 10))
        elif style == "offbeat":
            for k in range(int(dur + 0.999)):
                out.append(_n(r, t + k + 0.5, 0.4, velocity))
        elif style == "arp":
            passi = [r, quinta, r + 12, quinta]
            for k in range(int(dur * 2 + 0.999)):
                out.append(_n(passi[k % 4], t + k * 0.5, 0.45, velocity - (k % 2) * 10))
        t += dur
    return [n for n in out if n["start"] < t]


# --------------------------------------------------------------------------
# generatori: arpeggi
# --------------------------------------------------------------------------

ARP_PATTERNS = ("up", "down", "updown", "random", "chord_tones_octave", "alberti")


def arp_notes(prog: list[tuple[str, float]], pattern: str = "up", rate: float = 0.25, octaves: int = 1,
              center: int = 64, velocity: int = 85, gate: float = 0.8, seed: int = 0) -> list[dict]:
    if pattern not in ARP_PATTERNS:
        raise TheoryError(f"unknown arpeggio pattern {pattern!r}; available: {', '.join(ARP_PATTERNS)}")
    rnd = random.Random(seed)
    out: list[dict] = []
    t = 0.0
    prev = None
    for sym, dur in prog:
        v = voice_chord(sym, center, prev)
        prev = v
        pool = [p + 12 * o for o in range(max(1, octaves)) for p in v]
        if pattern == "down":
            seq = list(reversed(pool))
        elif pattern == "updown":
            seq = pool + list(reversed(pool))[1:-1] if len(pool) > 2 else pool
        elif pattern == "alberti" and len(v) >= 3:
            seq = [v[0], v[2], v[1], v[2]]
        elif pattern == "chord_tones_octave":
            seq = pool + [pool[0] + 12 * max(1, octaves)]
        else:
            seq = pool
        k = 0
        pos = 0.0
        while pos < dur - 1e-6:
            p = rnd.choice(pool) if pattern == "random" else seq[k % len(seq)]
            acc = velocity + (8 if abs((t + pos) % 1.0) < 1e-6 else 0)
            out.append(_n(p, t + pos, min(rate * gate, dur - pos), acc))
            k += 1
            pos += rate
        t += dur
    return out


# --------------------------------------------------------------------------
# melodie in notazione testuale
# --------------------------------------------------------------------------


def parse_melody(text: str, default_length: float = 1.0, velocity: int = 100) -> list[dict]:
    """Una melodia scritta come si detta:

    ``"C5:1 D5:0.5 E5:0.5 r:1 G5:2"`` — nota:durata in beat, ``r`` = pausa.
    Durata omessa = quella precedente. ``C5:1!`` accento, ``C5:1?`` piano.
    ``[C4 E4 G4]:2`` = accordo. ``~`` dopo la durata lega con la successiva (``C5:1~ C5:1``).
    Restituisce note con start relativo all'inizio della melodia.
    """
    out: list[dict] = []
    t = 0.0
    dur = default_length
    toks = re.findall(r"\[[^\]]*\](?::[\d./]+)?[!?~]*|\S+", str(text))
    if not toks:
        raise TheoryError("empty melody")
    legata: dict | None = None
    for tok in toks:
        m = re.fullmatch(r"(\[[^\]]*\]|[^:!?~]+)(?::([\d./]+))?([!?~]*)", tok)
        if not m:
            raise TheoryError(f"cannot read {tok!r} in the melody (use NOTE:BEATS like C5:0.5)")
        nome, d, mod = m.groups()
        if d:
            if "/" in d:
                a, b = d.split("/", 1)
                dur = float(a or 1) / float(b)
            else:
                dur = float(d)
        vel = velocity + (20 if "!" in mod else 0) - (30 if "?" in mod else 0)
        if nome.lower() in ("r", "rest", "-", "_"):
            t += dur
            legata = None
            continue
        altezze = [parse_pitch(x) for x in nome.strip("[]").split()] if nome.startswith("[") else [parse_pitch(nome)]
        if legata is not None and len(altezze) == 1 and legata["pitch"] == altezze[0]:
            legata["length"] = round(legata["length"] + dur, 4)
            nota = legata
        else:
            nota = None
            for p in altezze:
                nota = _n(p, t, dur * (0.95 if "~" not in mod else 1.0), vel)
                out.append(nota)
        legata = nota if "~" in mod else None
        t += dur
    return out


# --------------------------------------------------------------------------
# batteria
# --------------------------------------------------------------------------

# Pattern a passi di sedicesimi (16 per battuta in 4/4): una stringa per
# strumento, "x" colpo pieno, "o" colpo leggero (ghost), "." niente, "r" rullata
# di hi-hat (trentaduesimi). Le varianti di intensita' tolgono o aggiungono.
DRUM_PATTERNS: dict[str, dict[str, Any]] = {
    "pop": {"desc": "four-on-the-floor-free pop/rock backbeat",
            "kick": "x.......x.x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."},
    "rock": {"desc": "straight rock beat with open hat lift",
             "kick": "x.....x.x.......", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x.",
             "crash_first": True},
    "house": {"desc": "four on the floor, off-beat open hats, clap on 2 and 4",
              "kick": "x...x...x...x...", "clap": "....x.......x...", "hat_open": "..x...x...x...x.",
              "hat": "x.x.x.x.x.x.x.x."},
    "techno": {"desc": "driving four on the floor, 16th hats, rim accents",
               "kick": "x...x...x...x...", "hat": "xoxoxoxoxoxoxoxo", "clap": "....x.......x...",
               "rim": "......x.......x."},
    "trap": {"desc": "half-time trap: sparse 808 kicks, snare/clap on 3, rolling hats",
             "kick": "x......x..x.....", "clap": "........x.......", "snare": "........x.......",
             "hat": "x.x.x.x.x.rrx.x.", "half_time": True},
    "hiphop": {"desc": "boom bap: swung kick and snare on 2 and 4",
               "kick": "x......xx.x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x.",
               "swing": 0.25},
    "lofi": {"desc": "lazy lo-fi hip-hop, soft ghost snares, heavy swing",
             "kick": "x.......x.x.....", "snare": "....x..o....x...", "hat": "x.xox.x.x.xox.x.",
             "swing": 0.35},
    "reggaeton": {"desc": "dembow: kick on every beat, snare on the 'and' of 2 and the 4-e",
                  "kick": "x...x...x...x...", "snare": "...x..x....x..x.", "hat": "x.x.x.x.x.x.x.x."},
    "dnb": {"desc": "drum and bass two-step at double time feel",
            "kick": "x.........x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x.",
            "ride": "x...x...x...x..."},
    "funk": {"desc": "syncopated funk with ghost notes",
             "kick": "x..x..x...x..x..", "snare": "....x.o..o..x..o", "hat": "xxxxxxxxxxxxxxxx"},
    "disco": {"desc": "four on the floor, open hat on every off-beat",
              "kick": "x...x...x...x...", "snare": "....x.......x...", "hat_open": "..x...x...x...x.",
              "hat": "x...x...x...x..."},
    "afrobeats": {"desc": "afrobeats/amapiano-ish shuffle with rim and shaker",
                  "kick": "x..x....x..x....", "rim": "...x..x....x..x.", "shaker": "xoxoxoxoxoxoxoxo",
                  "clap": "....x.......x...", "swing": 0.15},
    "ballad": {"desc": "slow ballad: soft kick, rim click, ride",
               "kick": "x.......x.......", "rim": "....x.......x...", "ride": "x...x...x...x..."},
    "halftime": {"desc": "half-time groove, snare on 3",
                 "kick": "x.....x...x.....", "snare": "........x.......", "hat": "x.x.x.x.x.x.x.x."},
}

FILL = {"snare": "........xoxoxxxx", "tom_high": "............x...", "tom_mid": ".............x..",
        "tom_low": "..............xx"}


def drum_notes(genre: str = "pop", bars: int = 4, beats_per_bar: float = 4.0, intensity: str = "normal",
               fill_every: int = 0, swing: float | None = None, humanize: float = 0.0, seed: int = 0,
               crash_start: bool | None = None, velocity: int = 105) -> tuple[list[dict], float]:
    """Note di batteria (GM) per ``bars`` battute; restituisce anche lo swing consigliato."""
    if genre not in DRUM_PATTERNS:
        raise TheoryError(f"unknown drum genre {genre!r}; available: {', '.join(DRUM_PATTERNS)}")
    if intensity not in ("sparse", "normal", "busy"):
        raise TheoryError("intensity must be sparse, normal or busy")
    pat = DRUM_PATTERNS[genre]
    sw = pat.get("swing", 0.0) if swing is None else swing
    rnd = random.Random(seed)
    steps = int(round(beats_per_bar * 4))
    out: list[dict] = []
    for b in range(int(bars)):
        fill = fill_every and (b + 1) % fill_every == 0
        for nome, riga in pat.items():
            if nome in ("desc", "swing", "half_time", "crash_first"):
                continue
            r = riga
            if intensity == "sparse" and nome in ("hat", "shaker", "ride"):
                r = "".join(c if i % 4 == 0 else "." for i, c in enumerate(r))
            if intensity == "busy" and nome == "hat":
                r = "".join("x" if i % 2 == 0 else ("o" if c == "." else c) for i, c in enumerate(r))
            if intensity == "busy" and nome == "kick":
                r = r[:14] + ("x." if r[14] == "." else r[14:])
            for i in range(steps):
                c = r[i % len(r)]
                if fill and i >= steps // 2 and nome in ("snare", "clap", "hat_open"):
                    continue
                if c == ".":
                    continue
                pos = b * beats_per_bar + i * 0.25
                if c == "r":
                    for k in range(2):
                        out.append(_n(DRUMS[nome], pos + k * 0.125, 0.1, velocity - 25 + k * 5))
                    continue
                vel = velocity if c == "x" else velocity - 45
                if nome in ("hat", "shaker") and i % 2 == 1:
                    vel -= 15
                out.append(_n(DRUMS[nome], pos, 0.2, vel))
        if fill:
            for nome, riga in FILL.items():
                for i in range(steps):
                    c = riga[i % len(riga)]
                    if c != "." and i >= steps // 2:
                        out.append(_n(DRUMS[nome], b * beats_per_bar + i * 0.25, 0.2,
                                      velocity - (40 if c == "o" else 5) + (i - steps // 2) * 2))
        if (pat.get("crash_first", False) if crash_start is None else crash_start) and b == 0:
            out.append(_n(DRUMS["crash"], 0, 1, velocity - 10))
        if fill and b + 1 < bars:
            out.append(_n(DRUMS["crash"], (b + 1) * beats_per_bar, 1, velocity - 5))
    if sw > 0:
        # swing dei sedicesimi in levare, prima dell'umanizzazione (che sposta di poco)
        for n in out:
            n["start"] = round(apply_swing(n["start"], sw, 0.25), 4)
    if humanize > 0:
        for n in out:
            n["start"] = round(max(0.0, n["start"] + rnd.uniform(-1, 1) * humanize * 0.03), 4)
            n["velocity"] = int(max(1, min(127, n["velocity"] + rnd.uniform(-1, 1) * humanize * 12)))
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out, sw


# --------------------------------------------------------------------------
# operazioni sulle note
# --------------------------------------------------------------------------


def apply_swing(start: float, swing: float, grid: float = 0.5) -> float:
    """Sposta le note sul contrattempo della griglia: 0 dritto, 1 = terzina piena."""
    if swing <= 0:
        return start
    pos = start / grid
    k = int(pos + 1e-6)
    if k % 2 == 1 and abs(pos - k) < 1e-3:
        return start + grid * swing / 3.0
    return start


def quantize(notes: list[dict], grid: float = 0.25, strength: float = 1.0, swing: float = 0.0,
             lengths: bool = False) -> list[dict]:
    out = []
    for n in notes:
        q = round(n["start"] / grid) * grid
        if swing:
            q = apply_swing(q, swing, grid)
        s = n["start"] + (q - n["start"]) * strength
        m = dict(n, start=round(max(0.0, s), 4))
        if lengths:
            m["length"] = round(max(grid, round(n["length"] / grid) * grid), 4)
        out.append(m)
    return out


def humanize(notes: list[dict], timing: float = 0.02, velocity: float = 8, seed: int = 0) -> list[dict]:
    rnd = random.Random(seed)
    return [dict(n, start=round(max(0.0, n["start"] + rnd.gauss(0, timing)), 4),
                 velocity=int(max(1, min(127, n["velocity"] + rnd.gauss(0, velocity)))))
            for n in notes]


def progressions_for(mood: str = "") -> list[dict]:
    """Progressioni collaudate, per chi deve partire da qualcosa."""
    tutte = [
        {"name": "axis (pop)", "roman": "I V vi IV", "mood": "uplifting, pop, anthem"},
        {"name": "sad pop", "roman": "vi IV I V", "mood": "emotional, bittersweet, pop ballad"},
        {"name": "50s doo-wop", "roman": "I vi IV V", "mood": "nostalgic, retro, sweet"},
        {"name": "jazz ii-V-I", "roman": "ii7 V7 Imaj7 Imaj7", "mood": "jazz, smooth, sophisticated"},
        {"name": "andalusian", "roman": "i bVII bVI V", "mood": "dramatic, flamenco, minor, epic", "mode": "minor"},
        {"name": "minor trap", "roman": "i bVI bIII bVII", "mood": "dark, trap, hip-hop, minor", "mode": "minor"},
        {"name": "epic minor", "roman": "i bVI bVII i", "mood": "cinematic, epic, minor", "mode": "minor"},
        {"name": "lofi", "roman": "IVmaj7 iii7 ii7 Imaj7", "mood": "lofi, chill, warm, jazzy"},
        {"name": "royal road (J-pop)", "roman": "IVmaj7 V7 iii7 vi", "mood": "j-pop, anime, emotional"},
        {"name": "blues 12 bar", "roman": "I7 I7 I7 I7 IV7 IV7 I7 I7 V7 IV7 I7 V7", "mood": "blues, rock and roll"},
        {"name": "house minor", "roman": "i iv bVII bIII", "mood": "house, dance, deep, minor", "mode": "minor"},
        {"name": "canon", "roman": "I V vi iii IV I IV V", "mood": "classical, wedding, warm"},
        {"name": "reggaeton", "roman": "i bVI bIII bVII", "mood": "reggaeton, latin, dance", "mode": "minor"},
        {"name": "dorian groove", "roman": "i IV i IV", "mood": "funk, groove, dorian", "mode": "dorian"},
    ]
    if not mood:
        return tutte
    parole = mood.lower().split()
    scelte = [p for p in tutte if any(w in p["mood"] or w in p["name"] for w in parole)]
    return scelte or tutte
