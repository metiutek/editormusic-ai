<p align="center"><img src="https://raw.githubusercontent.com/metiutek/editormusic-ai/main/docs/logo.svg" alt="logo medit — editor musicale con IA" width="110"/></p>

<h1 align="center">medit — l'editor musicale (DAW) open source con IA, guidabile a parole</h1>

<p align="center">
  <strong>Chiedi a un'IA di scrivere la tua canzone e guardala lavorare in una DAW vera.</strong><br/>
  Accordi, beat, bassi, melodie, testi e voce — synth e kit di batteria interni, 31 effetti, mix e
  mastering a -14 LUFS. Funziona con <b>Claude Code, Cursor, Codex</b> e qualunque client MCP.
  Gratis, locale, MIT.
</p>

<p align="center">
  <a href="https://github.com/metiutek/editormusic-ai/actions/workflows/ci.yml"><img src="https://github.com/metiutek/editormusic-ai/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://pypi.org/project/medit-mcp/"><img src="https://img.shields.io/pypi/v/medit-mcp.svg?style=flat-square" alt="versione PyPI"/></a>
  <a href="https://pypi.org/project/medit-mcp/"><img src="https://img.shields.io/pypi/pyversions/medit-mcp.svg?style=flat-square" alt="versioni Python"/></a>
  <img src="https://img.shields.io/badge/strumenti%20MCP-95-blueviolet?style=flat-square" alt="95 strumenti MCP"/>
  <img src="https://img.shields.io/badge/gira-100%25%20in%20locale-brightgreen?style=flat-square" alt="Gira in locale"/>
  <a href="https://github.com/metiutek/editormusic-ai/blob/main/LICENSE"><img src="https://img.shields.io/badge/licenza-MIT-blue?style=flat-square" alt="licenza MIT"/></a>
  <a href="https://github.com/metiutek/editormusic-ai/stargazers"><img src="https://img.shields.io/github/stars/metiutek/editormusic-ai?style=flat-square" alt="stelle GitHub"/></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/metiutek/editormusic-ai/main/docs/medit-promo.gif" alt="demo di medit — un agente IA scrive accordi, batteria, basso e melodia nella DAW, poi mixa e masterizza" width="640"/>
</p>

<p align="center">
  <a href="https://metiutek.github.io/editormusic-ai/">Sito</a> ·
  <a href="#installazione--3-passi">Installazione</a> ·
  <a href="#collega-il-tuo-agente-ia-mcp">MCP</a> ·
  <a href="#cosa-puoi-chiedere">Esempi</a> ·
  <a href="#domande-frequenti">FAQ</a> ·
  <a href="https://github.com/metiutek/editormusic-ai/blob/main/README.md">🇬🇧 English</a>
</p>

## Perche' medit

Quasi tutti i tool di "musica con l'IA" ti danno un MP3 finito che non puoi toccare. Le DAW classiche
ti danno ogni manopola e nessun minuto indietro. **medit e' le due cose insieme**: una DAW normale —
arrangiamento, piano roll, mixer, effetti — dove **tutto cio' che fai col mouse lo puo' fare anche un
agente IA su comando**, perche' pulsanti, assistente integrato e agenti MCP chiamano le stesse operazioni.

- 🎹 **Scrive musica vera e modificabile** — le note restano note, gli accordi accordi, ogni passo si annulla con Ctrl+Z.
- 🧠 **Conosce la teoria musicale** — gradi romani, condotta delle voci, scale, 14 generi di batteria, 10 stili di accordi e 9 di basso.
- 👂 **L'agente "ascolta" misurando** — LUFS, true peak, spettro, immagini del piano roll e una revisione della canzone.
- 🎙️ **Registra e intona la tua voce** — registrazione dal microfono, Auto-Tune, catene voce, il tuo modello vocale RVC.
- 🤖 **IA generativa, locale o cloud** — canzoni intere cantate (ACE-Step), loop (Stable Audio), stem (UVR/Demucs).
- 🔒 **Gira sul tuo computer** — niente abbonamento, niente upload, niente watermark. Licenza MIT.

## Installazione — 3 passi

**1. Installa uv** (installa le app Python per te), poi chiudi e riapri il terminale.

| Windows (PowerShell) | macOS | Linux |
|---|---|---|
| `winget install astral-sh.uv` | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

**2. Installa medit**

```bash
uv tool install medit-mcp
```

**3. Apri l'editor**

```bash
medit ui
```

La DAW si apre nel browser su <http://127.0.0.1:8780>. Manca qualcosa? `medit doctor` dice cosa e come
sistemarlo. Aggiorna con `uv tool upgrade medit-mcp`. Preferisci pip? `pip install medit-mcp`.

## Collega il tuo agente IA (MCP)

**Claude Code**

```bash
claude mcp add medit -- uvx medit-mcp                                    # una canzone sua (stdio)
claude mcp add --transport http medit-live http://127.0.0.1:8780/mcp/    # la canzone aperta nel browser
```

**Claude Desktop, Cursor, Windsurf, VS Code, Codex** — aggiungi alla configurazione MCP del client
(`claude_desktop_config.json`, `.cursor/mcp.json`, …):

```json
{
  "mcpServers": {
    "medit": { "command": "uvx", "args": ["medit-mcp"] }
  }
}
```

Con `medit ui` aperto, punta il client a `http://127.0.0.1:8780/mcp/`: vedi l'agente lavorare sulla
timeline in tempo reale e puoi prendere il mouse in qualunque momento.

Funziona anche la scheda **Assistant** integrata: con Claude Code installato non c'e' niente da
configurare; altrimenti una chiave Anthropic, un endpoint compatibile OpenAI o un modello Ollama locale.

## Cosa puoi chiedere

> *"Scrivi una canzone lo-fi triste in La minore a 80 BPM: intro, strofa, ritornello. Batteria
> polverosa, accordi di Rhodes, una melodia morbida, poi masterizzala per Spotify."*

> *"Il ritornello deve essere piu' grande: raddoppia la melodia all'ottava, aggiungi un pad e apri la batteria."*

> *"Il basso impasta — sistemalo."* · *"Metti l'Auto-Tune sulla mia ripresa, naturale, nella tonalita' della canzone."*

> *"Separa la voce da questo MP3 e ricantala col mio modello vocale."*

Sotto, l'agente segue la strada di un produttore:

```
project_create(bpm, key) → structure → add_drums / add_chords / add_bassline / add_melody
  → set_instrument / add_effect / add_bus + set_send → preview + analyze_mix
  → review_song → balance_mix / auto_master → export_audio
```

## Funzioni

| | |
|---|---|
| **Motore di composizione** | Accordi da sigle o gradi romani (`vi IV I V`, `ii7 V7 Imaj7`, `i bVI bIII bVII`) con condotta delle voci da tastierista; 10 stili di accordi, 9 di basso, arpeggiatore, 14 generi di batteria con fill e swing; melodie in notazione testuale (`E5:1 D5:0.5 r:1 [C4 E4 G4]:2`); struttura della canzone con testo per sezione. |
| **Strumenti interni** | 31 suoni — pianoforte, e-piano, organo, pad, archi, supersaw, 808, reese, acid, chitarre, arpa, 5 kit — sintesi sottrattiva (PolyBLEP), FM e Karplus-Strong in numpy, livelli tarati in LUFS. Piu' un sampler per i tuoi file. |
| **Mix e mastering** | 31 effetti (Auto-Tune, pitch shift, EQ parametrico e grafico a 10 bande, compressore, multibanda, transient shaper, de-esser, limiter a picco vero, riverbero a convoluzione, delay a tempo, doubler, chorus, phaser, exciter, saturazione, lo-fi…), 22 catene pronte, bus e mandate, automazioni, `balance_mix`, `auto_master` a -14 LUFS / -1 dBTP. |
| **Analisi che l'agente legge** | `preview` restituisce arrangiamento, piano roll o spettrogramma come immagine; `analyze_mix` da' LUFS (BS.1770), true peak, bande e stereo; `review_song` segnala clipping, impasti, durezze, note fuori tonalita', basso nel registro sbagliato — ognuno con lo strumento che lo sistema. |
| **Registrazione voce** | Premi R: la canzone suona e il microfono registra dal cursore, latenza compensata, con metronomo, count-in e vista del testo. Un clic aggiunge Auto-Tune (naturale o robotico), una catena voce pop o un raddoppio. |
| **I tuoi file** | Importa WAV, MP3, FLAC, OGG, AIFF (m4a e video con ffmpeg) con rilevamento di BPM e tonalita'; importa/esporta MIDI; esporta mix e stem. |
| **IA generativa** | `generate_song` — canzone intera cantata da uno stile e dal tuo testo (ACE-Step 1.5 in ComfyUI, o ElevenLabs Music); `generate_audio` — loop ed effetti lunghi N battute (Stable Audio, Replicate); `separate_stems` — voce/batteria/basso con i tuoi modelli di **Ultimate Vocal Remover** o Demucs; `audio_to_midi` — canticchiato o beatbox in note; `convert_voice` / `voice_cover` — ricanta con **il tuo modello vocale** (Applio RVC). Tutto su tracce nuove. |
| **Memoria** | Preferenze condivise fra le canzoni, domande cliccabili nell'editor, versioni confrontabili, chat salvata accanto a ogni canzone. |

## Confronto

| | medit | Generatori di canzoni IA | DAW classiche |
|---|---|---|---|
| Risultato modificabile (note, tracce, effetti) | ✅ | ❌ un file audio | ✅ |
| Un agente IA fa il lavoro | ✅ 95 strumenti MCP | ✅ solo prompt | ❌ |
| Mix e master a una loudness obiettivo | ✅ automatico + manuale | ❌ | a mano |
| In locale, senza abbonamento | ✅ | ❌ | dipende |
| Open source | ✅ MIT | ❌ | raramente |

## Domande frequenti

**medit e' gratis?** Si'. Licenza MIT, niente account, niente watermark. I servizi cloud (ElevenLabs,
Replicate) sono opzionali e usano la tua chiave.

**Claude (o ChatGPT, Cursor, Codex) puo' fare musica con medit?** Si' — qualunque client che parla il
Model Context Protocol riceve 95 strumenti: comporre, arrangiare, mixare, masterizzare, analizzare, esportare.

**Serve una GPU?** No. DAW, synth, effetti e analisi girano sulla CPU in numpy. Solo i modelli
generativi opzionali (ACE-Step, Stable Audio, RVC, Demucs) vogliono una GPU.

**Posso usare i miei campioni e le mie registrazioni?** Si': trascina i file audio, usa il sampler o
registra dal microfono. L'audio importato non viene mai riscritto.

**Cosa esporta?** WAV, FLAC, MP3, OGG, MIDI e stem per traccia.

**Windows, macOS, Linux?** Tutti e tre; Python 3.10+.

## Progetti gemelli

Stessa filosofia, stesso modo di lavorare con l'agente:
[**vedit**](https://github.com/metiutek/editorvideo-ai) — editor video con IA ·
[**pedit**](https://github.com/metiutek/editorimage-ai) — editor immagini con IA.

## Contribuire

Issue e pull request benvenute — vedi [CONTRIBUTING.md](https://github.com/metiutek/editormusic-ai/blob/main/CONTRIBUTING.md)
e [AGENTS.md](https://github.com/metiutek/editormusic-ai/blob/main/AGENTS.md) (il contratto per persone e agenti di codice).
Test: `pytest` e `cd frontend && npm run build && npm test`.

Se medit ti e' utile, una ⭐ aiuta altri musicisti e sviluppatori a trovarlo.

[Licenza MIT](https://github.com/metiutek/editormusic-ai/blob/main/LICENSE).

<p align="center"><sub>Made by <a href="https://metiu.xyz"><b>metiu</b></a></sub></p>
