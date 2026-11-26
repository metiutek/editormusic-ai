"""Fixture comuni: canzoni in cartelle temporanee, audio sintetico.

Niente rete, niente modelli: ``MEDIT_HOME`` punta a una cartella temporanea
cosi' i test non toccano ``~/.medit`` di chi li lancia.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from medit import render
from medit.store import Store


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MEDIT_SEGNALAZIONI", str(tmp_path / "SEGNALAZIONI.md"))
    # skill e server MCP dell'utente: mai quelli veri di chi lancia i test
    monkeypatch.setenv("MEDIT_HOME_CLAUDE", str(tmp_path / "claude_home"))
    monkeypatch.setenv("MEDIT_CLAUDE_JSON", str(tmp_path / "claude.json"))
    monkeypatch.setenv("MEDIT_CLAUDE_DESKTOP", str(tmp_path / "claude_desktop.json"))
    render.clear_cache()


@pytest.fixture
def store(tmp_path):
    # 22050 Hz: render piu' veloci, stessa logica
    return Store.create(name="t", bpm=120, key="A", mode="minor", sample_rate=22050, path=str(tmp_path / "song.json"))


@pytest.fixture
def click_wav(tmp_path):
    """Quattro secondi a 120 BPM: un click ogni beat (per il rilevamento del tempo)."""
    sr = 22050
    x = np.zeros(sr * 8)
    for k in range(16):
        i = int(k * 0.5 * sr)
        n = np.arange(800)
        x[i:i + 800] += np.sin(2 * np.pi * 1000 * n / sr) * np.exp(-n / 150)
    p = tmp_path / "click.wav"
    sf.write(str(p), x.astype(np.float32), sr)
    return str(p)


@pytest.fixture
def tone_wav(tmp_path):
    """Due secondi di La 440 Hz stereo."""
    sr = 44100
    t = np.arange(sr * 2) / sr
    x = 0.5 * np.sin(2 * np.pi * 440 * t)
    p = tmp_path / "tone.wav"
    sf.write(str(p), np.stack([x, x], axis=1).astype(np.float32), sr)
    return str(p)
