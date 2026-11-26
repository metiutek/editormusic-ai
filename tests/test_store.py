"""Lo Store: ogni operazione, undo, salvataggio, versioni."""

import json

import pytest

from medit.store import EditError, Store


def test_create_save_reopen(store):
    store.add_chords("Am F C G")
    dati = json.loads(open(store.path, encoding="utf-8").read())
    assert dati["key"] == "A" and dati["mode"] == "minor"
    s2 = Store.open(store.path)
    assert s2.project.tracks[0].name == "Chords"
    assert len(s2.project.tracks[0].clips[0].notes) > 0


def test_bad_inputs_say_what_is_allowed(store):
    with pytest.raises(EditError, match="bars start at 1"):
        store.add_section("intro", 0, 4)
    with pytest.raises(EditError, match="tracks:"):
        store.set_track("nope", volume_db=-3)
    with pytest.raises(EditError, match="available"):
        store.add_track(sound="kazoo")
    with pytest.raises(EditError, match="out of range"):
        store.add_track(sound="piano")
        store.add_effect("Piano", "eq", {"low_gain": 99})


def test_one_action_one_undo(store):
    store.add_bus("Verb")             # add_track + apply_chain dentro: un solo passo
    assert len(store._undo) == 1
    store.undo()
    assert not store.project.tracks
    store.redo()
    assert store.project.tracks[0].kind == "bus"


def test_failed_edit_leaves_song_untouched(store):
    store.add_chords("Am F")
    prima = store.project.to_dict()
    with pytest.raises(EditError):
        store.add_chords("Am Xq")
    assert store.project.to_dict() == prima


def test_batch_is_atomic(store):
    with pytest.raises(EditError):
        with store.batch():
            store.add_chords("Am F")
            store.set_track("missing", volume_db=1)
    assert not store.project.tracks


def test_generators_create_tracks_and_clips(store):
    r = store.add_drums("trap", bars=4, fill_every=4)
    assert r["track"] == "Drums" and store.project.track("Drums").instrument.preset == "trap kit"
    store.add_chords("i bVI bIII bVII", bars=8, style="pad", sound="warm pad")
    store.add_bassline("i bVI bIII bVII", bars=8, style="808", sound="808")
    store.add_arpeggio("Am F", bars=2)
    store.add_melody("A4:1 C5:1 E5:2")
    assert [t.name for t in store.project.tracks] == ["Drums", "Chords", "Bass", "Arp", "Lead"]
    assert store.project.track("Chords").clips[0].length == 32


def test_notes_edit_cycle(store):
    store.add_track(sound="piano", name="Keys")
    c = store.add_clip("Keys", bar=2, notes=[["C4", 0, 1, 100], {"pitch": "E4", "start": 1, "length": 1}])
    cid = c["id"]
    store.add_notes(cid, melody="G4:1 C5:1", at=2)
    assert len(store.get_notes(cid)["notes"]) == 4
    store.edit_notes(cid, transpose=12, pitch="C4")
    assert ["C5", 0.0, 1.0, 100] in store.get_notes(cid)["notes"]
    store.remove_notes(cid, indices=[0])
    assert len(store.get_notes(cid)["notes"]) == 3
    store.quantize(cid, 0.5)
    store.humanize(cid)
    store.transpose(cid, -12)
    store.remove_notes(cid, all=True)
    assert store.get_notes(cid)["notes"] == []


def test_split_and_duplicate(store):
    store.add_track(sound="piano", name="Keys")
    cid = store.add_clip("Keys", bar=1, bars=4, notes=[["C4", 0, 1, 100], ["D4", 8, 1, 100]])["id"]
    r = store.split_clip(cid, 3)
    assert r["left"]["bars"] == 2 and r["right"]["bar"] == 3
    assert r["left"]["notes"] == 1 and r["right"]["notes"] == 1
    d = store.duplicate_clip(r["right"]["id"], times=2)
    assert [x["bar"] for x in d["copies"]] == [5, 7]


def test_copy_insert_delete_bars(store):
    store.structure([{"name": "verse", "bars": 4}, {"name": "chorus", "bars": 4}])
    store.add_chords("Am F C G", bar=1)
    store.add_drums("pop", bar=1, bars=8)
    store.copy_bars(1, 4, 9)
    assert len(store.project.track("Chords").clips) == 2
    assert [s.name for s in store.project.sections] == ["verse", "chorus", "verse"]
    store.insert_bars(5, 2)
    assert store.project.section("chorus").start == 6 * 4
    assert any(c.start == 6 * 4 for c in store.project.track("Drums").clips)
    store.delete_bars(5, 2)
    assert store.project.section("chorus").start == 4 * 4
    drums = store.project.track("Drums").clips
    assert sum(c.length for c in drums) == 12 * 4   # 8 battute + le 4 copiate


def test_fit_to_scale(store):
    store.add_track(sound="piano", name="Keys")
    cid = store.add_clip("Keys", notes=[["C#4", 0, 1], ["A4", 1, 1]])["id"]
    assert store.fit_to_scale("Keys")["moved_notes"] == 1
    assert all(n[0] in ("C4", "D4", "A4") for n in store.get_notes(cid)["notes"])


def test_effects_and_automation(store):
    store.add_chords("Am")
    store.add_effect("Chords", "eq", {"low_cut": 120})
    store.add_effect("Chords", "lowpass")
    store.set_automation("Chords", "fx.1.cutoff", [[1, 300], [2, 8000]])
    with pytest.raises(EditError, match="cannot be automated"):
        store.set_automation("Chords", "fx.0.low_cut", [[1, 1]])
    store.remove_effect("Chords", 0)
    assert store.project.track("Chords").automation[0].target == "fx.0.cutoff"
    store.apply_chain("master", "master streaming")
    assert store.project.master.effects[-1].type == "limiter"


def test_auto_master_hits_target(store):
    store.add_drums("house", bars=4)
    store.add_chords("Am F C G", style="offbeat")
    store.add_bassline("Am F C G", style="offbeat")
    r = store.auto_master(-12)
    assert abs(r["lufs"] - (-12)) < 1.0
    assert r["true_peak_db"] <= -0.9


def test_review_finds_problems(store):
    store.add_track(sound="piano", name="Keys")
    store.add_clip("Keys", bar=1, bars=2, notes=[["C#4", 0, 1], ["F#4", 1, 1], ["G#4", 2, 1]])
    store.add_clip("Keys", bar=2, bars=2, notes=[["A4", 0, 1]])
    store.add_track(sound="saw bass", name="Bass", role="bass")
    store.add_clip("Bass", notes=[["C5", 0, 4]])
    codici = {w["code"] for w in store.review()}
    assert {"overlap", "out_of_key", "bass_high"} <= codici


def test_audio_import(store, click_wav):
    r = store.add_audio(path=click_wav, bar=1, adopt_tempo=True)
    assert abs(r["detected_bpm"] - 120) < 2
    assert store.project.tracks[0].kind == "audio"
    st = store.analyze()
    assert st["peak_db"] > -20


def test_open_audio_file_starts_a_song(tone_wav):
    s = Store.open(tone_wav)
    assert s.project.tracks[0].clips[0].kind == "audio"
    assert s.path is None


def test_export_audio_and_midi(store, tmp_path):
    store.add_drums("pop", bars=1)
    store.add_chords("Am F", bars=2)
    for ext in ("wav", "flac", "mp3"):
        r = store.export_audio(str(tmp_path / f"song.{ext}"))
        assert (tmp_path / f"song.{ext}").stat().st_size > 1000 and r["duration_s"] > 3
    m = store.export_midi(str(tmp_path / "song.mid"))
    assert m["tracks"] == 2
    s2 = Store.create(name="b", sample_rate=22050)
    r = s2.import_midi(str(tmp_path / "song.mid"), adopt_tempo=True)
    assert {x["track"] for x in r["tracks"]} == {"Drums", "Chords"}
    assert s2.project.track("Drums").instrument.type == "drums"
    stems = store.export_stems(str(tmp_path / "stems"))
    assert len(stems["stems"]) == 2


def test_versions(store):
    store.add_chords("Am F")
    store.snapshot("first")
    store.add_drums("pop")
    cmp = store.compare_versions("first")
    assert cmp["added"] == ["Drums"]
    store.restore_snapshot("first")
    assert [t.name for t in store.project.tracks] == ["Chords"]
    store.undo()
    assert len(store.project.tracks) == 2


def test_balance_mix_by_role(store):
    store.add_drums("pop", bars=2)
    store.add_chords("Am F", style="pad", sound="warm pad")
    r = store.balance_mix()
    assert set(r["changed"]) == {"Drums", "Chords"}


def test_set_song(store):
    store.set_song(bpm=90, key="D dorian", swing=0.3)
    p = store.project
    assert (p.bpm, p.key, p.mode, p.swing) == (90, "D", "dorian", 0.3)
    with pytest.raises(EditError):
        store.set_song(bpm=5)


def test_effect_view_eq_and_compressor(store):
    store.add_chords("Am F C G")
    store.add_effect("Chords", "eq", {"high_cut": 1000})
    store.add_effect("Chords", "compressor", {"threshold_db": -40, "ratio": 8})
    v = store.effect_view("Chords", 0)
    s = v["spectrum"]
    assert v["effect"] == "eq" and len(s["freqs"]) == len(s["in"]) == len(s["out"])
    # il passa-basso a 1 kHz toglie gli alti in uscita, non in entrata
    alto = [i for i, f in enumerate(s["freqs"]) if f > 4000]
    assert all(s["out"][i] < s["in"][i] - 6 for i in alto)
    assert "time" not in v
    c = store.effect_view("Chords", 1)
    # l'ingresso del compressore e' l'uscita dell'EQ
    assert c["spectrum"]["in"] == s["out"]
    assert c["gr"]["max_db"] < -6 and len(c["time"]["gr_db"]) == len(c["time"]["in_db"])
    assert len(c["detector_hist"]) == 60
    store.add_effect("master", "limiter", {"gain_db": 12})
    m = store.effect_view("master", -1)
    assert m["index"] == 0 and m["gr"]["max_db"] < -1
    with pytest.raises(EditError):
        store.effect_view("Chords", 5)


def test_every_chain_is_valid_and_has_a_family(store):
    from medit import effects as fx, presets
    for c in presets.describe_chains():
        if c["user"]:
            continue
        assert c["category"] in {"voice clean", "voice rap", "voice experimental", "voice spaces",
                                 "instrument", "bus", "master"}, c["name"]
        for e in presets.chain(c["name"])["effects"]:
            fx.validate(e["type"], e.get("params"), partial=True)
    t = store.add_track(kind="audio", name="Vox")
    store.apply_chain("Vox", "vocal trap", replace=True)
    assert [e.type for e in store.project.track("Vox").effects][0] == "autotune"
