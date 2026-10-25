"""Regression tests for analyze_voice.py: check measurements on synthetic sounds with known answers.

    npm run test:analysis
"""
import numpy as np
import parselmouth
from parselmouth.praat import call

import analyze_voice as vox

SR = 44100
RNG = np.random.default_rng(0)


def snd(y, sr=SR):
    return parselmouth.Sound(y / np.abs(y).max() * 0.5, sampling_frequency=sr)


def harmonic(freq):
    """Per-sample instantaneous frequency array -> signal with 10 harmonics."""
    ph = 2 * np.pi * np.cumsum(freq) / SR
    return sum(np.sin(k * ph) / k for k in range(1, 11))


def vowel(f0=110.0, dur=4.0):
    """Pulse train with 0.4% jitter, filtered through 5 formants of a male /a/."""
    x = np.zeros(int(SR * dur))
    t = 0.0
    while t < dur:
        x[min(int(t * SR), len(x) - 1)] = 1.0
        t += (1 / f0) * (1 + RNG.normal(0, 0.004))
    s = parselmouth.Sound(x, sampling_frequency=SR)
    for f, b in ((700, 80), (1220, 90), (2600, 120), (3300, 150), (3750, 200)):
        s = call(s, 'Filter (one formant)...', f, b)
    return snd(s.values[0] + RNG.normal(0, 0.004, s.values.shape[1]))


def test_vowel_f0_and_formants():
    r = vox.vowel(vowel())
    assert abs(r['f0_median_hz'] - 110) < 1
    f1, f2, f3 = r['formants_hz']
    assert abs(f1 - 700) / 700 < 0.10
    assert abs(f2 - 1220) / 1220 < 0.05
    assert abs(f3 - 2600) / 2600 < 0.05


def test_glide_range():
    # glide() trims the top and bottom 1% to avoid octave errors. On a single sweep the ends come out 2–3% inside.
    t = np.arange(int(SR * 5)) / SR
    r = vox.glide(snd(harmonic(80 * (600 / 80) ** (t / 5))))
    assert abs(r['lowest_hz'] - 80) / 80 < 0.05
    assert abs(r['highest_hz'] - 600) / 600 < 0.05
    assert r['range_st'] > 33


def test_speech_pauses_and_syllables():
    # 150 Hz tone with 4 Hz intensity modulation (syllable-like): 3 s + 0.6 s pause + 2 s -> 1 pause, about 20 syllables
    def burst(sec):
        t = np.arange(int(SR * sec)) / SR
        return harmonic(np.full(t.shape, 150.0)) * (0.55 - 0.45 * np.cos(2 * np.pi * 4 * t))
    y = np.concatenate([burst(3), np.zeros(int(SR * 0.6)), burst(2)])
    r = vox.speech(snd(y + RNG.normal(0, 1e-4, len(y))))
    assert r['pauses'] == 1
    assert 17 <= r['syllables'] <= 23
    assert abs(r['f0_median_hz'] - 150) < 2


def test_load_decodes_webm_opus(tmp_path):
    import av
    x = (vowel(dur=2.0).resample(48000).values[0] * 32767).astype(np.int16)
    path = tmp_path / 'take.webm'
    with av.open(str(path), 'w', format='webm') as out:
        st = out.add_stream('libopus', rate=48000, layout='mono')
        st.bit_rate = 128000
        for i in range(0, len(x), 960):
            fr = av.AudioFrame.from_ndarray(x[i:i + 960].reshape(1, -1), format='s16', layout='mono')
            fr.sample_rate = 48000
            for p in st.encode(fr):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    loaded, name = vox.load(f'{path}@0.2-1.8')
    assert name == 'take.webm@0.2-1.8'
    assert abs(loaded.duration - 1.6) < 0.05
    assert abs(vox.vowel(loaded)['f0_median_hz'] - 110) < 1
