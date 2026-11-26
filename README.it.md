<p align="center"><img src="frontend/public/logo.svg" alt="logo medit" width="96"/></p>

<h1 align="center">medit — editor musicale open source con IA, guidabile a parole (MCP)</h1>

<p align="center">
  <strong>Una DAW gratuita che un agente IA puo' usare al posto tuo.</strong><br/>
  Tracce, clip, piano roll, synth interni, tastiere FM, corde pizzicate e kit di batteria, effetti,
  bus, automazioni, mix e mastering a una loudness obiettivo — e un motore di teoria musicale che
  trasforma "una canzone lo-fi triste in La minore" in accordi, beat, bassi e melodie modificabili a mano.
</p>

> 🇬🇧 English: [README.md](README.md) · Progetti gemelli: [editorvideo-ai (vedit)](https://github.com/metiutek/editorvideo-ai),
> [editorimage-ai (pedit)](https://github.com/metiutek/editorimage-ai)

## Installazione

```bash
uv tool install medit-mcp
medit ui
```

L'editor si apre su <http://127.0.0.1:8780>. Per far scrivere musica a Claude Code:
`claude mcp add medit -- medit-mcp`. Qualcosa non va? `medit doctor`.

## Cos'e'

Una DAW normale — arrangiamento, piano roll, mixer, effetti — dove **tutto cio' che fai col mouse
lo puo' fare anche un'IA su comando**. I pulsanti, l'assistente integrato e qualunque agente MCP
chiamano le stesse operazioni. Niente e' solo-IA, niente e' solo-mouse, niente e' distruttivo: le
note restano note, gli effetti restano modificabili, l'audio importato non si riscrive mai, ogni
passo si annulla.

| | |
|---|---|
| **Scrive musica vera** | Accordi da sigle o gradi romani (`vi IV I V`, `ii7 V7 Imaj7`, `i bVI bIII bVII`) con condotta delle voci da tastierista; 10 stili di accordi, 9 di basso, arpeggi, 14 generi di batteria con fill e swing; melodie in notazione testuale (`E5:1 D5:0.5 r:1 [C4 E4 G4]:2`). |
| **Suona da sola** | 31 suoni interni — pianoforti, e-piano, pad, archi, supersaw, 808, reese, acid, chitarre, arpa, 5 kit — sintetizzati in numpy, livelli tarati in LUFS. Piu' un sampler per i tuoi file. |
| **L'agente non sente: guarda e misura** | `preview` restituisce arrangiamento, piano roll o spettrogramma come immagine; `analyze_mix` da' LUFS, true peak, bande e stereo; `review_song` segnala clipping, impasti, durezze, note fuori tonalita', basso nel registro sbagliato, sovrapposizioni — ognuno con lo strumento che lo sistema. |
| **Mixa e masterizza** | 21 effetti (EQ, compressore, limiter a picco vero, riverbero a convoluzione, delay a tempo, chorus, saturazione, lo-fi, pump…), bus e mandate, automazioni, `balance_mix`, `auto_master` a -14 LUFS / -1 dBTP. |
| **Lavora coi tuoi file** | Importa WAV, MP3, FLAC, OGG, AIFF (m4a e audio dei video con ffmpeg) con rilevamento di BPM e tonalita'; importa ed esporta MIDI; esporta mix e stem. |
| **Ti ricorda e ti chiede** | Memoria condivisa fra le canzoni, domande cliccabili nell'editor, versioni confrontabili, chat salvata accanto a ogni canzone. |

## Da agente (MCP)

```bash
claude mcp add --transport http medit-live http://127.0.0.1:8780/mcp/   # la canzone aperta nel browser
claude mcp add medit -- uvx medit-mcp                                      # stdio
```

## Sviluppo

Vedi [AGENTS.md](AGENTS.md). `pytest` (backend), `cd frontend && npm run build && npm test` (UI).

Licenza MIT.
