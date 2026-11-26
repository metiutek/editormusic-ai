"""Fase generativa: ComfyUI, servizi in rete, Demucs e Applio simulati; trascrizione vera."""

import io
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from medit import ai, cloud, comfy, separa, trascrivi, voce
from medit.store import EditError

SR = 22050


def _audio_bytes(fmt="FLAC", seconds=2.0, f=220.0):
    t = np.arange(int(44100 * seconds)) / 44100
    x = 0.3 * np.sin(2 * np.pi * f * t)
    buf = io.BytesIO()
    sf.write(buf, np.stack([x, x], axis=1).astype(np.float32), 44100, format=fmt)
    return buf.getvalue()


def _melodia_wav(tmp_path, pitches=(69, 72, 76), dur=0.5):
    sr = 44100
    parti = []
    for p in pitches:
        t = np.arange(int(sr * dur)) / sr
        f = 440 * 2 ** ((p - 69) / 12)
        env = np.minimum(1, np.minimum(t / 0.01, (dur - t) / 0.02))
        parti.append(0.5 * np.sin(2 * np.pi * f * t) * env)
    x = np.concatenate([np.zeros(sr // 4)] + parti + [np.zeros(sr // 4)])
    f = tmp_path / "melody.wav"
    sf.write(str(f), x.astype(np.float32), sr)
    return str(f)


def test_status_says_what_is_missing():
    st = ai.status()
    assert st["comfyui"]["ok"] is False and "hint" in st["comfyui"]
    assert st["stems"]["ok"] is False and "demucs" in st["stems"]["hint"].lower()
    assert st["voice"]["ok"] is False
    assert st["audio_to_midi"]["ok"] is True


def test_no_engine_no_surprise_spending(store):
    cloud.imposta("elevenlabs", key="sk-test")   # chiave c'e', ma non e' predefinita
    with pytest.raises(EditError, match="ComfyUI is not running"):
        store.generate_song("lofi")
    assert not store.project.tracks


def test_song_workflow_matches_the_template():
    wf = comfy.workflow_song("ace.safetensors", "pop", "[Verse]\nla", 30, 100, "A minor", 4, "en", 7)
    tipi = {v["class_type"] for v in wf.values()}
    assert {"TextEncodeAceStepAudio1.5", "EmptyAceStep1.5LatentAudio", "ModelSamplingAuraFlow",
            "ConditioningZeroOut", "VAEDecodeAudio", "SaveAudio"} <= tipi
    enc = wf["3"]["inputs"]
    assert enc["bpm"] == 100 and enc["keyscale"] == "A minor" and enc["duration"] == 30.0
    assert wf["6"]["inputs"]["steps"] == 8 and wf["6"]["inputs"]["cfg"] == 1.0
    a = comfy.workflow_audio("sa.safetensors", "drum loop", "noise", 10, 1)
    assert a["2"]["inputs"]["type"] == "stable_audio"


def test_generate_song_with_comfy(store, monkeypatch):
    preso = {}
    monkeypatch.setattr(comfy, "available", lambda timeout=1.5: True)
    monkeypatch.setattr(comfy, "status", lambda: {"ok": True, "url": "x", "song_model": "ace.safetensors",
                                                  "audio_model": None})

    def finto(tags, lyrics, seconds, bpm, keyscale, time_sig=4, language="en", s=None):
        preso.update(tags=tags, lyrics=lyrics, seconds=seconds, keyscale=keyscale)
        return _audio_bytes("FLAC", 3)

    monkeypatch.setattr(comfy, "generate_song", finto)
    store.structure([{"name": "verse", "bars": 4, "lyrics": "walking alone"}, {"name": "chorus", "bars": 4,
                                                                               "lyrics": "we rise"}])
    r = store.generate_song("indie pop, female vocal")
    assert r["backend"] == "comfyui" and r["lyrics_used"]
    assert preso["lyrics"] == "[Verse]\nwalking alone\n\n[Chorus]\nwe rise"
    assert preso["seconds"] == pytest.approx(16.0) and preso["keyscale"] == "A minor"
    t = store.project.tracks[0]
    assert t.kind == "audio" and store.project.assets[0].generated
    assert len(store._undo) == 2   # struttura + canzone: un passo ciascuno


def test_generate_audio_elevenlabs_explicit(store, monkeypatch):
    cloud.imposta("elevenlabs", key="sk-test")
    chiamate = []

    def http(method, url, headers, body=None, timeout=600.0):
        chiamate.append((url, headers, json.loads(body)))
        return _audio_bytes("MP3", 4), "audio/mpeg"

    monkeypatch.setattr(cloud, "_http", http)
    r = store.generate_audio("dusty drum loop", bars=2, backend="elevenlabs")
    url, h, body = chiamate[0]
    assert url.endswith("/v1/music") and h["xi-api-key"] == "sk-test"
    assert body["music_length_ms"] == 4000 and "120 BPM" in body["prompt"]
    assert r["bars"] == 2


def test_cloud_default_is_used_by_auto(store, monkeypatch):
    cloud.imposta("replicate", key="r8-test", default=True)
    passi = iter([({"status": "starting", "urls": {"get": "https://api.replicate.com/v1/p/1"}}, "application/json"),
                  ({"status": "succeeded", "output": "https://x/out.wav"}, "application/json"),
                  (None, "audio/wav")])

    def http(method, url, headers, body=None, timeout=600.0):
        dati, ctype = next(passi)
        return (_audio_bytes("WAV", 2) if dati is None else json.dumps(dati).encode()), ctype

    monkeypatch.setattr(cloud, "_http", http)
    monkeypatch.setattr(cloud.time, "sleep", lambda s: None)
    r = store.generate_audio("ambient pad", seconds=2)
    assert r["backend"] == "replicate"


def test_keys_never_go_through_mcp():
    from medit import mcp_server as ms

    schema = json.dumps(ms.mcp._tool_manager.get_tool("ai_services").parameters)
    assert "key" not in json.loads(schema)["properties"]
    cloud.imposta("elevenlabs", key="sk-segretissima")
    assert "segretissima" not in json.dumps(ms.ai_services())


def test_melody_transcription(tmp_path):
    x, sr = sf.read(_melodia_wav(tmp_path))
    note = trascrivi.melody(np.stack([x, x]), sr)
    assert [n["pitch"] for n in note] == [69, 72, 76]
    assert all(abs(n["length"] - 0.5) < 0.1 for n in note)


def test_audio_to_midi_lands_on_the_grid(store, tmp_path):
    r = store.add_audio(path=_melodia_wav(tmp_path), bar=2)
    m = store.audio_to_midi(r["id"])
    note = store.get_notes(m["clip"])["notes"]
    assert [n[0] for n in note] == ["A4", "C5", "E5"]
    assert note[0][1] == 0.5 and note[1][1] == 1.5   # 0.25 s di silenzio = mezzo beat a 120 BPM
    assert store.project.track(m["track_id"]).clips[0].start == 4.0


def test_drum_transcription():
    sr = 22050
    x = np.zeros(sr * 2)
    for k, kind in enumerate(["kick", "hat", "snare", "hat"] * 2):
        i = int(k * 0.25 * sr)
        n = np.arange(2000)
        rng = np.random.default_rng(k)
        if kind == "kick":
            x[i:i + 2000] += np.sin(2 * np.pi * 60 * n / sr) * np.exp(-n / 600)
        elif kind == "hat":
            from scipy.signal import butter, lfilter

            b, a = butter(4, 7000 / (sr / 2), "high")
            x[i:i + 2000] += lfilter(b, a, rng.uniform(-1, 1, 2000)) * np.exp(-n / 150)
        else:
            x[i:i + 2000] += (rng.uniform(-1, 1, 2000) * 0.5 + np.sin(2 * np.pi * 200 * n / sr)) * np.exp(-n / 400)
    note = trascrivi.drums(x, sr)
    assert [n["pitch"] for n in note][:4] == [36, 42, 38, 42]


def test_separate_stems_non_destructive(store, tone_wav, monkeypatch):
    def finto(src, outdir, two_stems=False, model="htdemucs", timeout=0):
        out = {}
        for n in separa.STEMS4:
            f = outdir / n / "x.wav"
            f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, f)
            out[n] = f
        return out

    monkeypatch.setattr(separa, "separa", finto)
    r = store.add_audio(path=tone_wav)
    s = store.separate_stems(r["id"])
    assert [x["stem"] for x in s["stems"]] == list(separa.STEMS4)
    _, orig = store.project.clip(r["id"])
    assert orig.muted and len(store.project.tracks) == 5
    assert store.project.track(s["stems"][0]["track_id"]).role == "vocal"
    store.undo()
    assert len(store.project.tracks) == 1 and not store.project.clip(r["id"])[1].muted


def test_convert_voice_with_applio(store, tone_wav, tmp_path, monkeypatch):
    # un Applio finto: core.py, env/python.exe, un modello in logs/
    app = tmp_path / "Applio"
    (app / "env").mkdir(parents=True)
    (app / "core.py").write_text("")
    (app / "env" / "python.exe").write_text("")
    (app / "logs" / "paolo").mkdir(parents=True)
    (app / "logs" / "paolo" / "paolo_100e.pth").write_text("")
    (app / "logs" / "paolo" / "G_100.pth").write_text("")
    (app / "logs" / "paolo" / "paolo.index").write_text("")
    monkeypatch.setenv("MEDIT_APPLIO", str(app))
    assert voce.modelli()[0]["pth"].endswith("paolo_100e.pth")
    comandi = []

    def run(cmd, cwd=None, capture_output=True, timeout=0, env=None):
        comandi.append(cmd)
        dst = Path(cmd[cmd.index("--output-path") + 1])
        shutil.copyfile(cmd[cmd.index("--input-path") + 1], dst)

        class R:
            returncode, stdout, stderr = 0, b"", b""
        return R()

    monkeypatch.setattr(voce.subprocess, "run", run)
    r = store.add_audio(path=tone_wav)
    out = store.convert_voice(r["id"], "paolo", pitch=-12)
    assert "--pitch" in comandi[0] and comandi[0][comandi[0].index("--pitch") + 1] == "-12"
    assert out["model"] == "paolo" and store.project.clip(r["id"])[1].muted
    with pytest.raises(EditError, match="no voice model"):
        store.convert_voice(r["id"], "nessuno")


def test_api_ai_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from medit import api

    c = TestClient(api.app)
    c.post("/api/project/create", json={"name": "t", "path": str(tmp_path / "s.json")})
    st = c.get("/api/ai").json()
    assert "comfyui" in st and "voice" in st
    r = c.post("/api/ai/services", json={"service": "elevenlabs", "key": "sk-abcdef", "default": True})
    assert r.json()["default"] == "elevenlabs" and r.json()["services"]["elevenlabs"]["ready"]
    r = c.post("/api/op/generate_song", json={"prompt": ""})
    assert r.status_code == 400
