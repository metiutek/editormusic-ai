import pytest

from medit import theory as t


def test_pitch_names():
    assert t.parse_pitch("C4") == 60
    assert t.parse_pitch("A4") == 69
    assert t.parse_pitch("Bb3") == 58
    assert t.parse_pitch("Cb4") == 59
    assert t.parse_pitch(61) == 61
    assert t.pitch_name(61) == "C#4"
    with pytest.raises(t.TheoryError):
        t.parse_pitch("H2")


def test_keys_and_scales():
    assert t.parse_key("A minor") == (9, "minor")
    assert t.parse_key("Am") == (9, "minor")
    assert t.parse_key("F#", "dorian") == (6, "dorian")
    assert t.scale_info("D", "minor")["notes"] == ["D", "E", "F", "G", "A", "Bb", "C"]
    triadi = [c["triad"] for c in t.scale_info("C")["chords"]]
    assert triadi == ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]


def test_progressions():
    assert [c for c, _ in t.parse_progression("vi IV I V", "C")] == ["Am", "F", "C", "G"]
    assert [c for c, _ in t.parse_progression("i bVI bIII bVII", "A", "minor")] == ["Am", "F", "C", "G"]
    assert [c for c, _ in t.parse_progression("ii7 V7 Imaj7", "C")] == ["Dm7", "G7", "Cmaj7"]
    assert t.parse_progression("| Am | F | C G |") == [("Am", 4.0), ("F", 4.0), ("C", 2.0), ("G", 2.0)]
    assert t.parse_progression("Am:2 - F:4") == [("Am", 2.0), ("Am", 4.0), ("F", 4.0)]
    with pytest.raises(t.TheoryError):
        t.parse_progression("Xq7")


def test_voice_leading_moves_little():
    c = t.voice_chord("C")
    f = t.voice_chord("F", prev=c)
    # condotta delle voci: ogni voce si muove al massimo di una terza
    assert max(min(abs(a - b) for b in c) for a in f) <= 4


def test_melody_notation():
    n = t.parse_melody("C5:1 D5:0.5 E5 r:1 [C4 E4 G4]:2! G5:1~ G5:1")
    assert [x["pitch"] for x in n[:3]] == [72, 74, 76]
    assert n[2]["start"] == 1.5 and n[2]["length"] == pytest.approx(0.475)   # durata ereditata
    accordo = [x for x in n if x["start"] == 3.0]
    assert len(accordo) == 3 and accordo[0]["velocity"] == 120
    assert n[-1]["pitch"] == 79 and n[-1]["length"] == 2.0                   # legatura


def test_generators():
    prog = t.parse_progression("Am F C G")
    for style in t.CHORD_STYLES:
        assert t.chords_notes(prog, style)
    for style in t.BASS_STYLES:
        bass = t.bass_notes(prog, style)
        assert bass and all(n["pitch"] < 60 for n in bass)
    for pat in t.ARP_PATTERNS:
        assert t.arp_notes(prog, pat)
    for genre in t.DRUM_PATTERNS:
        notes, _ = t.drum_notes(genre, 2, fill_every=2)
        assert notes and all(0 <= n["start"] < 8 for n in notes)


def test_drum_swing_moves_offbeats():
    dritto, _ = t.drum_notes("funk", 1, swing=0.0)
    swing, _ = t.drum_notes("funk", 1, swing=1.0)
    assert {n["start"] for n in dritto} != {n["start"] for n in swing}


def test_snap_to_scale():
    pcs = t.scale_pcs("C")
    assert t.snap_to_scale(61, pcs) == 60
    assert t.snap_to_scale(62, pcs) == 62
