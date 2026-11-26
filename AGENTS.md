# Istruzioni per un agente su questa repo

Questo file e' il contratto per chi arriva qui con un agente di codice (Claude Code, Codex,
Cursor, Copilot…). Chi legge deve poter partire da una repo appena clonata e arrivare a un
editor funzionante senza fare domande. `CLAUDE.md` importa questo file.

medit e' il gemello per la musica di [vedit](https://github.com/metiutek/editorvideo-ai) e
[pedit](https://github.com/metiutek/editorimage-ai): stessa filosofia, stessa struttura.

---

## 0. Se devi solo *usarlo*

```bash
claude mcp add medit -- uvx medit-mcp
```

## 1. Installazione

```bash
python scripts/setup.py            # --venv, --no-frontend, --no-test, --rebuild, --reinstall, --json
```

Oppure a mano: `pip install -e ".[dev,chat]"` e `cd frontend && npm ci && npm run build`.

## 2. Verificare che funzioni davvero

```bash
medit doctor                        # numpy/scipy/soundfile/mido, MP3, ffmpeg, UI compilata
pytest                              # ~110 test, ~25 s, niente rete
cd frontend && npm run build && npm test
```

## 3. Come e' fatto

La canzone e' **JSON puro** (`model.py`), con il tempo in **beat** (semiminime). Il render
(`render.py`) e' una funzione pura della canzone piu' i file audio: play della UI, analisi
dell'agente ed export escono dallo stesso codice.

```
backend/medit/
  model.py       canzone: tracce (midi, audio, bus), clip, note, strumenti, effetti, automazioni, sezioni
  theory.py      note, scale, accordi, progressioni (anche gradi romani), voicing, generatori
                 (accordi, basso, arpeggi, batteria per genere), notazione melodica testuale
  synth.py       strumenti interni in numpy: synth sottrattivo PolyBLEP, FM, Karplus-Strong, batteria, sampler
  effects.py     registro effetti: parametri, validazione, funzioni; automatizzabili
  render.py      clip -> strumento -> effetti -> fader -> mandate/bus -> master; cache per traccia
  analyze.py     LUFS BS.1770, true peak, bande, stereo; BPM e tonalita' dei file; review della canzone
  visual.py      immagini per l'agente: arrangiamento, piano roll, forma d'onda + spettrogramma
  presets.py     suoni e catene pronti (livelli tarati in LUFS) + quelli dell'utente in ~/.medit/presets.json
  audio_io.py    leggere/scrivere audio (soundfile; ffmpeg per m4a/video)   midi_io.py  file .mid
  ai.py          cosa c'e' di IA e chi la fa (backend auto: ComfyUI, poi solo il servizio predefinito)
  comfy.py       ComfyUI: ACE-Step 1.5 (canzoni) e Stable Audio (suoni), workflow dai template ufficiali
  cloud.py       ElevenLabs Music, Replicate; chiavi in ~/.medit/ai_api.json; HTTP solo da _http
  separa.py      stem con Demucs (processo a parte)
  uvr.py         modelli di Ultimate Vocal Remover via audio-separator, in ~/.medit/uvr-env creato
                 sopra l'ambiente di Applio (`medit uvr install`); modelli dalle cartelle di UVR installato
  voce.py        Applio/RVC da riga di comando (tutte le opzioni di infer) + la sua interfaccia avviata da medit
  trascrivi.py   audio -> note: YIN per le melodie, attacchi per banda per il beatbox
  store.py       tutte le modifiche + undo/redo + salvataggio atomico + versioni
  mcp_server.py  strumenti MCP          api.py  REST/WebSocket + /mcp per la UI
  chat.py llm.py estensioni.py memoria.py conversazioni.py domande.py segnalazioni.py   come in pedit
  cli.py         riga di comando
frontend/src/    React + Vite: Arrange (timeline), PianoRoll, Inspector, Compose, Mixer, Chat, player.js (WebAudio)
```

**Regola che tiene in piedi tutto: ogni modifica alla canzone passa da `Store`.** UI, assistente,
agente MCP e CLI chiamano gli stessi metodi. Mai scrivere nel documento da `api.py`,
`mcp_server.py` o `cli.py`.

Scelte non ovvie:

- **Battute 1-based fuori, beat 0-based dentro.** Gli strumenti parlano di `bar`/`bars`; le note
  stanno in beat relativi alla clip. La conversione e' solo in `Store` (`_beat`, `_bars`, `_bar`).
- **`_edit` e' rientrante**: un metodo che ne chiama altri (`add_bus` -> `add_track` +
  `apply_chain`) resta un solo passo di undo; se fallisce torna tutto com'era.
- **Cache per traccia** (`render.track_key`: JSON della traccia senza mute/solo/sends + tempo +
  file usati): mute, solo e modifiche ad altre tracce non ricalcolano niente.
- **Il rumore ha un seme** (per nota, per traccia): il render resta una funzione pura.
- **Limiter a picco vero**: rileva su segnale sovracampionato 4x, curva min+media sulla finestra
  di lookahead: niente overs anche dopo l'MP3.
- **Livelli dei suoni tarati** (`presets._CALIBRAZIONE`, rifatta con `scripts/calibra_suoni.py`):
  batteria -19 LUFS, bassi -21, lead -22, tastiere -23, pad -25.
- **Audio non nativo** (m4a, video): convertito una volta in WAV nella cartella degli asset.
- **IA lunga fuori dal lucchetto**: `generate_*`, `separate_stems`, `convert_voice` lavorano minuti
  senza bloccare; lo Store prende `self.lock` solo dentro `_edit` per scrivere il risultato. In
  `api.LUNGHE` e `chat.SENZA_LOCK`, e fuori da `batch`.
- **Nei test** ComfyUI e' su una porta chiusa, `MEDIT_APPLIO`/`MEDIT_DEMUCS_PYTHON` puntano al vuoto e
  `cloud._http` si sostituisce: mai la GPU, la rete o la voce vera di chi li lancia.

Quando modifichi:

- **nuovo effetto** → `effects.REGISTRY`. Il test parametrico lo esegue; un effetto di tono vuole un
  test di *direzione* in `tests/test_render.py`.
- **nuovo suono** → `presets.SOUNDS`, poi ritara i livelli.
- **nuovo strumento MCP** → metodo in `store.py`, wrapper in `mcp_server.py` (docstring utile: diventa
  la descrizione), nome in `api.OPS` se serve alla UI, test. La chat lo prende da sola.
- **cambio alla UI** → `cd frontend && npm run build`, altrimenti il server serve il `dist` vecchio.

## 4. Guidare l'editor da agente (MCP)

```
project_create(bpm, key, mode) -> structure -> add_drums / add_chords / add_bassline / add_arpeggio / add_melody
-> set_instrument / add_effect / apply_chain / add_bus + set_send -> preview + analyze_mix
-> review_song -> balance_mix / auto_master -> export_audio (solo se l'utente lo chiede)
```

- L'agente non sente: `preview` (arrangement, piano_roll, mix) e `analyze_mix` sono i suoi occhi.
- `batch` = lista di `{"tool", "args"}` in un blocco atomico con un undo.
- `medit ui` espone lo stesso server su `/mcp/` (porta 8780): chi si collega li' lavora sulla canzone
  aperta nel browser. `open_ui` fa il contrario.
- L'export con l'editor aperto chiede conferma nel browser.

Le regole di composizione e mix stanno in `mcp_server.ISTRUZIONI` e arrivano a qualunque client;
`tests/test_mcp.py` controlla che restino.

## 5. Convenzioni della repo

- Codice e commenti **in italiano**. Quello che legge chi usa l'editor e' **in inglese**.
  `README.md` in inglese, `README.it.md` in italiano: se cambi uno, allinea l'altro.
- Niente dipendenze nuove senza motivo. Core: numpy, scipy, soundfile, mido, Pillow, FastAPI, mcp.
  `tests/test_dipendenze.py` pretende che ogni import sia dichiarato.
- Ogni comportamento nuovo arriva con un test.
