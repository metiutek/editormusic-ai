"""Il suono: motori, effetti, mix. Si guardano i campioni, non solo che non diano errore."""

import numpy as np
import pytest

from medit import analyze, effects as fx, presets, render, synth

SR = 22050


def _freq(y, sr=SR):
    m = y.mean(axis=0)
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    return np.fft.rfftfreq(len(m), 1 / sr)[np.argmax(spec)]


@pytest.mark.parametrize("kind", ["synth", "fm", "pluck"])
def test_engines_play_the_right_pitch(kind):
    par = {"synth": {"filter": "none", "unison": 1, "osc1": "sine", "osc_mix": 0}, "fm": {"index": 0.0}}.get(kind, {})
    y = synth.render_notes(kind, par, [(0, SR, 69.0, 100)], SR * 2, SR)
    assert np.isfinite(y).all() and np.abs(y).max() > 0.01
    assert abs(_freq(y[:, : SR]) - 440) < 8


def test_drums_choke_and_kit():
    ev = [(0, 1000, 46.0, 110), (SR // 4, 1000, 42.0, 100)]
    y = synth.render_notes("drums", {}, ev, SR, SR)
    open_only = synth.render_notes("drums", {}, ev[:1], SR, SR)
    # dopo il charleston chiuso, l'aperto e' strozzato
    coda = slice(SR // 4 + 2000, SR // 2)
    assert np.abs(y[:, coda]).max() < np.abs(open_only[:, coda]).max()


@pytest.mark.parametrize("name", list(presets.SOUNDS))
def test_every_preset_renders(name):
    s = presets.SOUNDS[name]
    pitch = 38.0 if s["category"] == "drums" else 60.0
    y = synth.render_notes(s["type"], s["params"], [(0, SR // 4, pitch, 100)], SR, SR)
    assert np.isfinite(y).all() and np.abs(y).max() > 1e-3


@pytest.mark.parametrize("name", list(fx.REGISTRY))
def test_every_effect_runs(name):
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.3, 0.3, (2, SR))
    y = fx.apply(name, x, SR, fx.validate(name, {}), {"bpm": 120, "sr": SR, "seed": 1})
    assert y.shape == x.shape and np.isfinite(y).all()


def test_lowpass_darkens():
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.5, 0.5, (2, SR))
    y = fx.apply("lowpass", x, SR, {"cutoff": 500.0}, {"bpm": 120})
    alto = lambda z: analyze.spectrum_balance(z, SR)["air"]  # noqa: E731
    assert alto(y) < alto(x) - 20


def test_limiter_holds_ceiling():
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * 997 * t)] * 2) * 2.0
    y = fx.apply("limiter", x, SR, {"ceiling_db": -1.0, "gain_db": 6.0}, {"bpm": 120})
    assert np.abs(y).max() <= 10 ** (-1 / 20) + 1e-6
    assert analyze.true_peak_db(y) < -0.5


def test_compressor_reduces_dynamics():
    t = np.arange(SR * 2) / SR
    x = np.stack([np.sin(2 * np.pi * 220 * t) * np.where(t < 1, 0.05, 0.8)] * 2)
    y = fx.apply("compressor", x, SR, {"threshold_db": -30, "ratio": 8}, {"bpm": 120})
    prima = np.abs(x[:, SR + 5000:]).max() / np.abs(x[:, 5000:SR]).max()
    dopo = np.abs(y[:, SR + 5000:]).max() / np.abs(y[:, 5000:SR]).max()
    assert dopo < prima / 2


def test_delay_echo_at_tempo():
    x = np.zeros((2, SR * 2))
    x[:, 0] = 1.0
    y = fx.apply("delay", x, SR, {"time_beats": 1.0, "feedback": 0.0, "mix": 1.0, "tone": 22050.0}, {"bpm": 120})
    picco = int(np.argmax(np.abs(y[0])))
    assert abs(picco - SR // 2) < 30   # un beat a 120 BPM = 0.5 s


def test_loudness_of_reference_tone():
    # una sinusoide 1 kHz a 0 dBFS su un canale: circa -3 LUFS (taratura EBU)
    t = np.arange(SR * 5) / SR
    x = np.stack([np.sin(2 * np.pi * 1000 * t), np.zeros_like(t)])
    assert abs(analyze.loudness(x, SR)["lufs"] - (-3.0)) < 0.5


def test_detect_tempo(click_wav):
    from medit import audio_io

    x = audio_io.load(click_wav, 22050)
    assert abs(analyze.detect_tempo(x, 22050)["bpm"] - 120) < 2


def test_detect_key_of_a_minor_chord():
    t = np.arange(SR * 4) / SR
    note = [57, 60, 64, 69, 45]
    x = sum(np.sin(2 * np.pi * synth.midi_hz(p) * t) for p in note)
    k = analyze.detect_key(np.stack([x, x]), SR)
    assert (k["key"], k["mode"]) in (("A", "minor"), ("C", "major"))


def test_render_is_pure_and_cached(store):
    store.add_drums("pop", bars=2)
    store.add_chords("Am F", bars=2)
    a = render.render(store.project, store.base_dir)
    b = render.render(store.project, store.base_dir)
    assert np.array_equal(a, b)
    render.clear_cache()
    c = render.render(store.project, store.base_dir)
    assert np.allclose(a, c, atol=1e-6)


def test_mute_and_solo(store):
    store.add_drums("pop", bars=1)
    store.add_chords("Am", bars=1)
    tutto = render.render(store.project, store.base_dir)
    store.set_track("Drums", solo=True)
    solo = render.render(store.project, store.base_dir)
    store.set_track("Drums", solo=False, mute=True)
    senza = render.render(store.project, store.base_dir)
    assert np.allclose(solo + senza, tutto, atol=1e-4)


def test_send_to_bus_adds_reverb(store):
    store.add_melody("A4:1 r:7", sound="soft lead")
    secco = render.render(store.project, store.base_dir)
    store.add_bus("Verb")
    store.set_send("Lead", "Verb", -3)
    bagnato = render.render(store.project, store.base_dir)
    coda = slice(int(SR * 0.9), int(SR * 1.5))   # dopo la nota: solo coda di riverbero
    assert np.abs(bagnato[:, coda]).mean() > np.abs(secco[:, coda]).mean() * 2


def test_automation_volume(store):
    store.add_chords("Am", bars=2, style="pad", sound="warm pad")
    store.set_automation("Chords", "volume", [[1, -60], [2, 0]])
    y = render.render(store.project, store.base_dir)
    inizio = np.abs(y[:, int(SR * 0.6):int(SR * 0.9)]).max()
    dopo = np.abs(y[:, int(SR * 2.2):int(SR * 3)]).max()
    assert dopo > inizio * 5


def test_loop_clip_repeats(store):
    tid = store.add_track(sound="pluck")["id"]
    r = store.add_clip(tid, bar=1, bars=4, notes=[["C4", 0, 0.5, 100]], loop_bars=1)
    _, c = store.project.clip(r["id"])
    ev = render.clip_note_events(store.project, c, SR)
    assert len(ev) == 4


def _sega(f, sec=2.0, sr=SR):
    t = np.arange(int(sr * sec)) / sr
    ph = f * t
    x = sum(np.sin(2 * np.pi * k * ph) / k for k in range(1, 10)) * 0.2
    return np.stack([x, x])


def _f0(y, sr=SR):
    from medit import intonazione

    f0, _ = intonazione.f0_track(y.mean(axis=0), sr)
    return float(np.median(f0[f0 > 0]))


def test_autotune_snaps_to_song_scale():
    x = _sega(452.0)                       # La crescente di ~47 cent
    ctx = {"bpm": 120, "sr": SR, "seed": 1, "key": "C", "mode": "major"}
    y = fx.apply("autotune", x, SR, fx.validate("autotune", {"speed_ms": 0}), ctx)
    assert abs(_f0(y) - 440.0) < 2.0
    # in Re# maggiore il La non c'e': va su La# (466) o Sol# (415)
    ctx2 = {**ctx, "key": "D#", "mode": "major"}
    z = fx.apply("autotune", x, SR, fx.validate("autotune", {"speed_ms": 0}), ctx2)
    assert min(abs(_f0(z) - 466.16), abs(_f0(z) - 415.3)) < 3.0


def test_autotune_amount_zero_is_dry():
    x = _sega(452.0)
    y = fx.apply("autotune", x, SR, fx.validate("autotune", {"amount": 0}), {"bpm": 120, "key": "C", "mode": "major"})
    assert abs(_f0(y) - _f0(x)) < 1.0


def test_autotune_follows_song_key_in_cache(store, tmp_path):
    from medit import audio_io

    f = tmp_path / "voce.wav"
    audio_io.write(f, _sega(452.0, 3.0, 44100), 44100, 24)
    store.add_audio(path=str(f), name="Vocals", detect=False)
    store.add_effect("Vocals", "autotune", {"speed_ms": 0})
    t = store.project.tracks[0]
    k1 = render.track_key(store.project, t, 44100, 1000, store.base_dir)
    store.project.key = "D#"
    assert render.track_key(store.project, t, 44100, 1000, store.base_dir) != k1


def test_pitch_shift_moves_pitch_up():
    x = _sega(220.0)
    for mode in ("any", "voice"):
        y = fx.apply("pitch_shift", x, SR, fx.validate("pitch_shift", {"semitones": 12, "mode": mode}), {"bpm": 120})
        assert y.shape == x.shape
        assert abs(_f0(y) - 440.0) < 8.0, mode


def test_graphic_eq_boosts_its_band():
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.3, 0.3, (2, SR))
    y = fx.apply("graphic_eq", x, SR, fx.validate("graphic_eq", {"g1k": 12}), {"bpm": 120})
    banda = lambda z: np.abs(np.fft.rfft(z[0]))[900:1100].mean()  # noqa: E731  (1 bin = 1 Hz)
    assert banda(y) > banda(x) * 2.5


def test_exciter_adds_highs():
    x = _sega(220.0)
    y = fx.apply("exciter", x, SR, fx.validate("exciter", {"amount": 1.0}), {"bpm": 120})
    alto = lambda z: analyze.spectrum_balance(z, SR)["air"]  # noqa: E731
    assert alto(y) > alto(x)


def test_transient_shaper_adds_punch():
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * 200 * t) * np.exp(-t * 3)] * 2) * 0.5
    y = fx.apply("transient", x, SR, fx.validate("transient", {"attack": 12}), {"bpm": 120})
    assert np.abs(y[:, :300]).max() > np.abs(x[:, :300]).max() * 1.5


def test_multiband_bands_sum_back():
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.05, 0.05, (2, SR))       # sotto ogni soglia: niente compressione
    sopra = {f"{b}_threshold_db": 0.0 for b in ("low", "mid", "high")}
    y = fx.apply("multiband", x, SR, fx.validate("multiband", sopra), {"bpm": 120})
    assert np.allclose(x, y, atol=1e-6)


def test_doubler_widens():
    x = _sega(220.0)
    y = fx.apply("doubler", x, SR, fx.validate("doubler", {"mix": 1.0}), {"bpm": 120})
    assert analyze.stereo(x)["correlation"] > analyze.stereo(y)["correlation"]
