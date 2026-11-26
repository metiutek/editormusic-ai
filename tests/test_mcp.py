"""Server MCP: strumenti registrati, risposte compatte, batch, regole nelle istruzioni."""

import asyncio
import json

import pytest

from medit import mcp_server as ms
from medit.mcp_server import Image


def _run(fn, **kw):
    out = fn(**kw)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


@pytest.fixture
def song(tmp_path):
    ms._current[0] = None
    ms._stores.clear()
    ms.project_create(path=str(tmp_path / "s.json"), bpm=100, key="C")
    return ms._current[0]


def test_instructions_keep_the_rules():
    for frase in ("NON PUOI ASCOLTARE", "review_song", "Non esportare mai", "battute 1-based", "ask_user", "remember"):
        assert frase in ms.ISTRUZIONI


def test_every_tool_has_a_description():
    assert len(ms.STRUMENTI) >= 75
    for nome in ms.STRUMENTI:
        t = ms.mcp._tool_manager.get_tool(nome)
        assert t is not None and len(t.description) > 10, nome
        assert '"title": "' not in json.dumps(t.parameters)
        assert set(t.parameters.get("required", [])) <= set(t.parameters.get("properties", {}))


def test_full_song_through_tools(song):
    ms.structure([{"name": "verse", "bars": 4}, {"name": "chorus", "bars": 4}])
    ms.add_drums("pop", bars=8, fill_every=4)
    ms.add_chords("I V vi IV", bars=8)
    ms.add_bassline("I V vi IV", bars=8, style="pulse")
    ms.add_melody("E5:1 D5:1 C5:2", bar=5)
    info = ms.project_info()
    assert len(info["tracks"]) == 4
    out = _run(ms.preview)
    assert isinstance(out[0], Image)
    out = _run(ms.preview, view="piano_roll", track="Lead")
    assert isinstance(out[0], Image)
    out = _run(ms.preview, view="mix")
    assert isinstance(out[0], Image)
    st = _run(ms.analyze_mix)
    assert st["lufs"] > -40
    r = _run(ms.review_song)
    assert "warnings" in r


def test_batch_one_undo(song):
    r = _run(ms.batch, ops=[{"tool": "add_chords", "args": {"progression": "C G"}},
                            {"tool": "set_track", "args": {"track": "Chords", "volume_db": -6}}])
    assert r["done"] == 2
    assert len(song._undo) == 1
    with pytest.raises(Exception):
        _run(ms.batch, ops=[{"tool": "export_audio", "args": {"path": "x.wav"}}])


def test_music_reference(song):
    r = ms.music_reference(mood="sad")
    assert r["scale"]["key"] == "C"
    assert any("sad" in p["mood"] or "emotional" in p["mood"] for p in r["progressions"])


def test_errors_are_tool_errors(song):
    from mcp.server.mcpserver.exceptions import ToolError

    t = ms.mcp._tool_manager.get_tool("set_track")
    with pytest.raises(ToolError, match="tracks:"):
        t.fn(track="nope", volume_db=1)


def test_memory_tools(song):
    ms.remember("beats at 140 bpm", "genres")
    assert "140" in ms.memory()["testo"]
    ms.forget("140")
    assert "140" not in ms.memory()["testo"]
