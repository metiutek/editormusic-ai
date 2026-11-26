<p align="center"><img src="frontend/public/logo.svg" alt="medit logo" width="96"/></p>

<h1 align="center">medit — open-source AI music editor you can drive with words (MCP)</h1>

<p align="center">
  <strong>A free DAW that an AI agent can use for you.</strong><br/>
  Tracks, clips, piano roll, built-in synths, FM keys, plucked strings and drum kits, effects,
  buses, automation, mixing and mastering to a loudness target — and a music-theory engine that
  turns "a sad lo-fi song in A minor" into chords, beats, bass lines and melodies you can edit by hand.
</p>

> 🇮🇹 Italiano: [README.it.md](README.it.md) · Sister projects: [editorvideo-ai (vedit)](https://github.com/metiutek/editorvideo-ai),
> [editorimage-ai (pedit)](https://github.com/metiutek/editorimage-ai)

## Install

```bash
uv tool install medit-mcp
medit ui
```

The editor opens at <http://127.0.0.1:8780>. Let Claude Code write music with you:
`claude mcp add medit -- medit-mcp`. Something wrong? `medit doctor`.

## What it is

An ordinary DAW — arrangement, piano roll, mixer, effects — where **everything you can do with the
mouse, an AI can also do on command**. The buttons, the built-in assistant and any MCP agent call
the exact same operations. Nothing is AI-only, nothing is mouse-only, and nothing is destructive:
notes stay notes, effects stay editable, imported audio is never rewritten, every step undoes.

| | |
|---|---|
| **Writes real music** | Chords from symbols or roman numerals (`vi IV I V`, `ii7 V7 Imaj7`, `i bVI bIII bVII`) with keyboard-player voice leading; 10 chord styles, 9 bass styles, arpeggios, 14 drum genres with fills and swing; melodies in a text notation (`E5:1 D5:0.5 r:1 [C4 E4 G4]:2`). |
| **Sounds on its own** | 31 built-in sounds — pianos, e-piano, pads, strings, supersaw, 808, reese, acid, guitars, harp, 5 drum kits — rendered in numpy, levels calibrated in LUFS. Plus a sampler for your own files. |
| **The agent can't hear, so it looks and measures** | `preview` returns the arrangement, the piano roll or a spectrogram as an image; `analyze_mix` gives LUFS, true peak, band balance and stereo; `review_song` flags clipping, mud, harshness, notes out of key, bass in the wrong register, overlaps — each with the tool that fixes it. |
| **Mixes and masters** | 21 effects (EQ, compressor, true-peak limiter, convolution reverb, tempo-synced delay, chorus, saturation, lo-fi, pump…), buses and sends, automation, `balance_mix` gain staging, `auto_master` to -14 LUFS / -1 dBTP. |
| **Works with your files** | Import WAV, MP3, FLAC, OGG, AIFF (m4a and video audio with ffmpeg) with BPM and key detection; import and export MIDI; export mixdown and stems. |
| **Remembers you, and asks** | Shared memory across songs, clickable questions in the editor, versions you can compare, a chat saved next to each song. |

## Driving it from an agent (MCP)

```bash
claude mcp add --transport http medit-live http://127.0.0.1:8780/mcp/   # the song open in the browser
claude mcp add medit -- uvx medit-mcp                                      # stdio
```

```
project_create(bpm, key) → structure → add_drums / add_chords / add_bassline / add_melody
  → set_instrument / add_effect / add_bus + set_send → preview + analyze_mix
  → review_song → auto_master → export_audio (only when the user asks)
```

## Development

See [AGENTS.md](AGENTS.md). `pytest` (backend), `cd frontend && npm run build && npm test` (UI).

MIT license.
