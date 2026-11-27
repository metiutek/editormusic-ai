# Changelog

## 0.4.0 — 2026-11-27

- **Pannello traccia** in basso (si apre selezionando traccia o clip): preset per famiglia, manopole
  rapide Reverb/Pan/Volume, rack di effetti a schede con libreria, schede Clip/Track/Sound/Master;
  Mixer e Master stanno li'. EQ parametrico/grafico con curva e spettro vero, compressore con curva di
  trasferimento, riduzione di guadagno nel tempo e meter IN/GR/OUT (`/api/fxview`, stesso codice del render).
- **Play a blocchi in tempo reale**: render a pezzi di 3 s dal cursore (`/api/chunk`, identico al render
  intero); le modifiche durante il play ricalcolano solo i pezzi avanti, con dissolvenza.
- Registrazione voce dal vivo: scelta ingresso, meter, ascolto in cuffia, calibrazione della latenza,
  arma (R), metronomo con count-in, vista del testo. Preset voce nuovi (natural, podcast, rap, trap,
  robot, dreamy, stadium).
- "Made by metiu" in fondo al pannello laterale, con link a metiu.xyz.
- README riscritto (installazione in 3 passi, configurazione dei client MCP, esempi, confronto, FAQ),
  sito su GitHub Pages (`docs/`), CONTRIBUTING, SECURITY, template di issue e PR, CITATION.cff.
- **Registrazione dal microfono**: R o il tasto rosso; la canzone suona, la ripresa (WAV float dal
  segnale grezzo, AudioWorklet) parte dal cursore con la latenza compensata e va sulla traccia audio
  scelta o su una nuova "Vocals"; se si sovrappone a una ripresa vecchia va su una traccia sotto.
  `POST /api/record`, un solo undo.
- **Auto-Tune** (`autotune`): YIN + TD-PSOLA, scala della canzone o scelta, velocita' di correzione
  (0 = robotico), humanize, formanti intatte. Pulsanti Auto-Tune / Hard tune / Pop vocal chain / Double
  nell'Inspector delle tracce audio; catene `vocal tuned`, `vocal hard tune`, `vocal pop`.
- Effetti nuovi: `pitch_shift` (phase vocoder, o PSOLA per la voce), `vibrato`, `doubler`, `phaser`,
  `ring_mod`, `exciter`, `graphic_eq` (10 bande), `transient`, `multiband`. Il menu effetti e'
  diviso per categoria.

## 0.3.0 — 2026-11-26

- Modelli di **Ultimate Vocal Remover** (MDX-Net, VR, MDX23C, Roformer): `separate_stems(engine="uvr")`
  usa quelli di UVR installato; `stem_models` li elenca; `medit uvr install` crea il runner sopra
  l'ambiente di Applio (riusa torch con CUDA, Applio non viene toccato).
- **Applio dentro medit**: `convert_voice` con tutte le opzioni (metodo f0, index, protect, autotune,
  riduzione rumore, formanti, split); `voice_cover` = UVR voce/base -> tua voce -> sulla base;
  `applio_ui` avvia l'interfaccia di Applio e la mostra in un riquadro dell'editor.
- **Pannelli ridimensionabili** (laterale, piano roll, nomi delle tracce; la misura resta) e **allegati in
  chat** (graffetta, trascina, incolla: audio, MIDI, testi letti dall'assistente, immagini).

## 0.2.0 — 2026-11-26

IA generativa, sempre non distruttiva (tracce nuove, originale solo silenziato):
- `generate_song`: canzone intera anche cantata da stile + testo (testi delle sezioni se omessi),
  con ACE-Step 1.5 in ComfyUI o ElevenLabs Music;
- `generate_audio`: loop, strumenti, effetti lunghi N battute (Stable Audio Open in ComfyUI,
  ElevenLabs, Replicate);
- `separate_stems` con Demucs (extra `stems`), `audio_to_midi` (melodia YIN e beatbox, numpy),
  `convert_voice` con i modelli RVC dell'utente in Applio;
- `ai_status`, `ai_services` (chiavi solo da UI/CLI), `comfy_settings`, `voice_models`; scheda AI
  nella UI; `medit key`, `medit ai`; le operazioni lunghe non bloccano l'editor.

## 0.1.0 — 2026-11-26

Prima versione: DAW con tracce MIDI/audio/bus, 5 motori di sintesi, 31 suoni, 21 effetti,
automazioni, teoria musicale e generatori, analisi LUFS/true peak, review, auto master,
import/export audio e MIDI, 83 strumenti MCP, UI React (arrangiamento, piano roll, mixer, chat).
