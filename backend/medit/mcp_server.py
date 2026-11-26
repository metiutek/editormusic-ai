"""Server MCP: espone l'editor musicale come strumenti per un agente.

Filosofia degli strumenti (la stessa di vedit e pedit):
- ogni strumento e' un metodo di ``Store``: niente scorciatoie riservate
  all'agente, niente che la UI non possa fare;
- risposte compatte, in JSON senza spazi: ogni risposta resta nel contesto;
- errori con messaggio utile, che dicono cosa era ammesso;
- l'agente non sente: ``preview`` restituisce immagini vere (arrangiamento,
  piano roll, spettrogramma) e ``analyze_mix`` i numeri, cosi' *guarda e misura*
  invece di indovinare.

Avvio: ``medit-mcp`` (stdio). Dentro ``medit ui`` lo stesso server risponde su
``/mcp/`` e lavora sulla canzone aperta nel browser.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import io
import json
import sys
import time as _time
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from . import __version__, ai, audio_io, cloud, comfy, memoria, presets, segnalazioni, synth, theory, visual, voce
from . import analyze as analyze_mod
from . import domande as domande_mod
from . import effects as fx
from .store import EditError, Store

ISTRUZIONI = """\
Editor musicale (DAW) non distruttivo: tracce MIDI con strumenti interni (synth,
FM, corde pizzicate, batteria, sampler), tracce audio, bus di effetti, master.

Flusso: project_create (bpm, key, mode) -> structure (intro/strofa/ritornello...)
-> add_drums / add_chords / add_bassline / add_arpeggio / add_melody (oppure
add_clip + add_notes) -> suoni (set_instrument, list_sounds) -> effetti
(add_effect, apply_chain, add_bus + set_send) -> preview + analyze_mix ->
review_song -> auto_master -> export_audio (solo se l'utente lo chiede).

POSIZIONI. L'arrangiamento e' in battute 1-based: bar=1 e' l'inizio, bar=9.5 la
meta' della nona; le lunghezze in battute (bars). Le note stanno in beat dentro
la clip (0 = inizio clip, 1 beat = una semiminima). Altezze: numero MIDI o nome
(C4 = 60 = Do centrale, F#3, Bb5). Tracce, clip e sezioni per id o per nome.

== NON PUOI ASCOLTARE: GUARDA E MISURA ==
preview(view="arrangement") mostra tracce, clip e sezioni; view="piano_roll"
(clip= o track=) le note con le righe della scala; view="mix" forma d'onda e
spettrogramma. analyze_mix da' LUFS, true peak, bande di frequenza, stereo (anche
di una traccia sola: track=). get_notes legge le note esatte. Una parte non
guardata e' una parte non fatta.

== COME SCRIVERE MUSICA ==
1. Armonia prima di tutto: una tonalita' (music_reference da' scala, accordi
   diatonici e progressioni collaudate per umore/genere), poi ritmo, basso,
   melodia. Accordi fuori tonalita' solo se voluti (bVII, prestiti dal minore).
2. Registri separati: basso C1-C3, accordi/pad C3-C5, melodia C4-C6. Due parti
   nello stesso registro si impastano.
3. Il basso segue le fondamentali degli accordi e si incastra con la cassa.
4. Melodia: soprattutto gradi congiunti, pochi salti (e dopo un salto si torna
   indietro), note lunghe e note dell'accordo sui tempi forti, frasi di 2-4
   battute a domanda/risposta, un motivo che ritorna. Il ritornello sale di
   registro rispetto alla strofa. Con un testo: una nota per sillaba, gli
   accenti delle parole sui tempi forti.
5. Contrasto fra sezioni: strofa piu' vuota, ritornello pieno (piu' tracce,
   intensity="busy", accordi in ottava sopra); fill di batteria prima dei cambi
   (fill_every), crash a inizio sezione; intro e outro piu' leggere.
6. Ripeti senza riscrivere: copy_bars (una sezione intera), duplicate_clip,
   loop_bars su una clip.

== IA GENERATIVA ==
ai_status dice cosa c'e' qui (ComfyUI con ACE-Step / Stable Audio, Demucs,
Applio, servizi in rete): chiedilo prima di promettere. generate_song fa una
canzone intera anche cantata (stile + testo: senza lyrics usa i testi delle
sezioni); generate_audio un loop, uno strumento o un effetto lungo N battute;
separate_stems divide un audio negli stem (motore uvr: i modelli di Ultimate
Vocal Remover dell'utente, stem_models li elenca; demucs: voce/batteria/basso/
resto); voice_cover fa in un colpo UVR -> voce dell'utente sulla base; audio_to_midi
trasforma una voce, un fischio o un beatbox in note; convert_voice rifa' una
voce con un modello RVC dell'utente (voice_models). Tutto finisce su tracce
nuove, l'originale resta (silenziato). I servizi in rete costano all'utente:
backend="auto" li usa solo se ne ha scelto uno come predefinito; nominarne uno
solo se l'utente lo chiede. La generazione locale su una GPU piccola dura
minuti: dillo prima.

== MIX ==
- balance_mix fa il gain staging per ruolo; poi ritocca a gusto: batteria,
  basso, voce e lead al centro; accordi, pad e chitarre aperti col pan.
- Riverbero e delay su un bus (add_bus + set_send), non su ogni traccia.
- eq low_cut sulle tracce che non sono basso/cassa: pulisce i bassi.
- review_song prima di dire che hai finito: ogni problema ha lo strumento che
  lo sistema. auto_master alla fine (-14 LUFS per lo streaming).

ECONOMIA. Ogni chiamata rilegge tutto il contesto. batch applica una lista di
modifiche in un colpo solo (un undo); con look=true restituisce anche
l'arrangiamento. project_info solo se non conosci lo stato.

VERSIONI. Prima di una strada diversa (altro genere, altro arrangiamento,
altro ritornello) salva con snapshot; compare_versions dice cosa cambia,
restore_snapshot torna indietro (si annulla con undo).

SCELTE DELL'UTENTE. Per cio' che spetta a lui (genere, tonalita', tempo,
struttura, suono, quale versione tenere) ask_user gli mostra domande con
opzioni nell'editor; senza editor aperto chiedi nella conversazione.

MEMORIA FRA I DOCUMENTI. project_create e project_open restituiscono "memoria":
preferenze di chi fa musica, valide in ogni canzone. Seguile se la richiesta non
dice altro. Quando l'utente esprime una preferenza che vale oltre questa canzone
("i miei beat sono sempre 140 BPM", "niente reverb sulla voce", "master a -9
LUFS"), salvala con remember, breve e concreta. forget toglie, memory legge.

Non esportare mai di tua iniziativa: export_audio / export_stems / export_midi
solo se l'utente lo chiede. Se l'utente vuole sentire o correggere a mano,
open_ui apre l'editor sulla stessa canzone (li' c'e' il play). Quando qualcosa
non va (errore, strumento scomodo, funzione che manca) annotalo con
report_issue e prosegui.
"""

mcp = MCPServer(name="medit", version=__version__, instructions=ISTRUZIONI)

_PREVISTI = (ValueError, KeyError, FileNotFoundError)


def _messaggio(exc: BaseException) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _arrotonda(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _arrotonda(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_arrotonda(v) for v in x]
    return x


def _json(x) -> str:
    return json.dumps(_arrotonda(x), ensure_ascii=False, separators=(",", ":"), default=str)


def _compatto(res):
    if res is None or isinstance(res, (str, Image)):
        return res
    if isinstance(res, (list, tuple)) and any(isinstance(x, Image) for x in res):
        return [x if isinstance(x, (str, Image)) else _json(x) for x in res]
    return _json(res)


def _snello(schema: Any, proprieta: bool = False) -> Any:
    """Schema senza i ``title`` ripetuti e gli ``anyOf [x, null]`` di pydantic.

    Dentro ``properties`` le chiavi sono nomi di parametri: un parametro che si
    chiama ``title`` (report_issue) resta.
    """
    if isinstance(schema, list):
        return [_snello(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    if proprieta:
        return {k: _snello(v) for k, v in schema.items()}
    out = {k: _snello(v, proprieta=(k == "properties")) for k, v in schema.items()
           if not (k == "title" and isinstance(v, str)) and not (k == "default" and v is None)}
    varianti = out.get("anyOf")
    if isinstance(varianti, list):
        senza_null = [v for v in varianti if v != {"type": "null"}]
        if len(senza_null) == 1 and isinstance(senza_null[0], dict):
            del out["anyOf"]
            out = {**senza_null[0], **out}
        elif len(senza_null) != len(varianti):
            out["anyOf"] = senza_null
    return out


# nome -> funzione, per ``batch`` e per l'assistente in chat
STRUMENTI: dict[str, Any] = {}
# strumenti che non hanno senso dentro batch (anteprime, export, interfaccia)
_FUORI_BATCH = {"batch", "preview", "export_audio", "export_stems", "export_midi", "open_ui", "close_ui", "undo",
                "redo", "project_create", "project_open", "report_issue", "ask_user", "remember", "forget", "memory",
                "snapshot", "snapshots", "restore_snapshot", "delete_snapshot", "compare_versions", "analyze_mix",
                "analyze_audio", "review_song", "auto_master", "system_info", "save_chain", "save_sound",
                "delete_preset", "ai_status", "ai_services", "comfy_settings", "voice_models", "generate_song",
                "generate_audio", "separate_stems", "convert_voice", "audio_to_midi", "voice_cover", "stem_models",
                "applio_ui"}

_CTX: contextvars.ContextVar[Context | None] = contextvars.ContextVar("medit_ctx", default=None)
BATTITO_S = 15.0


def _strumento(*args, **kwargs):
    registra = mcp.tool(*args, structured_output=False, **kwargs)

    def applica(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def avvolta(*a, contesto_mcp=None, **k):
                _CTX.set(contesto_mcp)
                try:
                    return _compatto(await fn(*a, **k))
                except _PREVISTI as exc:
                    raise ToolError(_messaggio(exc)) from exc
        else:
            @functools.wraps(fn)
            def avvolta(*a, contesto_mcp=None, **k):
                try:
                    return _compatto(fn(*a, **k))
                except _PREVISTI as exc:
                    raise ToolError(_messaggio(exc)) from exc
        firma = inspect.signature(fn)
        avvolta.__signature__ = firma.replace(parameters=[
            *firma.parameters.values(),
            inspect.Parameter("contesto_mcp", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context)])
        avvolta.__annotations__ = {**getattr(fn, "__annotations__", {}), "contesto_mcp": Context}
        registra(avvolta)
        nome = kwargs.get("name") or fn.__name__
        STRUMENTI[nome] = fn
        tool = mcp._tool_manager.get_tool(nome)
        if tool is not None:
            tool.parameters = _snello(tool.parameters)
            tool.description = inspect.cleandoc(tool.description or "")
        return fn

    return applica


async def _off(fn, *args, **kwargs):
    """Lavoro bloccante (render lunghi) fuori dal loop, con battiti di progresso."""
    ctx = _CTX.get()
    if ctx is None:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    t0, esito = _time.monotonic(), []

    async def battito():
        while True:
            await anyio.sleep(BATTITO_S)
            try:
                await ctx.report_progress(int(_time.monotonic() - t0), None, "working")
            except Exception:  # noqa: BLE001
                return

    async with anyio.create_task_group() as tg:
        tg.start_soon(battito)
        try:
            esito.append(await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs)))
        finally:
            tg.cancel_scope.cancel()
    return esito[0]


# --------------------------------------------------------------------------
# canzone corrente
# --------------------------------------------------------------------------

_stores: dict[str, Store] = {}
_current: list[Store | None] = [None]


def _ospite() -> Store | None:
    """La canzone aperta nell'interfaccia, se questo server gira dentro di lei."""
    api = sys.modules.get("medit.api")
    if api is not None and api.MCP_ATTIVO and api.S.store is not None:
        return api.S.store
    return None


def _ui_attach(s: Store) -> None:
    api = sys.modules.get("medit.api")
    if api is not None and (api.background_info() or api.MCP_ATTIVO) and api.S.store is not s:
        api.attach(s)


def _store(project: str | None = None) -> Store:
    if project is None and (ospite := _ospite()) is not None:
        _current[0] = ospite
        return ospite
    if project:
        key = str(Path(project).resolve())
        if key not in _stores:
            _stores[key] = Store.open(key)
        _current[0] = _stores[key]
        _ui_attach(_current[0])
        return _current[0]
    if _current[0] is None:
        raise EditError("no song open: use project_create or project_open")
    return _current[0]


def _png(img: PILImage.Image) -> Image:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=False)
    return Image(data=buf.getvalue(), format="png")


def _con_memoria(out: dict) -> dict:
    ricordi = memoria.contesto()
    if ricordi:
        out["memoria"] = ricordi
    return out


# --------------------------------------------------------------------------
# canzone
# --------------------------------------------------------------------------


@_strumento()
def project_create(path: str | None = None, name: str = "untitled", bpm: float = 120, key: str = "C",
                   mode: str = "major", time_sig: list[int] | None = None, from_audio: str | None = None) -> dict:
    """Create a song. key: C, F#, Bb...; mode: major, minor, dorian, mixolydian, phrygian, lydian,
    harmonic_minor, pentatonic_minor, blues... (or key="A minor"). time_sig [4,4] default.
    from_audio=<file> starts from an audio file (a beat, a demo): it goes on an audio track and the
    song takes its detected BPM. path=<file.json> saves it (autosave after every edit)."""
    s = Store.create(name=name, bpm=bpm, key=key, mode=mode, time_sig=time_sig, path=path, from_audio=from_audio)
    if s.path:
        _stores[s.path] = s
    _current[0] = s
    _ui_attach(s)
    return _con_memoria(s.summary("brief"))


@_strumento()
def project_open(path: str) -> dict:
    """Open a song (.json), or start one from an audio file (.wav .mp3 .flac...) or a MIDI file (.mid)."""
    s = Store.open(path)
    if s.path:
        _stores[s.path] = s
    _current[0] = s
    _ui_attach(s)
    return _con_memoria(s.summary("normal"))


@_strumento()
def project_info(detail: str = "normal", project: str | None = None) -> dict:
    """The song: tempo, key, sections (with lyrics), tracks with instrument, volume, effects, sends and
    clips. detail: brief | normal | full (full adds every note and parameter)."""
    return _store(project).summary(detail)


@_strumento()
def project_save(path: str | None = None, project: str | None = None) -> dict:
    """Save the song (.json). path= saves to a new file (save as)."""
    s = _store(project)
    return {"path": s.save(path)}


@_strumento()
def set_song(name: str | None = None, bpm: float | None = None, key: str | None = None, mode: str | None = None,
             time_sig: list[int] | None = None, swing: float | None = None, loop: list[float] | None = None,
             clear_loop: bool = False, project: str | None = None) -> dict:
    """Song settings: name, bpm (notes stay on the grid), key + mode (only the label used by the
    theory tools: to move the notes use transpose), time_sig, swing 0-1 (delays off-beat 16ths of all
    MIDI), loop=[first_bar, last_bar] for playback."""
    return _store(project).set_song(name, bpm, key, mode, time_sig, swing, loop, clear_loop)


@_strumento()
def undo(project: str | None = None) -> dict:
    """Undo the last edit."""
    return _store(project).undo()


@_strumento()
def redo(project: str | None = None) -> dict:
    """Redo the last undone edit."""
    return _store(project).redo()


# --------------------------------------------------------------------------
# tracce e suoni
# --------------------------------------------------------------------------


@_strumento()
def add_track(kind: str = "midi", name: str | None = None, sound: str | None = None, instrument: str | None = None,
              params: dict | None = None, volume_db: float = 0.0, pan: float = 0.0, role: str = "",
              index: int | None = None, project: str | None = None) -> dict:
    """New track. kind: midi (plays notes with an instrument), audio (audio files), bus (effect return,
    fed by set_send). sound = a preset from list_sounds (e.g. "electric piano", "808", "trap kit"), or
    instrument = synth | fm | pluck | drums | sampler with params. role (drums, bass, chords, pad, lead,
    vocal, arp, fx) helps balance_mix and review."""
    return _store(project).add_track(kind, name, sound, instrument, params, None, volume_db, pan, role, index)


@_strumento()
def set_track(track: str, name: str | None = None, volume_db: float | None = None, pan: float | None = None,
              mute: bool | None = None, solo: bool | None = None, color: str | None = None,
              role: str | None = None, project: str | None = None) -> dict:
    """Mixer settings of a track: volume_db (-96..+24), pan (-1 left .. 1 right), mute, solo, name, color, role."""
    return _store(project).set_track(track, name, volume_db, pan, mute, solo, color, role)


@_strumento()
def remove_track(track: str, project: str | None = None) -> dict:
    """Delete a track and its clips."""
    return _store(project).remove_track(track)


@_strumento()
def duplicate_track(track: str, name: str | None = None, project: str | None = None) -> dict:
    """Copy a track with clips, instrument and effects (to layer a sound or try a variation)."""
    return _store(project).duplicate_track(track, name)


@_strumento()
def move_track(track: str, index: int, project: str | None = None) -> dict:
    """Reorder: index 0 = top."""
    return _store(project).move_track(track, index)


@_strumento()
def list_sounds(category: str | None = None) -> list:
    """Built-in and saved sounds (instrument presets) by category: keys, pad, lead, pluck, guitar, bass, drums."""
    out = presets.describe_sounds()
    if category:
        out = [x for x in out if x["category"] == category]
    return out


@_strumento()
def instrument_params(type: str = "synth") -> dict:
    """Parameters of an instrument type (synth, fm, pluck, drums, sampler) with defaults and meaning,
    to shape a sound with set_instrument(params=...)."""
    if type not in synth.DEFAULTS:
        raise EditError(f"unknown instrument type {type!r}; available: {', '.join(synth.DEFAULTS)}")
    return {k: {"default": v, "desc": synth.PARAM_DOCS[type].get(k, "")} for k, v in synth.DEFAULTS[type].items()}


@_strumento()
def set_instrument(track: str, sound: str | None = None, type: str | None = None, params: dict | None = None,
                   project: str | None = None) -> dict:
    """Change the sound of a MIDI track: sound = preset name (replaces it), or params = some parameters to
    tweak the current one (merged: e.g. {"cutoff": 900, "release": 0.6}). See instrument_params."""
    return _store(project).set_instrument(track, sound, type, params)


@_strumento()
def save_sound(name: str, track: str, desc: str = "", project: str | None = None) -> dict:
    """Save the instrument of a track as a sound of the user, usable in every song (list_sounds)."""
    return _store(project).save_sound(name, track, desc)


@_strumento()
def add_bus(name: str = "Reverb", chain: str | None = "big reverb bus", volume_db: float = 0.0,
            project: str | None = None) -> dict:
    """An effect return bus with a ready chain (big reverb bus, plate bus, delay bus, or none). Feed it with
    set_send from the tracks: one reverb shared by everything sounds like one room."""
    return _store(project).add_bus(name, chain, volume_db)


@_strumento()
def set_send(track: str, bus: str, level_db: float = -12.0, remove: bool = False, project: str | None = None) -> dict:
    """Send a track (post-fader) to a bus at level_db (-30 subtle .. -6 a lot). remove=true stops it."""
    return _store(project).set_send(track, bus, level_db, remove)


# --------------------------------------------------------------------------
# clip
# --------------------------------------------------------------------------


@_strumento()
def add_clip(track: str, bar: float = 1, bars: float | None = None, name: str | None = None,
             notes: list | None = None, melody: str | None = None, loop_bars: float = 0,
             project: str | None = None) -> dict:
    """A MIDI clip on a track at bar, bars long (default: as long as its notes). notes: [{"pitch": "C4",
    "start": 0, "length": 1, "velocity": 100}] or ["C4", 0, 1, 100] (start/length in beats from the clip
    start). melody: text notation (see add_melody). loop_bars repeats the first N bars to fill the clip."""
    return _store(project).add_clip(track, bar, bars, name, notes, melody, loop_bars)


@_strumento()
async def add_audio(path: str | None = None, asset: str | None = None, track: str | None = None, bar: float = 1,
                    bars: float | None = None, name: str | None = None, offset: float = 0.0,
                    adopt_tempo: bool = False, project: str | None = None) -> dict:
    """Put an audio file (wav, mp3, flac, ogg, aiff; m4a/video with ffmpeg) on an audio track (new if
    track is omitted) at bar. BPM and key are detected. offset = seconds to skip in the file; bars trims
    it. adopt_tempo=true sets the song BPM (and key if empty) to the file's: to build on top of a beat."""
    s = _store(project)
    return await _off(s.add_audio, path, asset, track, bar, bars, name, offset, True, adopt_tempo)


@_strumento()
def set_clip(clip: str, name: str | None = None, bar: float | None = None, bars: float | None = None,
             track: str | None = None, offset: float | None = None, gain_db: float | None = None,
             fade_in: float | None = None, fade_out: float | None = None, loop_bars: float | None = None,
             transpose: int | None = None, muted: bool | None = None, project: str | None = None) -> dict:
    """Move (bar, track), resize (bars), trim audio (offset seconds), gain_db, fades (in beats),
    loop_bars (0 = no loop), transpose in semitones (audio: changes pitch and speed), mute a clip."""
    return _store(project).set_clip(clip, name, bar, bars, track, offset, gain_db, fade_in, fade_out, loop_bars,
                                    transpose, muted)


@_strumento()
def split_clip(clip: str, at_bar: float, project: str | None = None) -> dict:
    """Cut a clip in two at a bar (e.g. 5 or 5.5)."""
    return _store(project).split_clip(clip, at_bar)


@_strumento()
def duplicate_clip(clip: str, times: int = 1, bar: float | None = None, project: str | None = None) -> dict:
    """Copies of a clip one after the other (or at bar)."""
    return _store(project).duplicate_clip(clip, times, bar)


@_strumento()
def remove_clip(clip: str, project: str | None = None) -> dict:
    """Delete a clip."""
    return _store(project).remove_clip(clip)


@_strumento()
def copy_bars(from_bar: float, bars: float, to_bar: float, tracks: list[str] | None = None, sections: bool = True,
              project: str | None = None) -> dict:
    """Copy everything in bars [from_bar, from_bar+bars) to to_bar (all tracks, or only tracks): to repeat a
    whole verse or chorus. Section markers are copied too unless sections=false."""
    return _store(project).copy_bars(from_bar, bars, to_bar, tracks, sections)


@_strumento()
def insert_bars(at_bar: float, bars: float, project: str | None = None) -> dict:
    """Open empty bars at at_bar: everything after moves right (clips across are split)."""
    return _store(project).insert_bars(at_bar, bars)


@_strumento()
def delete_bars(at_bar: float, bars: float, project: str | None = None) -> dict:
    """Remove bars (and what is in them) and close the gap."""
    return _store(project).delete_bars(at_bar, bars)


# --------------------------------------------------------------------------
# note
# --------------------------------------------------------------------------


@_strumento()
def get_notes(clip: str, project: str | None = None) -> dict:
    """All notes of a MIDI clip as [pitch, start_beat, length_beats, velocity], sorted by time. The
    position in this list is the index used by remove_notes / edit_notes."""
    return _store(project).get_notes(clip)


@_strumento()
def add_notes(clip: str, notes: list | None = None, melody: str | None = None, at: float = 0.0,
              project: str | None = None) -> dict:
    """Add notes to a MIDI clip: notes as in add_clip, or melody text starting at beat ``at``."""
    return _store(project).add_notes(clip, notes, melody, at)


@_strumento()
def set_notes(clip: str, notes: list, extend: bool = True, project: str | None = None) -> dict:
    """Replace all the notes of a clip (extend=true lengthens the clip if notes run past its end)."""
    return _store(project).set_notes(clip, notes, extend)


@_strumento()
def remove_notes(clip: str, pitch: Any = None, start: float | None = None, end: float | None = None,
                 indices: list[int] | None = None, all: bool = False, project: str | None = None) -> dict:
    """Remove notes by pitch (one or a list), by beat range [start, end), by index (get_notes), or all."""
    return _store(project).remove_notes(clip, pitch, start, end, indices, all)


@_strumento()
def edit_notes(clip: str, transpose: int = 0, shift: float = 0.0, velocity: int | None = None,
               velocity_scale: float = 1.0, length_scale: float = 1.0, length: float | None = None,
               pitch: Any = None, start: float | None = None, end: float | None = None,
               indices: list[int] | None = None, legato: bool = False, project: str | None = None) -> dict:
    """Change the selected notes (all, or filtered by pitch / beat range / indices): transpose semitones,
    shift beats, set or scale velocity, set or scale length, legato (each note lasts until the next)."""
    return _store(project).edit_notes(clip, transpose, shift, velocity, velocity_scale, length_scale, length,
                                      pitch, start, end, indices, legato)


@_strumento()
def transpose(target: str, semitones: int, project: str | None = None) -> dict:
    """Transpose a clip, or every clip of a track, by semitones (12 = one octave)."""
    return _store(project).transpose(target, semitones)


@_strumento()
def quantize(clip: str, grid: float = 0.25, strength: float = 1.0, swing: float = 0.0, lengths: bool = False,
             project: str | None = None) -> dict:
    """Snap notes to a grid in beats (0.25 = 16ths, 0.5 = 8ths, 0.333 = triplets). strength < 1 keeps some
    feel; swing 0-1 delays the off-beats of the grid; lengths=true snaps durations too."""
    return _store(project).quantize(clip, grid, strength, swing, lengths)


@_strumento()
def humanize(clip: str, timing: float = 0.015, velocity: float = 8, seed: int = 0, project: str | None = None) -> dict:
    """Small random timing (beats) and velocity changes so a part sounds played, not programmed."""
    return _store(project).humanize(clip, timing, velocity, seed)


@_strumento()
def fit_to_scale(target: str, key: str | None = None, mode: str | None = None, project: str | None = None) -> dict:
    """Move the notes of a clip (or a whole track) that are outside the song's scale (or key/mode) to the
    nearest scale note."""
    return _store(project).fit_to_scale(target, key, mode)


# --------------------------------------------------------------------------
# composizione
# --------------------------------------------------------------------------


@_strumento()
def music_reference(key: str | None = None, mode: str | None = None, mood: str = "", project: str | None = None) -> dict:
    """Music theory at hand: the scale and diatonic chords of the key (the song's if omitted), proven
    progressions for a mood/genre (roman numerals, usable directly in add_chords), and the styles
    accepted by add_chords, add_bassline, add_arpeggio and add_drums."""
    if key is None:
        s = _current[0] if _current[0] is not None else _ospite()
        if s is not None:
            key, mode = s.project.key, mode or s.project.mode
    try:
        info = theory.scale_info(key or "C", mode or "major")
    except theory.TheoryError as exc:
        raise EditError(str(exc)) from exc
    return {"scale": info, "progressions": theory.progressions_for(mood),
            "chord_styles": theory.CHORD_STYLES, "bass_styles": theory.BASS_STYLES,
            "arp_patterns": list(theory.ARP_PATTERNS),
            "drum_genres": {k: v["desc"] for k, v in theory.DRUM_PATTERNS.items()},
            "melody_notation": "C5:1 D5:0.5 E5:0.5 r:1 [C4 E4 G4]:2 G5:1~ G5:1 (note:beats, r rest, "
                               "[..] chord, ! accent, ? soft, ~ tie)"}


@_strumento()
def add_chords(progression: str, track: str | None = None, bar: float = 1, style: str = "block", octave: int = 4,
               bars: float | None = None, beats_per_chord: float | None = None, velocity: int = 90,
               spread: bool = False, sound: str | None = None, name: str | None = None,
               project: str | None = None) -> dict:
    """Chords from a progression: "Am F C G" (one per bar), "Am:2 F:2" (beats), "| Am | F | C G |",
    roman numerals in the song key "vi IV I V" / "ii7 V7 Imaj7" / "i bVI bIII bVII". Voice-led like a
    keyboard player. style: block, pad, half, quarter, eighths, offbeat, syncopated, ballad, strum, stabs.
    bars repeats the progression to fill them. track omitted = a new "Chords" track (sound = preset)."""
    return _store(project).add_chords(progression, track, bar, style, octave, bars, beats_per_chord, velocity,
                                      spread, sound, name)


@_strumento()
def add_bassline(progression: str, track: str | None = None, bar: float = 1, style: str = "root", octave: int = 2,
                 bars: float | None = None, beats_per_chord: float | None = None, velocity: int = 100,
                 sound: str | None = None, name: str | None = None, project: str | None = None) -> dict:
    """A bass line following the chord roots. style: root, pulse, quarter, octave, walking, syncopated, 808,
    offbeat, arp. track omitted = a new "Bass" track."""
    return _store(project).add_bassline(progression, track, bar, style, octave, bars, beats_per_chord, velocity,
                                        sound, name)


@_strumento()
def add_arpeggio(progression: str, track: str | None = None, bar: float = 1, pattern: str = "up", rate: float = 0.25,
                 octaves: int = 1, octave: int = 4, bars: float | None = None, beats_per_chord: float | None = None,
                 velocity: int = 85, gate: float = 0.8, sound: str | None = None, name: str | None = None,
                 project: str | None = None) -> dict:
    """Arpeggiate the chords. pattern: up, down, updown, random, chord_tones_octave, alberti; rate in beats
    (0.25 = 16ths); gate = note length fraction. track omitted = a new "Arp" track."""
    return _store(project).add_arpeggio(progression, track, bar, pattern, rate, octaves, octave, bars,
                                        beats_per_chord, velocity, gate, sound, name)


@_strumento()
def add_melody(melody: str, track: str | None = None, bar: float = 1, sound: str | None = None,
               name: str | None = None, bars: float | None = None, project: str | None = None) -> dict:
    """A melody in text: "E5:1 D5:0.5 C5:0.5 A4:2 r:1 ..." = note:beats, r = rest, [C4 E4 G4]:2 = chord,
    ! accent, ? soft, ~ tie to the next equal note. Durations carry over when omitted. track omitted = a
    new "Lead" track."""
    return _store(project).add_melody(melody, track, bar, sound, name, bars)


@_strumento()
def add_drums(genre: str = "pop", track: str | None = None, bar: float = 1, bars: float = 4,
              intensity: str = "normal", fill_every: int = 0, swing: float | None = None, humanize: float = 0.2,
              crash: bool | None = None, velocity: int = 105, sound: str | None = None, name: str | None = None,
              loop: bool = False, seed: int = 0, project: str | None = None) -> dict:
    """A drum pattern: pop, rock, house, techno, trap, hiphop, lofi, reggaeton, dnb, funk, disco, afrobeats,
    ballad, halftime. intensity sparse | normal | busy; fill_every=4 puts a fill at the end of every 4th
    bar; crash on the first beat; swing (default per genre). track omitted = a new "Drums" track with a
    kit suited to the genre. GM notes: kick 36, snare 38, clap 39, closed hat 42, open hat 46, crash 49."""
    return _store(project).add_drums(genre, track, bar, bars, intensity, fill_every, swing, humanize, crash, seed,
                                     velocity, sound, name, loop)


# --------------------------------------------------------------------------
# sezioni e testo
# --------------------------------------------------------------------------


@_strumento()
def structure(sections: list[dict], start_bar: float = 1, replace: bool = True, project: str | None = None) -> dict:
    """Lay out the whole song form at once: [{"name": "intro", "bars": 4}, {"name": "verse", "bars": 8,
    "lyrics": "..."}, {"name": "chorus", "bars": 8}, ...], back to back from start_bar."""
    return _store(project).structure(sections, start_bar, replace)


@_strumento()
def add_section(name: str, bar: float, bars: float, lyrics: str = "", project: str | None = None) -> dict:
    """A section marker (intro, verse, pre-chorus, chorus, bridge, drop, outro...) with optional lyrics."""
    return _store(project).add_section(name, bar, bars, lyrics)


@_strumento()
def set_section(section: str, name: str | None = None, bar: float | None = None, bars: float | None = None,
                lyrics: str | None = None, project: str | None = None) -> dict:
    """Rename, move, resize a section or write its lyrics (one line per phrase)."""
    return _store(project).set_section(section, name, bar, bars, lyrics)


@_strumento()
def remove_section(section: str, project: str | None = None) -> dict:
    """Delete a section marker (the clips stay)."""
    return _store(project).remove_section(section)


# --------------------------------------------------------------------------
# effetti e automazione
# --------------------------------------------------------------------------


@_strumento()
def list_effects(name: str | None = None) -> list | dict:
    """Effects with their parameters (ranges, defaults) and which ones can be automated."""
    tutti = fx.describe()
    if name:
        for e in tutti:
            if e["name"] == name:
                return e
        raise EditError(f"unknown effect {name!r}; available: {', '.join(fx.REGISTRY)}")
    return [{"name": e["name"], "group": e["group"], "desc": e["desc"], "params": list(e["params"])} for e in tutti]


@_strumento()
def add_effect(target: str, type: str, params: dict | None = None, index: int | None = None,
               project: str | None = None) -> dict:
    """Insert an effect on a track (or target="master") at the end of its chain (or at index). Chain order
    matters: eq -> compressor -> saturation -> modulation -> delay/reverb. type: see list_effects."""
    return _store(project).add_effect(target, type, params, index)


@_strumento()
def update_effect(target: str, index: int, params: dict | None = None, enabled: bool | None = None,
                  project: str | None = None) -> dict:
    """Change parameters of an effect (merged) or switch it on/off (enabled)."""
    return _store(project).update_effect(target, index, params, enabled)


@_strumento()
def remove_effect(target: str, index: int, project: str | None = None) -> dict:
    """Remove an effect from a chain."""
    return _store(project).remove_effect(target, index)


@_strumento()
def move_effect(target: str, index: int, to: int, project: str | None = None) -> dict:
    """Reorder a chain."""
    return _store(project).move_effect(target, index, to)


@_strumento()
def list_chains() -> list:
    """Ready effect chains (vocal, bass, drum bus, pad space, lofi, radio, slapback, reverb/delay buses,
    master streaming, master loud) and the user's own."""
    return presets.describe_chains()


@_strumento()
def apply_chain(target: str, name: str, replace: bool = False, project: str | None = None) -> dict:
    """Append a ready chain to a track or the master (replace=true clears the chain first)."""
    return _store(project).apply_chain(target, name, replace)


@_strumento()
def save_chain(name: str, target: str, desc: str = "", project: str | None = None) -> dict:
    """Save the effect chain of a track (or master) as a chain of the user, usable in every song."""
    return _store(project).save_chain(name, target, desc)


@_strumento()
def delete_preset(name: str) -> dict:
    """Delete a sound or chain the user saved."""
    try:
        return presets.delete_user(name)
    except ValueError as exc:
        raise EditError(str(exc)) from exc


@_strumento()
def set_automation(track: str, target: str, points: list, project: str | None = None) -> dict:
    """An automation curve: points [[bar, value], ...], linear in between. target: volume (dB), pan
    (-1..1), or fx.<index>.<param> for an automatable effect parameter (e.g. fx.0.cutoff for a filter
    sweep, fx.2.mix for more reverb in the chorus). Replaces the curve of that target."""
    return _store(project).set_automation(track, target, points)


@_strumento()
def clear_automation(track: str, target: str | None = None, project: str | None = None) -> dict:
    """Remove the automation of a target (or all of the track)."""
    return _store(project).clear_automation(track, target)


@_strumento()
def set_master(volume_db: float | None = None, project: str | None = None) -> dict:
    """Master volume (the master effects are edited with add_effect target="master")."""
    return _store(project).set_master(volume_db)


# --------------------------------------------------------------------------
# guardare e misurare
# --------------------------------------------------------------------------


@_strumento()
async def preview(view: str = "arrangement", clip: str | None = None, track: str | None = None,
                  bars: list[float] | None = None, width: int = 1400, project: str | None = None) -> list:
    """LOOK at the song. view: arrangement (tracks x bars, sections, clips with mini notes/waveforms),
    piano_roll (notes of clip= or track=, scale rows highlighted), mix (master waveform + spectrogram).
    bars=[first, last] zooms."""
    s = _store(project)
    width = int(max(400, min(2400, width)))

    def fai():
        p = s.project
        if view == "arrangement":
            return visual.arrangement(p, width, bars, s.base_dir), {"bars": round(p.end_beat() / p.beats_per_bar, 2)}
        if view == "piano_roll":
            if not clip and not track:
                raise EditError("piano_roll needs clip= or track=")
            return visual.piano_roll(p, track, clip, width, bars), (s.get_notes(clip) if clip else {})
        if view == "mix":
            x = s.render(*(bars or [None, None])[:2]) if bars else s.render()
            st = analyze_mod.stats(x, p.sample_rate, detail=False)
            return visual.mix_view(p, x, width), st
        raise EditError("view must be arrangement, piano_roll or mix")

    img, info = await _off(fai)
    if view == "piano_roll" and clip and len(info.get("notes", [])) > 64:
        info = {**info, "notes": info["notes"][:64], "more": len(info["notes"]) - 64}
    return [_png(img), _json(info)]


@_strumento()
async def analyze_mix(track: str | None = None, start_bar: float | None = None, end_bar: float | None = None,
                      project: str | None = None) -> dict:
    """MEASURE the mix (or one track, post-fader): integrated LUFS, true peak, peak, RMS, crest, loudness
    range, energy per band (sub, bass, low_mid, mid, high_mid, air in dB vs total), stereo correlation."""
    return await _off(_store(project).analyze, track, start_bar, end_bar)


@_strumento()
async def analyze_audio(path: str | None = None, asset: str | None = None, project: str | None = None) -> dict:
    """BPM, key and loudness of an audio file (or an asset of the song): to match a sample or a beat."""
    def fai():
        if asset:
            s = _store(project)
            a = s.project.asset(asset)
            from .render import resolve

            f = resolve(a.path, s.base_dir)
        elif path:
            f = Path(path)
        else:
            raise EditError("pass path= or asset=")
        x = audio_io.load(f, 22050)
        return {"file": str(f), **analyze_mod.detect_tempo(x, 22050), "key": analyze_mod.detect_key(x, 22050),
                **analyze_mod.stats(x, 22050, detail=False)}
    try:
        return await _off(fai)
    except audio_io.AudioError as exc:
        raise EditError(str(exc)) from exc


@_strumento()
async def review_song(target_lufs: float = -14.0, project: str | None = None) -> dict:
    """CHECK before saying done: empty or overlapping clips, notes out of key, bass too high, clipping,
    loudness far from target, muddy/harsh/thin/boomy balance, phase problems, tracks too hot, empty
    sections, missing files. Each warning names the tool that fixes it."""
    w = await _off(_store(project).review, target_lufs)
    return {"ok": not w, "warnings": w}


@_strumento()
async def balance_mix(target_lufs: float = -20.0, project: str | None = None) -> dict:
    """Gain staging: set each track volume to a typical loudness for its role (drums loudest, pads
    lowest). A starting point; then adjust by taste."""
    return await _off(_store(project).balance_mix, target_lufs)


@_strumento()
async def auto_master(target_lufs: float = -14.0, style: str = "streaming", ceiling_db: float = -1.0,
                      project: str | None = None) -> dict:
    """Master the song to a loudness: adds the master chain if there is no limiter (style streaming or
    loud) and finds the limiter gain by measuring. -14 LUFS streaming, -9 club; ceiling -1 dBTP."""
    return await _off(_store(project).auto_master, target_lufs, style, ceiling_db)


# --------------------------------------------------------------------------
# IA generativa
# --------------------------------------------------------------------------


@_strumento()
async def ai_status() -> dict:
    """What AI is available HERE: song generation (ComfyUI ACE-Step or a cloud service), sound/loop
    generation (Stable Audio or cloud), stem separation (Demucs), the user's voice models (Applio),
    audio-to-MIDI (always). Each missing piece says exactly what to install or download."""
    return await _off(ai.status)


@_strumento()
def ai_services(service: str | None = None, model: str | None = None, default: bool | None = None) -> dict:
    """Online music services (ElevenLabs Music, Replicate) and which is the default for backend="auto".
    API keys are NOT set here: the user adds them in the editor (AI services) or with
    `medit key <service> <key>`; they stay on their computer. model = Replicate model (owner/name)."""
    if service is None:
        return cloud.stato()
    try:
        return cloud.imposta(service, None, model, None, default)
    except cloud.CloudError as exc:
        raise EditError(str(exc)) from exc


@_strumento()
def comfy_settings(url: str | None = None, song_checkpoint: str | None = None,
                   audio_checkpoint: str | None = None) -> dict:
    """ComfyUI address and which checkpoints to use for songs (ACE-Step) and sounds (Stable Audio).
    Empty string = back to automatic."""
    cfg = comfy.set_config(url=url, song_checkpoint=song_checkpoint, audio_checkpoint=audio_checkpoint)
    return {k: cfg.get(k) for k in ("url", "song_checkpoint", "audio_checkpoint")}


@_strumento()
def voice_models(applio_path: str | None = None) -> dict:
    """The user's voice models in Applio (RVC), for convert_voice. applio_path tells medit where Applio is."""
    if applio_path:
        try:
            return voce.imposta(applio_path)
        except voce.VoceError as exc:
            raise EditError(str(exc)) from exc
    return voce.stato()


@_strumento()
async def generate_song(prompt: str, lyrics: str | None = None, seconds: float | None = None, bar: float = 1,
                        instrumental: bool = False, backend: str = "auto", seed: int = -1, language: str = "en",
                        name: str | None = None, track: str | None = None, project: str | None = None) -> dict:
    """Generate a whole song as audio (with sung vocals) on a new audio track. prompt = style tags: genre,
    mood, instruments, voice ("melancholic indie pop, female breathy vocal, acoustic guitar, 90 BPM").
    lyrics with section tags "[Verse]\n...\n\n[Chorus]\n..."; omitted = the lyrics of the song's sections.
    seconds omitted = the length of the song form. Tempo and key come from the song. backend: auto,
    comfyui (local ACE-Step 1.5), elevenlabs. Takes minutes on a small GPU."""
    return await _off(_store(project).generate_song, prompt, lyrics, seconds, bar, instrumental, backend, seed,
                      language, name, track)


@_strumento()
async def generate_audio(prompt: str, bars: float | None = None, seconds: float | None = None, bar: float = 1,
                         track: str | None = None, backend: str = "auto", seed: int = -1, name: str | None = None,
                         project: str | None = None) -> dict:
    """Generate a sound from a description onto an audio track: a drum loop, a texture, an instrument
    phrase, a riser, an effect. bars = exact length in bars at the song tempo (the tempo goes in the
    prompt). backend: auto, comfyui (Stable Audio Open, up to 47 s), elevenlabs, replicate."""
    return await _off(_store(project).generate_audio, prompt, bars, seconds, bar, track, backend, seed, name)


@_strumento()
async def separate_stems(clip: str, engine: str = "auto", model: str | None = None, two_stems: bool = False,
                         project: str | None = None) -> dict:
    """Split an audio clip into stems, one new track each at the same position; the original is muted, not
    deleted. engine uvr = Ultimate Vocal Remover models (the user's UVR models: vocals/instrumental with
    MDX-Net or Roformer, noise or reverb removal with VR models; see stem_models), demucs = vocals, drums,
    bass, other (two_stems=true: vocals + instrumental). auto prefers UVR."""
    return await _off(_store(project).separate_stems, clip, two_stems, model, engine)


@_strumento()
def stem_models() -> dict:
    """Stem separators available and the Ultimate Vocal Remover models on disk (name, architecture, use:
    vocals/instrumental, noise removal, reverb removal...). A model not on disk can still be named: it is
    downloaded on first use."""
    from . import separa as _separa
    from . import uvr as _uvr

    return {"uvr": {**_uvr.stato(), "models": _uvr.modelli(), "default": _uvr.scegli(None)[0]},
            "demucs": _separa.stato()}


@_strumento()
async def audio_to_midi(clip: str, mode: str = "melody", sound: str | None = None, grid: float = 0.25,
                        name: str | None = None, project: str | None = None) -> dict:
    """Turn an audio clip into MIDI notes on a new track: mode melody (one line at a time: singing,
    humming, whistling, a bass, a solo; separate_stems first for a full mix) or drums (beatbox ->
    kick/snare/hat). grid quantizes in beats (0 = off). Then edit the notes or change the sound."""
    return await _off(_store(project).audio_to_midi, clip, mode, sound, grid, name)


@_strumento()
async def convert_voice(clip: str, model: str, pitch: int = 0, f0_method: str = "rmvpe", index_rate: float = 0.5,
                        protect: float = 0.33, autotune: bool = False, autotune_strength: float = 1.0,
                        clean: bool = False, clean_strength: float = 0.7, split_audio: bool = False,
                        formant_shift: float = 0.0, volume_envelope: float = 1.0, embedder: str = "contentvec",
                        project: str | None = None) -> dict:
    """Re-sing a vocal clip with one of the user's voice models (Applio RVC, see voice_models): e.g. turn
    a generated vocal into the user's own voice. Works best on an isolated vocal (separate_stems first).
    pitch in semitones (-12 female -> male, +12 male -> female). Applio options: f0_method (rmvpe default,
    crepe smoother), index_rate (0-1, more = closer to the model's accent), protect (consonants/breaths),
    autotune (+strength), clean (noise reduction), split_audio (long files), formant_shift in semitones
    (timbre younger/older without changing notes), volume_envelope, embedder. New track; original muted."""
    return await _off(_store(project).convert_voice, clip, model, pitch, f0_method, index_rate, protect, autotune,
                      autotune_strength, clean, clean_strength, split_audio, formant_shift, volume_envelope, embedder)


@_strumento()
async def voice_cover(clip: str, model: str, pitch: int = 0, uvr_model: str | None = None, engine: str = "auto",
                      f0_method: str = "rmvpe", index_rate: float = 0.5, protect: float = 0.33,
                      autotune: bool = False, clean: bool = False, formant_shift: float = 0.0,
                      project: str | None = None) -> dict:
    """A song sung with the user's voice, in one step: separate vocals and instrumental (UVR or Demucs), re-sing
    the vocal with an Applio model, keep it on the instrumental. Every intermediate track stays (original,
    stems, new voice) so each step can be changed; two undo steps."""
    return await _off(_store(project).voice_cover, clip, model, pitch, uvr_model, engine, f0_method=f0_method,
                      index_rate=index_rate, protect=protect, autotune=autotune, clean=clean,
                      formant_shift=formant_shift)


@_strumento()
def applio_ui(action: str = "status") -> dict:
    """Applio's own interface (training new voice models, TTS, everything) started by medit and shown inside
    the editor. action: start | stop | status. Starting takes 20-60 s."""
    try:
        if action == "start":
            return voce.ui_avvia()
        if action == "stop":
            return voce.ui_ferma()
    except voce.VoceError as exc:
        raise EditError(str(exc)) from exc
    return voce.ui_stato()


# --------------------------------------------------------------------------
# import / export
# --------------------------------------------------------------------------


async def _conferma(s: Store, path: str) -> bool:
    api = sys.modules.get("medit.api")
    if api is not None and api.S.store is s and (api.MCP_ATTIVO or api.background_info()):
        return await anyio.to_thread.run_sync(api.conferma_export, path)
    return True


@_strumento()
async def export_audio(path: str, start_bar: float | None = None, end_bar: float | None = None, bit_depth: int = 24,
                       quality: float = 0.9, sample_rate: int | None = None, project: str | None = None) -> dict:
    """Write the song to an audio file (.wav .flac .mp3 .ogg .aiff .m4a). ONLY when the user asks.
    start_bar/end_bar export a part."""
    s = _store(project)
    if not await _conferma(s, path):
        return {"exported": False, "reason": "the user did not confirm the export"}
    return await _off(s.export_audio, path, start_bar, end_bar, bit_depth, quality, sample_rate)


@_strumento()
async def export_stems(folder: str, format: str = "wav", bit_depth: int = 24, project: str | None = None) -> dict:
    """One audio file per track (post-fader, no master), all the same length. ONLY when the user asks."""
    s = _store(project)
    if not await _conferma(s, folder):
        return {"exported": False, "reason": "the user did not confirm the export"}
    return await _off(s.export_stems, folder, format, bit_depth)


@_strumento()
async def export_midi(path: str, tracks: list[str] | None = None, project: str | None = None) -> dict:
    """Write the MIDI tracks to a standard .mid file. ONLY when the user asks."""
    s = _store(project)
    if not await _conferma(s, path):
        return {"exported": False, "reason": "the user did not confirm the export"}
    return s.export_midi(path, tracks)


@_strumento()
def import_midi(path: str, bar: float = 1, adopt_tempo: bool = False, project: str | None = None) -> dict:
    """Import a .mid file: one track per instrument (channel 10 = drums), built-in sounds chosen from the
    General MIDI program. adopt_tempo=true takes its BPM and time signature."""
    return _store(project).import_midi(path, bar, adopt_tempo)


@_strumento()
async def import_audio(path: str, project: str | None = None) -> dict:
    """Add an audio file to the song's files without placing it (BPM/key measured). Place it with add_audio(asset=)."""
    return await _off(_store(project).import_audio, path)


# --------------------------------------------------------------------------
# batch, interfaccia, segnalazioni
# --------------------------------------------------------------------------


@_strumento()
async def batch(ops: list[dict], look: bool = False, project: str | None = None) -> list | dict:
    """Many edits in ONE call and ONE undo step, all or nothing:
    [{"tool": "add_chords", "args": {...}}, {"tool": "set_track", "args": {...}}, ...].
    look=true also returns the arrangement image."""
    s = _store(project)
    risultati = []
    with s.batch():
        for i, op in enumerate(ops):
            nome = op.get("tool")
            if nome in _FUORI_BATCH or nome not in STRUMENTI:
                raise EditError(f"step {i}: {nome!r} cannot be used in batch")
            fn = STRUMENTI[nome]
            args = dict(op.get("args") or {})
            args.pop("project", None)
            try:
                if inspect.iscoroutinefunction(fn):
                    res = await fn(**args)
                else:
                    res = fn(**args)
            except TypeError as exc:
                raise EditError(f"step {i} ({nome}): {exc}") from exc
            except _PREVISTI as exc:
                raise EditError(f"step {i} ({nome}): {_messaggio(exc)}") from exc
            risultati.append(res)
    out = {"done": len(risultati), "results": risultati}
    if look:
        img = await preview(project=project)
        return [img[0], _json(out)]
    return out


@_strumento()
def open_ui(port: int = 8780, project: str | None = None) -> dict:
    """Open the web editor on THIS song (same in-memory song, live updates, with play)."""
    from . import api

    s = _store(project)
    url = api.serve_background(s, port=port)
    return {"url": url}


@_strumento()
def close_ui() -> dict:
    """Stop the web editor started with open_ui."""
    from . import api

    return {"stopped": api.stop_background()}


@_strumento()
def report_issue(kind: str, title: str, details: str = "", tool: str = "") -> dict:
    """Log what is broken/clumsy/missing (kind: bug, scomodo, sbagliato, manca, lento), then go on."""
    return segnalazioni.aggiungi(kind, title, details, tool)


# --------------------------------------------------------------------------
# versioni
# --------------------------------------------------------------------------


@_strumento()
def snapshot(name: str, note: str = "", project: str | None = None) -> dict:
    """Save a named version of the song without changing it: before trying another direction."""
    return _store(project).snapshot(name, note)


@_strumento()
def snapshots(project: str | None = None) -> list:
    """Saved versions, newest first."""
    return _store(project).snapshots()


@_strumento()
def restore_snapshot(name: str, project: str | None = None) -> dict:
    """Bring the song back to a saved version (undo reverts it)."""
    return _store(project).restore_snapshot(name)


@_strumento()
def delete_snapshot(name: str, project: str | None = None) -> dict:
    """Delete a saved version."""
    return _store(project).delete_snapshot(name)


@_strumento()
async def compare_versions(a: str, b: str | None = None, project: str | None = None) -> dict:
    """What changes between two versions (b omitted = the current song): tempo/key, tracks added,
    removed, changed (with note counts), sections, loudness."""
    return await _off(_store(project).compare_versions, a, b)


# --------------------------------------------------------------------------
# l'utente: domande e memoria
# --------------------------------------------------------------------------


@_strumento()
async def ask_user(domande: list[dict]) -> dict:
    """Ask the user 1-4 questions with clickable options, in the editor, and wait for the answer.
    Each: {"domanda": "...", "titolo": "short", "opzioni": [{"etichetta": "...", "descrizione":
    "..."}, ...], "multipla": false}. 2-6 options, recommended first; the user can always type
    another answer. For choices that are theirs: genre, key, tempo, structure, sound, which version.
    Needs the editor open (open_ui or medit ui); otherwise ask in the conversation."""
    api = sys.modules.get("medit.api")
    if api is None or not api.S.listeners:
        return {"error": "no editor open: ask the question in the conversation"}
    norm = domande_mod.valida(domande)
    return await _off(api.chiedi, norm)


@_strumento()
def remember(note: str, section: str = "general") -> dict:
    """Save to the memory shared by ALL songs (MEMORIA.md) a preference of the user: usual tempos and
    genres, favourite sounds and chains, master loudness, where exports go, things to avoid. One short,
    concrete line. section groups: preferences, sounds, mix, genres..."""
    return memoria.ricorda(note, section)


@_strumento()
def forget(match: str) -> dict:
    """Remove from the shared memory the entries containing ``match``."""
    return memoria.dimentica(match)


@_strumento()
def memory() -> dict:
    """The whole memory shared by all songs, and where its file is."""
    return {"file": str(memoria.percorso()), "testo": memoria.leggi()}


@_strumento()
async def system_info() -> dict:
    """medit version, optional parts, ffmpeg, where settings and memory live, and whether the web
    editor is open."""
    import importlib.util
    import platform

    api = sys.modules.get("medit.api")
    return {"medit": __version__, "python": platform.python_version(),
            "extras": {m: importlib.util.find_spec(m) is not None for m in ("anthropic", "demucs")},
            "ffmpeg": audio_io.ffmpeg(),
            "memory": str(memoria.percorso()),
            "ui": api.background_info() if api else None}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["mcp", "main", "STRUMENTI"]
