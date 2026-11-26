# Changelog

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
