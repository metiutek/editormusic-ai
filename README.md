<p align="center"><img src="https://raw.githubusercontent.com/metiutek/editormusic-ai/main/docs/logo.svg" alt="medit logo — AI music editor" width="110"/></p>

<h1 align="center">medit — the open-source AI music editor (DAW) you can drive with words</h1>

<p align="center">
  <strong>Tell an AI to write your song, and watch it happen in a real DAW.</strong><br/>
  Chords, beats, bass lines, melodies, lyrics and vocals — built-in synths and drum kits, 31 effects,
  mixing and mastering to -14 LUFS. Works with <b>Claude Code, Cursor, Codex</b> and any MCP client.
  Free, local, MIT.
</p>

<p align="center">
  <a href="https://github.com/metiutek/editormusic-ai/actions/workflows/ci.yml"><img src="https://github.com/metiutek/editormusic-ai/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://pypi.org/project/medit-mcp/"><img src="https://img.shields.io/pypi/v/medit-mcp.svg?style=flat-square" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/medit-mcp/"><img src="https://img.shields.io/pypi/pyversions/medit-mcp.svg?style=flat-square" alt="Python versions"/></a>
  <img src="https://img.shields.io/badge/MCP%20tools-95-blueviolet?style=flat-square" alt="95 MCP tools"/>
  <img src="https://img.shields.io/badge/runs-100%25%20local-brightgreen?style=flat-square" alt="Runs locally"/>
  <a href="https://github.com/metiutek/editormusic-ai/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT license"/></a>
  <a href="https://github.com/metiutek/editormusic-ai/stargazers"><img src="https://img.shields.io/github/stars/metiutek/editormusic-ai?style=flat-square" alt="GitHub stars"/></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/metiutek/editormusic-ai/main/docs/medit-promo.gif" alt="medit demo — an AI agent writes chords, drums, bass and melody in the DAW, then mixes and masters the song" width="640"/>
</p>

<p align="center">
  <a href="https://metiutek.github.io/editormusic-ai/">Website</a> ·
  <a href="#install--3-steps">Install</a> ·
  <a href="#connect-your-ai-agent-mcp">MCP setup</a> ·
  <a href="#what-you-can-ask">Examples</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="https://github.com/metiutek/editormusic-ai/blob/main/README.it.md">🇮🇹 Italiano</a>
</p>

## Why medit

Most "AI music" tools hand you a finished MP3 you cannot touch. Classic DAWs give you every knob and
none of your time back. **medit is both at once**: an ordinary DAW — arrangement, piano roll, mixer,
effects — where **everything you can do with the mouse, an AI agent can also do on command**, because
the buttons, the built-in assistant and any MCP agent call the exact same operations.

- 🎹 **Writes real, editable music** — notes stay notes, chords stay chords, every step undoes with Ctrl+Z.
- 🧠 **Knows music theory** — roman numerals, voice leading, scales, 14 drum genres, 10 chord and 9 bass styles.
- 👂 **The agent "listens" by measuring** — LUFS, true peak, spectrum, piano-roll images and a song review.
- 🎙️ **Records and tunes your voice** — mic recording, Auto-Tune, vocal chains, your own RVC voice model.
- 🤖 **Generative AI, local or cloud** — whole sung songs (ACE-Step), loops (Stable Audio), stems (UVR/Demucs).
- 🔒 **Runs on your machine** — no subscription, no upload, no watermark. MIT licensed.

## Install — 3 steps

**1. Install uv** (it installs Python apps for you), then close and reopen the terminal.

| Windows (PowerShell) | macOS | Linux |
|---|---|---|
| `winget install astral-sh.uv` | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

**2. Install medit**

```bash
uv tool install medit-mcp
```

**3. Open the editor**

```bash
medit ui
```

The DAW opens in your browser at <http://127.0.0.1:8780>. Something missing? `medit doctor` tells you
what and how to fix it. Update with `uv tool upgrade medit-mcp`. Prefer pip? `pip install medit-mcp`.

## Connect your AI agent (MCP)

**Claude Code**

```bash
claude mcp add medit -- uvx medit-mcp                                    # its own song (stdio)
claude mcp add --transport http medit-live http://127.0.0.1:8780/mcp/    # the song open in your browser
```

**Claude Desktop, Cursor, Windsurf, VS Code, Codex** — add to the client's MCP config
(`claude_desktop_config.json`, `.cursor/mcp.json`, …):

```json
{
  "mcpServers": {
    "medit": { "command": "uvx", "args": ["medit-mcp"] }
  }
}
```

With `medit ui` running, point the client at `http://127.0.0.1:8780/mcp/` instead and you watch the
agent work on the timeline in real time — and can grab the mouse at any moment.

The built-in **Assistant** tab works too: with Claude Code installed there is nothing to configure;
otherwise use an Anthropic key, any OpenAI-compatible endpoint or a local Ollama model.

## What you can ask

> *"Write a sad lo-fi song in A minor at 80 BPM: intro, verse, chorus. Dusty drums, Rhodes chords,
> a soft lead melody, then master it for Spotify."*

> *"The chorus needs to be bigger: double the melody an octave up, add a pad and open the drums."*

> *"The bass is muddy — fix it."* · *"Put Auto-Tune on my vocal take, natural, in the song's key."*

> *"Separate the vocals from this MP3 and re-sing them with my voice model."*

Under the hood the agent follows the same path a producer would:

```
project_create(bpm, key) → structure → add_drums / add_chords / add_bassline / add_melody
  → set_instrument / add_effect / add_bus + set_send → preview + analyze_mix
  → review_song → balance_mix / auto_master → export_audio
```

## Features

| | |
|---|---|
| **Composition engine** | Chords from symbols or roman numerals (`vi IV I V`, `ii7 V7 Imaj7`, `i bVI bIII bVII`) with keyboard-player voice leading; 10 chord styles, 9 bass styles, arpeggiator, 14 drum genres with fills and swing; melodies in a text notation (`E5:1 D5:0.5 r:1 [C4 E4 G4]:2`); song structure with lyrics per section. |
| **Built-in instruments** | 31 sounds — piano, e-piano, organ, pads, strings, supersaw, 808, reese, acid, guitars, harp, 5 drum kits — subtractive (PolyBLEP), FM and Karplus-Strong synthesis in numpy, levels calibrated in LUFS. Plus a sampler for your own files. |
| **Mixing & mastering** | 31 effects (Auto-Tune, pitch shift, parametric and 10-band graphic EQ, compressor, multiband, transient shaper, de-esser, true-peak limiter, convolution reverb, tempo-synced delay, doubler, chorus, phaser, exciter, saturation, lo-fi…), 22 ready chains, buses and sends, automation, `balance_mix` gain staging, `auto_master` to -14 LUFS / -1 dBTP. |
| **Analysis the agent can read** | `preview` returns arrangement, piano roll or spectrogram as an image; `analyze_mix` gives LUFS (BS.1770), true peak, band balance and stereo; `review_song` flags clipping, mud, harshness, notes out of key, bass in the wrong register — each with the tool that fixes it. |
| **Vocal recording** | Press R: the song plays and the mic records from the playhead, latency compensated, with metronome, count-in and lyrics view. One click adds Auto-Tune (natural or hard), a pop vocal chain or a double. |
| **Your files** | Import WAV, MP3, FLAC, OGG, AIFF (m4a and video with ffmpeg) with BPM and key detection; import/export MIDI; export mixdown and stems. |
| **Generative AI** | `generate_song` — a whole sung song from a style and your lyrics (ACE-Step 1.5 in ComfyUI, or ElevenLabs Music); `generate_audio` — loops and effects N bars long (Stable Audio, Replicate); `separate_stems` — vocals/drums/bass with your **Ultimate Vocal Remover** models or Demucs; `audio_to_midi` — humming or beatbox to notes; `convert_voice` / `voice_cover` — re-sing with **your own voice model** (Applio RVC). Everything lands on new tracks. |
| **Memory** | Preferences shared across songs, clickable questions in the editor, versions to compare, a chat saved next to each song. |

## How it compares

| | medit | AI song generators | Classic DAWs |
|---|---|---|---|
| Editable result (notes, tracks, effects) | ✅ | ❌ one audio file | ✅ |
| An AI agent does the work | ✅ 95 MCP tools | ✅ prompt only | ❌ |
| Mix & master to a loudness target | ✅ automatic + manual | ❌ | manual |
| Runs locally, no subscription | ✅ | ❌ | depends |
| Open source | ✅ MIT | ❌ | rarely |

## FAQ

**Is medit free?** Yes. MIT license, no account, no watermark. Cloud services (ElevenLabs, Replicate)
are optional and use your own key.

**Can Claude (or ChatGPT, Cursor, Codex) make music with it?** Yes — any client that speaks the
Model Context Protocol gets 95 tools: compose, arrange, mix, master, analyze and export.

**Does it need a GPU?** No. The DAW, synths, effects and analysis run on the CPU in numpy. Only the
optional generative models (ACE-Step, Stable Audio, RVC, Demucs) want a GPU.

**Can I use my own samples and recordings?** Yes: drag audio files in, use the sampler, or record
from the microphone. Imported audio is never rewritten.

**What does it export?** WAV, FLAC, MP3, OGG, MIDI and per-track stems.

**Windows, macOS, Linux?** All three; Python 3.10+.

## Sister projects

Same philosophy, same agent workflow:
[**vedit**](https://github.com/metiutek/editorvideo-ai) — AI video editor ·
[**pedit**](https://github.com/metiutek/editorimage-ai) — AI image editor.

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](https://github.com/metiutek/editormusic-ai/blob/main/CONTRIBUTING.md)
and [AGENTS.md](https://github.com/metiutek/editormusic-ai/blob/main/AGENTS.md) (the contract for humans and coding agents).
Tests: `pytest` and `cd frontend && npm run build && npm test`.

If medit is useful to you, a ⭐ helps other musicians and developers find it.

[MIT license](https://github.com/metiutek/editormusic-ai/blob/main/LICENSE).

<p align="center"><sub>Created by <a href="https://metiu.xyz/"><b>Mattia Cibin (Metiu)</b></a> — independent developer from Italy.</sub></p>
