"""analyze_voice.py 회귀 테스트: 정답을 아는 합성음으로 측정값을 확인한다.

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
    """프레임별 순간 주파수 배열 → 배음 10개짜리 신호."""
    ph = 2 * np.pi * np.cumsum(freq) / SR
    return sum(np.sin(k * ph) / k for k in range(1, 11))


def vowel(f0=110.0, dur=4.0):
    """흔들림 0.4%의 펄스열을 남성 /a/ 포먼트 5개로 거른 모음."""
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
    # glide()는 옥타브 오류를 피하려고 위아래 1%를 잘라 낸다. 한 번 훑는 글라이드에선 양끝이 2–3% 안쪽으로 나온다.
    t = np.arange(int(SR * 5)) / SR
    r = vox.glide(snd(harmonic(80 * (600 / 80) ** (t / 5))))
    assert abs(r['lowest_hz'] - 80) / 80 < 0.05
    assert abs(r['highest_hz'] - 600) / 600 < 0.05
    assert r['range_st'] > 33


def test_speech_pauses_and_syllables():
    # 세기가 4 Hz로 출렁이는 150 Hz 소리(음절 비슷) 3초 + 쉼 0.6초 + 2초 → 쉼 1회, 음절 약 20개
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
