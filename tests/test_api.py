"""API della UI: stesse operazioni dello Store, audio WAV, stato."""

import io

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from medit import api


@pytest.fixture
def client(tmp_path):
    c = TestClient(api.app)
    r = c.post("/api/project/create", json={"name": "t", "bpm": 120, "key": "C", "path": str(tmp_path / "s.json")})
    assert r.status_code == 200
    return c


def test_state_lists_everything(client):
    s = client.get("/api/state").json()
    assert s["project"]["bpm"] == 120
    assert any(e["name"] == "reverb" for e in s["effects"])
    assert any(x["name"] == "808" for x in s["sounds"])
    assert "trap" in s["theory"]["drum_genres"]


def test_ops_and_errors(client):
    r = client.post("/api/op/add_chords", json={"progression": "C Am F G"})
    assert r.status_code == 200 and r.json()["project"]["tracks"][0]["name"] == "Chords"
    r = client.post("/api/op/set_track", json={"track": "nope", "volume_db": 1})
    assert r.status_code == 400 and "tracks:" in r.json()["detail"]
    assert client.post("/api/op/save", json={}).status_code == 404
    r = client.post("/api/op/undo", json={})
    assert r.json()["project"]["tracks"] == []


def test_audio_is_a_wav(client):
    client.post("/api/op/add_drums", json={"genre": "pop", "bars": 1})
    r = client.get("/api/audio")
    assert r.headers["content-type"] == "audio/wav"
    x, sr = sf.read(io.BytesIO(r.content))
    assert sr == 44100 and x.shape[1] == 2 and abs(x).max() > 0.05
    r = client.get("/api/note", params={"track": "Drums", "pitch": 38})
    assert r.status_code == 200 and len(r.content) > 1000


def test_peaks_of_audio_clip(client, tone_wav):
    r = client.post("/api/op/add_audio", json={"path": tone_wav})
    asset = r.json()["result"]["asset"]
    p = client.get(f"/api/peaks/{asset}").json()
    assert len(p["peaks"]) > 100 and max(p["peaks"]) > 0.4


def test_export_endpoint(client, tmp_path):
    client.post("/api/op/add_chords", json={"progression": "C"})
    r = client.post("/api/export", json={"path": str(tmp_path / "o.wav")})
    assert r.status_code == 200 and (tmp_path / "o.wav").exists()


def test_non_local_host_refused(client):
    api._consenti("127.0.0.1")
    try:
        r = client.get("/api/state", headers={"host": "evil.example"})
        assert r.status_code == 403
    finally:
        api._host_consentiti.clear()


def test_client_disconnects_are_silent():
    chiamate = []

    class Loop:
        def default_exception_handler(self, ctx):
            chiamate.append(ctx)

    api._connessioni_chiuse(Loop(), {"exception": ConnectionResetError(10054, "reset")})
    api._connessioni_chiuse(Loop(), {"exception": ConnectionAbortedError()})
    assert chiamate == []
    api._connessioni_chiuse(Loop(), {"exception": ValueError("vero errore")})
    assert len(chiamate) == 1
