"""API REST/WebSocket per l'interfaccia web, piu' il server MCP su ``/mcp``.

Nessuna modifica alla canzone nasce qui: ``/api/op/{nome}`` chiama il metodo
omonimo di ``Store``, lo stesso che chiamano l'agente MCP e l'assistente.
Qui ci sono solo trasporto, l'audio renderizzato in cache per revisione (il
browser lo suona), la chat salvata accanto al documento e l'attesa delle
risposte dell'utente (ask_user, conferma dell'export).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, ai, audio_io, cloud, comfy, conversazioni, domande, estensioni, llm, memoria, presets, render, synth, theory
from . import chat as chat_mod
from . import effects as fx
from .model import AUDIO_EXTS, MEDIA_EXTS, MIDI_EXTS, Project
from .store import EditError, Store

PORTA = 8780


def _frontend_dir() -> Path:
    """UI compilata: dentro il pacchetto se installato da pip, altrimenti frontend/dist."""
    dentro = Path(__file__).resolve().parent / "webui"
    if (dentro / "index.html").is_file():
        return dentro
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


FRONTEND = _frontend_dir()

# operazioni di editing esposte alla UI (nomi dei metodi di Store)
OPS = {
    "set_song", "add_track", "set_track", "remove_track", "duplicate_track", "move_track", "set_instrument",
    "save_sound", "add_bus", "set_send",
    "add_clip", "add_audio", "import_audio", "set_clip", "split_clip", "duplicate_clip", "remove_clip",
    "copy_bars", "insert_bars", "delete_bars", "remove_asset",
    "add_notes", "set_notes", "remove_notes", "edit_notes", "transpose", "quantize", "humanize", "fit_to_scale",
    "add_chords", "add_bassline", "add_arpeggio", "add_melody", "add_drums",
    "add_section", "set_section", "remove_section", "structure",
    "add_effect", "update_effect", "remove_effect", "move_effect", "apply_chain", "save_chain", "set_master",
    "set_automation", "clear_automation", "balance_mix", "auto_master", "import_midi",
    "snapshot", "snapshots", "restore_snapshot", "delete_snapshot", "compare_versions",
    "get_notes", "undo", "redo",
} | {"generate_song", "generate_audio", "separate_stems", "audio_to_midi", "convert_voice"}

# lavorano minuti (ComfyUI, rete, Demucs, Applio): fuori dal lucchetto della UI, lo Store
# prende il suo solo per scrivere il risultato. Intanto l'editor resta usabile.
LUNGHE = {"generate_song", "generate_audio", "separate_stems", "audio_to_midi", "convert_voice", "auto_master",
          "balance_mix"}


class Session:
    """Canzone aperta + ascoltatori. Una sola sessione per processo."""

    def __init__(self) -> None:
        self.store: Store | None = None
        self.listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lock = threading.RLock()
        # un render alla volta: due play ravvicinati non fanno due mix in parallelo
        self.render_lock = threading.Lock()
        self.chat: dict = {}
        self.vista: list[dict] = []
        self.fermo = threading.Event()
        self.domanda: dict | None = None
        self.porta: int | None = None
        self.seq = 0
        self._rev: tuple | None = None
        self._cache: dict[tuple, bytes] = {}

    def need(self) -> Store:
        if self.store is None:
            raise HTTPException(400, "no song open")
        return self.store

    def publish(self, event: dict) -> None:
        if event.get("type") == "project":
            self.seq += 1
            event = {**event, "seq": self.seq}
        if self.loop is None:
            return
        for q in list(self.listeners):
            try:
                self.loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:
                return

    def revision(self) -> str:
        """Impronta del contenuto: uno stato e il suo undo ritrovano lo stesso audio."""
        st = self.store
        if st is None:
            return "0"
        r = self._rev
        if r and r[0] is st and r[1] is st.project and r[2] == st.version:
            return r[3]
        blob = json.dumps(st.project.to_dict(), sort_keys=True).encode()
        rev = hashlib.sha1(blob).hexdigest()[:16]
        self._rev = (st, st.project, st.version, rev)
        return rev

    def state(self) -> dict:
        st = self.store
        return {"project": st.summary("full") if st else None, "path": st.path if st else None,
                "revision": self.revision(), "seq": self.seq,
                "history": {"undo": len(st._undo), "redo": len(st._redo)} if st else None}

    def snapshot(self) -> tuple[Project, str | None]:
        """Copia della canzone da renderizzare fuori dal lock."""
        with self.lock:
            st = self.need()
            return Project.from_obj(st.project.to_dict()), st.base_dir

    def cached(self, key: tuple, make) -> bytes:
        if key in self._cache:
            return self._cache[key]
        data = make()
        # l'audio pesa: poche voci
        while len(self._cache) > 6:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = data
        return data


S = Session()


def attach(store: Store) -> None:
    """La UI lavora su questo Store (anche quello dell'agente MCP: open_ui)."""
    if S.store is not None and S.store is not store:
        S.store.on_change = None
    nuovo = S.store is not store
    S.store = store
    store.on_change = lambda: S.publish({"type": "project"})
    if nuovo:
        carica_chat()
    S.publish({"type": "project"})


# --------------------------------------------------------------------------
# server MCP montato su /mcp
# --------------------------------------------------------------------------


class _PonteMcp:
    def __init__(self) -> None:
        self.app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            await JSONResponse({"detail": "MCP server not running"}, status_code=503)(scope, receive, send)
            return
        await self.app(scope, receive, send)


_mcp = _PonteMcp()
MCP_ATTIVO = False


@asynccontextmanager
async def _vita(_app):
    global MCP_ATTIVO
    S.loop = asyncio.get_running_loop()
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        from . import mcp_server

        sub = mcp_server.mcp.streamable_http_app(
            streamable_http_path="/", stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    except Exception:  # noqa: BLE001 - senza MCP l'interfaccia funziona lo stesso
        sub = None
    if sub is None:
        yield
        return
    async with sub.router.lifespan_context(sub):
        _mcp.app = sub
        MCP_ATTIVO = True
        try:
            yield
        finally:
            MCP_ATTIVO = False
            _mcp.app = None


app = FastAPI(title="medit", lifespan=_vita)
app.mount("/mcp", _mcp)

_host_consentiti: set[str] = set()
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _nome_host(valore: str) -> str:
    valore = valore.strip().lower()
    if valore.startswith("["):
        return valore.split("]")[0] + "]"
    return valore.rsplit(":", 1)[0] if valore.count(":") == 1 else valore


@app.middleware("http")
async def _solo_locale(request: Request, call_next):
    """L'API legge e scrive file ovunque: niente DNS rebinding, niente richieste da altri siti."""
    if _host_consentiti:
        if _nome_host(request.headers.get("host", "")) not in _host_consentiti:
            return JSONResponse({"detail": "non-local request refused"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and _nome_host(origin.split("://", 1)[-1]) not in _host_consentiti:
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    return await call_next(request)


def mcp_url() -> str | None:
    if not MCP_ATTIVO or not S.porta:
        return None
    return f"http://127.0.0.1:{S.porta}/mcp/"


# --------------------------------------------------------------------------
# stato e canzone
# --------------------------------------------------------------------------


def _cartella_musica() -> str:
    home = Path.home()
    for nome in ("Music", "Musica", "Musique"):
        if (home / nome).is_dir():
            return str(home / nome)
    return str(home)


@app.get("/api/state")
def state() -> dict:
    return {
        **S.state(),
        "version": __version__,
        "home": _cartella_musica(),
        "effects": fx.describe(),
        "sounds": presets.describe_sounds(),
        "chains": presets.describe_chains(),
        "instruments": {k: {p: {"default": v, "desc": synth.PARAM_DOCS[k].get(p, "")} for p, v in d.items()}
                        for k, d in synth.DEFAULTS.items()},
        "theory": {"modes": list(theory.SCALES), "chord_styles": theory.CHORD_STYLES,
                   "bass_styles": theory.BASS_STYLES, "arp_patterns": list(theory.ARP_PATTERNS),
                   "drum_genres": {k: v["desc"] for k, v in theory.DRUM_PATTERNS.items()},
                   "progressions": theory.progressions_for()},
        "chat": llm.stato(),
        "ai": ai.status(check_comfy=False),
        "mcp": mcp_url(),
        "ffmpeg": bool(audio_io.ffmpeg()),
    }


@app.get("/api/project")
def project_state() -> dict:
    return S.state()


class CreateBody(BaseModel):
    name: str = "untitled"
    bpm: float = 120.0
    key: str = "C"
    mode: str = "major"
    time_sig: list[int] | None = None
    path: str | None = None
    from_audio: str | None = None


class PathBody(BaseModel):
    path: str | None = None


@app.post("/api/project/create")
def project_create(body: CreateBody) -> dict:
    try:
        attach(Store.create(**body.model_dump()))
    except (EditError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return S.state()


@app.post("/api/project/open")
def project_open(body: PathBody) -> dict:
    if not body.path:
        raise HTTPException(400, "path missing")
    try:
        attach(Store.open(body.path))
    except (EditError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return S.state()


@app.post("/api/project/save")
def project_save(body: PathBody) -> dict:
    st = S.need()
    try:
        with S.lock:
            path = st.save(body.path)
    except (EditError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    salva_chat()
    S.publish({"type": "project"})
    return {"path": path, **S.state()}


def _plain(x: Any) -> Any:
    try:
        json.dumps(x)
        return x
    except TypeError:
        return json.loads(json.dumps(x, default=lambda v: float(v) if isinstance(v, np.generic) else str(v)))


@app.post("/api/op/{name}")
def op(name: str, body: dict | None = None) -> dict:
    """Esegue un'operazione di Store e restituisce lo stato aggiornato."""
    if name not in OPS:
        raise HTTPException(404, f"unknown operation: {name}")
    st = S.need()
    try:
        if name in LUNGHE:
            result = getattr(st, name)(**dict(body or {}))
        else:
            with S.lock:
                result = getattr(st, name)(**dict(body or {}))
    except TypeError as exc:
        raise HTTPException(400, f"invalid arguments for {name}: {exc}") from exc
    except (EditError, ValueError, KeyError, FileNotFoundError) as exc:
        msg = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        raise HTTPException(400, msg) from exc
    return {"result": _plain(result), **S.state()}


# --------------------------------------------------------------------------
# audio per il browser
# --------------------------------------------------------------------------


@app.get("/api/audio")
def audio(rev: str = "", sr: int = 0) -> Response:
    """La canzone renderizzata (WAV 16 bit). In cache per revisione: un undo ritrova l'audio."""
    snap, base = S.snapshot()
    sr = int(sr) if sr in (22050, 32000, 44100, 48000) else snap.sample_rate
    key = ("mix", S.revision(), sr)

    def fai() -> bytes:
        with S.render_lock:
            x = render.render(snap, base, sr=sr)
            return audio_io.wav_bytes(x, sr)

    try:
        data = S.cached(key, fai)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(data, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.get("/api/note")
def note(track: str, pitch: int, velocity: int = 100, seconds: float = 0.5) -> Response:
    """Una nota sola sullo strumento della traccia: il tasto del piano roll suona."""
    snap, base = S.snapshot()
    try:
        t = snap.track(track)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    x = render.render_note(snap, t, int(np.clip(pitch, 0, 127)), int(np.clip(velocity, 1, 127)),
                           float(np.clip(seconds, 0.05, 4)), base)
    return Response(audio_io.wav_bytes(x, snap.sample_rate), media_type="audio/wav")


@app.get("/api/peaks/{asset_id}")
def peaks(asset_id: str, per_second: int = 100) -> dict:
    """Picchi del file (max assoluto per finestra), per disegnare la forma d'onda nelle clip."""
    snap, base = S.snapshot()
    try:
        a = snap.asset(asset_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    per_second = int(np.clip(per_second, 10, 400))
    key = ("peaks", asset_id, a.path, per_second)

    def fai() -> bytes:
        x = audio_io.load(render.resolve(a.path, base), 8000)
        m = np.abs(x).max(axis=0)
        passo = max(1, 8000 // per_second)
        n = len(m) // passo
        v = m[: n * passo].reshape(n, passo).max(axis=1) if n else np.zeros(0)
        return json.dumps({"per_second": 8000 / passo, "peaks": [round(float(p), 3) for p in v]}).encode()

    try:
        return json.loads(S.cached(key, fai))
    except audio_io.AudioError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/analyze")
def analyze_doc(track: str | None = None) -> dict:
    st = S.need()
    with S.render_lock:
        try:
            return st.analyze(track)
        except EditError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/review")
def review_doc() -> dict:
    st = S.need()
    with S.render_lock:
        w = st.review()
    return {"ok": not w, "warnings": w}


# --------------------------------------------------------------------------
# file: sfoglia, importa, carica, esporta
# --------------------------------------------------------------------------


@app.get("/api/browse")
def browse(path: str | None = None) -> dict:
    p = Path(path or _cartella_musica())
    if not p.is_dir():
        p = p.parent if p.parent.is_dir() else Path.home()
    voci = []
    try:
        for f in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if f.name.startswith("."):
                continue
            ext = f.suffix.lower()
            if f.is_dir():
                voci.append({"name": f.name, "path": str(f), "dir": True})
            elif ext in MEDIA_EXTS or ext in MIDI_EXTS or ext == ".json":
                kind = "doc" if ext == ".json" else "midi" if ext in MIDI_EXTS else "audio"
                voci.append({"name": f.name, "path": str(f), "dir": False, "kind": kind})
    except OSError as exc:
        raise HTTPException(400, str(exc)) from exc
    radici = [f"{d}:\\" for d in "CDEFGH" if os.name == "nt" and Path(f"{d}:\\").exists()] or ["/"]
    return {"path": str(p.resolve()), "parent": str(p.resolve().parent), "entries": voci, "roots": radici}


class ImportBody(BaseModel):
    paths: list[str]
    bar: float = 1
    track: str | None = None


@app.post("/api/import")
def importa(body: ImportBody) -> dict:
    st = S.need()
    try:
        with S.lock, st.batch():
            for path in body.paths:
                if Path(path).suffix.lower() in MIDI_EXTS:
                    st.import_midi(path, body.bar)
                else:
                    st.add_audio(path=path, bar=body.bar, track=body.track)
    except (EditError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return S.state()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), bar: str = Form("1"), track: str = Form("")) -> dict:
    """File trascinati nel browser: copiati nella cartella degli asset (il browser non da' il percorso)."""
    st = S.need()
    dest = st.assets_dir() / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    salvati = []
    for f in files:
        nome = Path(f.filename or "audio.wav").name
        if Path(nome).suffix.lower() not in AUDIO_EXTS | MIDI_EXTS | MEDIA_EXTS:
            continue
        target = dest / f"{uuid.uuid4().hex[:6]}_{nome}"
        with target.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        salvati.append(str(target))
    if not salvati:
        raise HTTPException(400, "no audio or MIDI files in the upload")
    return await asyncio.to_thread(importa, ImportBody(paths=salvati, bar=float(bar or 1), track=track or None))


class ExportBody(BaseModel):
    path: str
    kind: str = "audio"          # audio | stems | midi
    start_bar: float | None = None
    end_bar: float | None = None
    bit_depth: int = 24
    quality: float = 0.9
    format: str = "wav"


@app.post("/api/export")
def export(body: ExportBody) -> dict:
    st = S.need()
    try:
        with S.render_lock:
            if body.kind == "stems":
                return st.export_stems(body.path, body.format, body.bit_depth)
            if body.kind == "midi":
                return st.export_midi(body.path)
            return st.export_audio(body.path, body.start_bar, body.end_bar, body.bit_depth, body.quality)
    except (EditError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


# --------------------------------------------------------------------------
# domande all'utente (ask_user, conferma export)
# --------------------------------------------------------------------------


def chiedi(lista, timeout: float = 1800.0) -> dict:
    """Mostra le domande nel browser e aspetta la risposta (o "ferma")."""
    norm = domande.valida(lista)
    if not S.listeners:
        return {"annullata": True, "motivo": "no editor open"}
    if S.domanda is not None:
        return {"annullata": True, "motivo": "a question is already waiting for an answer"}
    qid = uuid.uuid4().hex[:10]
    evento = threading.Event()
    S.domanda = {"id": qid, "domande": norm, "evento": evento, "risposte": None}
    S.publish({"type": "domande", "id": qid, "domande": norm})
    scadenza = time.time() + timeout
    try:
        while not evento.wait(0.25):
            if S.fermo.is_set():
                return {"annullata": True, "motivo": "the user stopped the assistant"}
            if time.time() > scadenza:
                return {"annullata": True, "motivo": "no answer"}
        r = S.domanda["risposte"] or {}
        if r.get("__annulla__"):
            return {"annullata": True, "motivo": "the user closed the questions without answering"}
        return {"risposte": r}
    finally:
        S.domanda = None
        S.publish({"type": "domande_chiuse", "id": qid})


def conferma_export(path: str, timeout: float = 600) -> bool:
    """L'agente vuole scrivere un file: lo decide l'utente, nel browser."""
    if not S.listeners:
        return False
    return domande.approvato(chiedi(domande.conferma_export(path), timeout))


@app.get("/api/domanda")
def domanda_aperta() -> dict:
    d = S.domanda
    return {"domanda": {"id": d["id"], "domande": d["domande"]} if d else None}


class RispostaBody(BaseModel):
    risposte: dict


@app.post("/api/domanda/{qid}")
def domanda_rispondi(qid: str, body: RispostaBody) -> dict:
    d = S.domanda
    if d is None or d["id"] != qid:
        raise HTTPException(404, "no pending question with this id")
    d["risposte"] = body.risposte
    d["evento"].set()
    return {"ok": True}


# --------------------------------------------------------------------------
# assistente, preset, memoria
# --------------------------------------------------------------------------


@app.get("/api/ai")
def ai_stato() -> dict:
    return ai.status()


class ServizioBody(BaseModel):
    service: str
    key: str | None = None
    model: str | None = None
    default: bool | None = None


@app.post("/api/ai/services")
def ai_servizi(body: ServizioBody) -> dict:
    """Le chiavi dei servizi in rete arrivano solo da qui (o dalla CLI): mai dagli strumenti MCP."""
    try:
        return cloud.imposta(body.service, body.key, body.model, None, body.default)
    except cloud.CloudError as exc:
        raise HTTPException(400, str(exc)) from exc


class ComfyBody(BaseModel):
    url: str | None = None
    song_checkpoint: str | None = None
    audio_checkpoint: str | None = None


@app.post("/api/ai/comfy")
def ai_comfy(body: ComfyBody) -> dict:
    comfy.set_config(**body.model_dump())
    return ai.status()


@app.get("/api/llm")
def llm_stato() -> dict:
    return llm.stato()


class RapidoBody(BaseModel):
    modello: str | None = None
    sforzo: str | None = None


@app.post("/api/llm/rapido")
def llm_rapido(body: RapidoBody) -> dict:
    try:
        return llm.imposta_rapido(body.modello, body.sforzo)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


class LlmBody(BaseModel):
    provider: str
    key: str | None = None
    model: str | None = None
    url: str | None = None


@app.post("/api/llm")
def llm_imposta(body: LlmBody) -> dict:
    try:
        return llm.imposta(body.provider, body.key, body.model, body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class AccessoBody(BaseModel):
    accesso: str | None = None
    server_spenti: list[str] | None = None


@app.get("/api/estensioni")
def estensioni_stato() -> dict:
    return {**estensioni.stato(S.store.path if S.store else None), "accesso": llm.carica()["accesso"]}


@app.post("/api/estensioni")
def estensioni_imposta(body: AccessoBody) -> dict:
    try:
        llm.imposta_accesso(body.accesso, body.server_spenti)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return estensioni_stato()


@app.post("/api/estensioni/collega")
def estensioni_collega() -> dict:
    estensioni.GESTORE.collega(estensioni.server_attivi(S.store.path if S.store else None), riprova=True)
    return estensioni_stato()


class MemoriaBody(BaseModel):
    testo: str


@app.get("/api/memoria")
def memoria_leggi() -> dict:
    return {"file": str(memoria.percorso()), "testo": memoria.leggi()}


@app.put("/api/memoria")
def memoria_scrivi(body: MemoriaBody) -> dict:
    try:
        out = memoria.sostituisci(body.testo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**out, "testo": memoria.leggi()}


@app.get("/api/presets")
def presets_lista() -> dict:
    return {"sounds": presets.describe_sounds(), "chains": presets.describe_chains()}


@app.delete("/api/presets/{name}")
def preset_elimina(name: str) -> dict:
    try:
        presets.delete_user(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return presets_lista()


class ChatBody(BaseModel):
    question: str
    refs: list[dict] = []


def carica_chat() -> None:
    stato, vista = conversazioni.carica(S.store.path if S.store else None)
    S.chat.clear()
    S.chat.update(stato)
    S.vista = vista


def salva_chat() -> None:
    if S.store is None:
        return
    try:
        conversazioni.salva(S.store.path, S.chat, S.vista)
    except OSError:
        pass


def _in_vista(m: dict, ev: dict) -> None:
    t = ev.get("type")
    if t == "text":
        m["text"] += ev.get("text", "")
    elif t == "tool":
        corti = {k: v for k, v in (ev.get("input") or {}).items()
                 if len(json.dumps(v, ensure_ascii=False, default=str)) <= 300}
        m["tools"].append({"name": ev.get("name"), "state": "run", "input": corti})
    elif t in ("tool_done", "tool_error"):
        for x in reversed(m["tools"]):
            if x["name"] == ev.get("name") and x["state"] == "run":
                x["state"] = "ok" if t == "tool_done" else "err"
                if ev.get("message"):
                    x["message"] = ev["message"]
                break
    elif t == "error":
        m["error"] = ev.get("message")
    elif t == "stopped":
        for x in m["tools"]:
            if x["state"] == "run":
                x["state"] = "err"
        m["note"] = "Stopped. The changes already made stay: Ctrl+Z to undo them."


@app.get("/api/chat/storia")
def chat_storia() -> dict:
    return {"vista": S.vista}


@app.post("/api/chat")
def chat(body: ChatBody) -> StreamingResponse:
    """Un turno con l'assistente, in streaming (NDJSON)."""
    st = S.need()
    S.fermo.clear()

    def run_op(name: str, args: dict):
        if name in chat_mod.SENZA_LOCK or name.startswith("mcp__"):
            return chat_mod.execute(st, name, args)
        with S.lock:
            return chat_mod.execute(st, name, args)

    def flusso():
        precedente = conversazioni.testo(S.vista)
        S.vista.append({"role": "user", "text": body.question, "refs": body.refs})
        risposta: dict = {"role": "assistant", "text": "", "tools": []}
        S.vista.append(risposta)
        try:
            for ev in chat_mod.run(st, S.chat, body.question, body.refs, mcp_url(), S.fermo.is_set,
                                   run_op=run_op, precedente=precedente):
                _in_vista(risposta, ev)
                yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
        except Exception as exc:  # noqa: BLE001 - l'errore va nella chat, non nel log del server
            risposta["error"] = str(exc)
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
        finally:
            salva_chat()

    return StreamingResponse(flusso(), media_type="application/x-ndjson")


@app.post("/api/chat/stop")
def chat_stop() -> dict:
    S.fermo.set()
    return {"ok": True}


@app.post("/api/chat/reset")
def chat_reset() -> dict:
    S.chat.clear()
    S.vista = []
    salva_chat()
    return {"ok": True}


# --------------------------------------------------------------------------
# eventi
# --------------------------------------------------------------------------


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    if _host_consentiti and _nome_host(socket.headers.get("host", "")) not in _host_consentiti:
        await socket.close(code=1008)
        return
    await socket.accept()
    S.loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    S.listeners.add(q)
    try:
        while True:
            ev = await q.get()
            await socket.send_json(ev)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        S.listeners.discard(q)


# interfaccia compilata (montata per ultima: le rotte /api vincono)
if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")
else:
    @app.get("/")
    def _senza_ui() -> JSONResponse:
        return JSONResponse({"detail": "web UI not built: cd frontend && npm ci && npm run build"})


# --------------------------------------------------------------------------
# avvio
# --------------------------------------------------------------------------

_bg: dict[str, Any] = {}


def _consenti(host: str) -> None:
    _host_consentiti.update(_LOOPBACK)
    if host not in ("0.0.0.0", "::", ""):
        _host_consentiti.add(host)
    else:
        _host_consentiti.clear()


def serve(store: Store | None = None, host: str = "127.0.0.1", port: int = PORTA, browser: bool = True) -> None:
    import uvicorn

    if store is not None:
        attach(store)
    _consenti(host)
    S.porta = port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    if browser:
        threading.Timer(1.0, lambda: __import__("webbrowser").open(url)).start()
    print(f"medit {__version__} - {url}  (MCP: {url}/mcp/)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def background_info() -> dict | None:
    return _bg.get("info")


def serve_background(store: Store, port: int = PORTA) -> str:
    """Interfaccia nello stesso processo del server MCP: stesso Store, aggiornamenti dal vivo."""
    import uvicorn

    attach(store)
    if _bg.get("info"):
        return _bg["info"]["url"]
    _consenti("127.0.0.1")
    S.porta = port
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    _bg["info"] = {"url": url}
    _bg["server"] = server
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    return url


def stop_background() -> bool:
    server = _bg.pop("server", None)
    _bg.pop("info", None)
    if server is None:
        return False
    server.should_exit = True
    return True


__all__ = ["app", "serve", "attach", "S"]
