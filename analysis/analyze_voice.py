#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["praat-parselmouth>=0.4.3", "numpy", "av"]
# ///
"""목소리 분석 (Praat / parselmouth).

    uv run analysis/analyze_voice.py --speech en_free.m4a ko_free.m4a --vowel a.m4a --glide glide.m4a
    uv run analysis/analyze_voice.py --segments all_in_one.m4a     # 한 파일 녹음에서 구간 찾기

FILE@START-END(초)로 일부 구간만 분석한다. 예: all_in_one.m4a@12.5-70
wav/aiff/flac/mp3는 Praat가 바로 읽고, m4a/mp4/webm(페이지 녹음)은 PyAV로 디코딩한다.
진단용이 아니라 같은 장비·설정에서 시간에 따른 변화를 비교하는 용도다.
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note(hz):
    m = round(69 + 12 * math.log2(hz / 440))
    return f'{NOTES[m % 12]}{m // 12 - 1}'


def semi(hz):
    """100 Hz 기준 반음."""
    return 12 * np.log2(np.asarray(hz, dtype=float) / 100.0)


def med(values):
    v = [x for x in values if x is not None and not math.isnan(x)]
    return float(np.median(v)) if v else None


# ---------- 읽기 ----------
def load(spec):
    path, rng = spec, None
    m = re.fullmatch(r'(.+)@([\d.]+)-([\d.]+)', spec)
    if m:
        path, rng = m.group(1), (float(m.group(2)), float(m.group(3)))
    if not Path(path).is_file():
        sys.exit(f'파일이 없어요: {path}')
    try:
        snd = parselmouth.Sound(path)
    except parselmouth.PraatError:
        snd = decode(path)
    if snd.n_channels > 1:
        snd = snd.convert_to_mono()
    if rng:
        snd = snd.extract_part(rng[0], min(rng[1], snd.xmax))
    return snd, Path(path).name + (f'@{m.group(2)}-{m.group(3)}' if rng else '')


def decode(path):
    import av
    with av.open(path) as box:
        stream = box.streams.audio[0]
        sr = stream.codec_context.sample_rate or 48000
        rs = av.AudioResampler(format='flt', layout='mono', rate=sr)
        chunks = []
        for frame in box.decode(stream):
            chunks += [f.to_ndarray().ravel() for f in rs.resample(frame)]
        chunks += [f.to_ndarray().ravel() for f in rs.resample(None)]
    return parselmouth.Sound(np.concatenate(chunks).astype(np.float64), sampling_frequency=sr)


# ---------- 측정 ----------
def pitch_of(snd, lo, hi):
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=lo, pitch_ceiling=hi)
    return p, p.selected_array['frequency']


def pitch_adaptive(snd):
    """F0 범위 2단계 추정: 50–800 Hz로 한 번 잰 뒤 0.75·Q1 ~ 1.5·Q3로 다시 잰다 (옥타브 오류 줄이기)."""
    _, f = pitch_of(snd, 50, 800)
    v = f[f > 0]
    lo, hi = (max(40.0, 0.75 * np.percentile(v, 25)), 1.5 * np.percentile(v, 75)) if len(v) >= 20 else (60.0, 500.0)
    p, f = pitch_of(snd, lo, hi)
    return p, f, (round(lo), round(hi))


def sounding(snd, min_pause=0.25, silence_db=-25.0):
    """세기로 찾은 발성 구간 [(시작, 끝)]. 상위 1% 세기보다 25 dB 넘게 작으면 조용함, 그게 min_pause 이상이면 쉼."""
    it = snd.to_intensity(minimum_pitch=50, time_step=0.01)
    t, db = it.xs(), it.values[0]
    thr = max(np.percentile(db, 99) + silence_db, db.min())
    edges = np.flatnonzero(np.diff(np.r_[0, (db > thr).astype(int), 0]))
    segs = []
    for a, b in zip(edges[::2], edges[1::2]):
        s, e = t[a] - 0.005, t[b - 1] + 0.005
        if segs and s - segs[-1][1] < min_pause:
            segs[-1][1] = e
        else:
            segs.append([s, e])
    segs = [(max(s, snd.xmin), min(e, snd.xmax)) for s, e in segs if e - s >= 0.08]
    return segs, (t, db, thr)


def syllables(t, db, thr, pitch, min_dip=2.0):
    """음절핵 수 (De Jong & Wempe 2009 방식 간소화): 임계 위 세기 봉우리 가운데
    다음 봉우리까지 2 dB 넘게 꺼지고, 그 지점이 유성인 것."""
    pk = np.flatnonzero((db[1:-1] > db[:-2]) & (db[1:-1] >= db[2:])) + 1
    pk = pk[db[pk] > thr]
    n = 0
    for k, i in enumerate(pk):
        j = pk[k + 1] if k + 1 < len(pk) else len(db) - 1
        if db[i] - db[i:j + 1].min() > min_dip and not math.isnan(pitch.get_value_at_time(t[i])):
            n += 1
    return n


def formants(snd, pitch, ceiling):
    """유성 프레임의 F1–F3 중앙값 (Burg)."""
    fm = snd.to_formant_burg(time_step=0.01, max_number_of_formants=5, maximum_formant=ceiling,
                             window_length=0.025, pre_emphasis_from=50)
    f0 = pitch.selected_array['frequency']
    vals = [[], [], []]
    for t in pitch.xs()[f0 > 0]:
        for k in range(3):
            vals[k].append(fm.get_value_at_time(k + 1, t))
    return [round(x) if x else None for x in map(med, vals)]


def cpps(snd):
    """CPPS (dB), AVQI 설정 (Maryn & Weenink 2015)."""
    pc = call(snd, 'To PowerCepstrogram', 60, 0.002, 5000, 50)
    return call(pc, 'Get CPPS', 'no', 0.01, 0.001, 60, 330, 0.05, 'Parabolic', 0.001, 0, 'Straight', 'Robust')


def hnr(snd):
    h = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=75, silence_threshold=0.1, periods_per_window=1.0)
    return call(h, 'Get mean', 0, 0)


def h1h2(snd, pitch):
    """보정하지 않은 H1–H2 (dB). 프레임마다 4주기 Hann 창 스펙트럼에서 f0와 2·f0 근처 최댓값의 차이.
    F1이 높은 /a/에서만 의미가 있다 (F1이 낮으면 H1이 부풀려짐)."""
    x, sr = snd.values[0], snd.sampling_frequency
    out = []
    for t, f in zip(pitch.xs(), pitch.selected_array['frequency']):
        if f <= 0:
            continue
        n = int(sr * max(0.04, 4 / f))
        a = int((t - snd.xmin) * sr) - n // 2
        if a < 0 or a + n > len(x):
            continue
        nfft = 1 << math.ceil(math.log2(n * 4))
        spec = 20 * np.log10(np.abs(np.fft.rfft(x[a:a + n] * np.hanning(n), nfft)) + 1e-12)
        fr = np.fft.rfftfreq(nfft, 1 / sr)
        peak = lambda fc: spec[(fr >= 0.9 * fc) & (fr <= 1.1 * fc)].max()
        out.append(peak(f) - peak(2 * f))
    return med(out)


# ---------- 종류별 분석 ----------
def speech(snd, ceiling=None):
    p, f, rng = pitch_adaptive(snd)
    v = f[f > 0]
    segs, (t, db, thr) = sounding(snd)
    if len(v) < 20 or not segs:
        return {'error': '유성음을 거의 찾지 못했어요'}
    sv = semi(v)
    span = segs[-1][1] - segs[0][0]
    phon = sum(e - s for s, e in segs)
    nsyl = syllables(t, db, thr, p)
    f0 = float(np.median(v))
    ceiling = ceiling or (5000 if f0 < 165 else 5500)
    voiced = parselmouth.Sound.concatenate([snd.extract_part(s, e) for s, e in segs])
    return {
        'duration_s': round(snd.duration, 1),
        'f0_median_hz': round(f0, 1), 'f0_median_note': note(f0),
        'f0_p5_hz': round(float(np.percentile(v, 5)), 1), 'f0_p95_hz': round(float(np.percentile(v, 95)), 1),
        'f0_range_st': round(float(np.percentile(sv, 95) - np.percentile(sv, 5)), 1),
        'f0_sd_st': round(float(np.std(sv)), 2),
        'pauses': len(segs) - 1, 'pause_s': round(span - phon, 1),
        'syllables': nsyl, 'speech_rate': round(nsyl / span, 2), 'articulation_rate': round(nsyl / phon, 2),
        'cpps_db': round(cpps(voiced), 2),
        'formants_hz': formants(snd, p, ceiling), 'formant_ceiling': ceiling,
        'pitch_range_used': rng,
    }


def vowel(snd, ceiling=None):
    segs, _ = sounding(snd, min_pause=0.3)
    reps = [(s, e) for s, e in segs if e - s >= 1.0] or [(snd.xmin, snd.xmax)]
    rows = []
    for s, e in reps:
        cut = 0.1 * (e - s)                       # 시작·끝 10%는 버리고 안정 구간만
        core = snd.extract_part(s + cut, e - cut)
        p, f, _ = pitch_adaptive(core)
        v = f[f > 0]
        if len(v) < 20:
            continue
        f0 = float(np.median(v))
        rows.append({'dur': e - s, 'f0': f0, 'sd_cents': float(np.std(1200 * np.log2(v / f0))),
                     'hnr': hnr(core), 'cpps': cpps(core), 'h1h2': h1h2(core, p),
                     'F': formants(core, p, ceiling or (5000 if f0 < 165 else 5500))})
    if not rows:
        return {'error': '1초 이상 길게 낸 모음을 찾지 못했어요'}
    col = lambda k: med([r[k] for r in rows])
    rnd = lambda x, d: None if x is None else round(x, d)
    f0 = col('f0')
    return {
        'reps': len(rows), 'longest_s': round(max(r['dur'] for r in rows), 1),
        'f0_median_hz': round(f0, 1), 'f0_median_note': note(f0), 'f0_sd_cents': rnd(col('sd_cents'), 0),
        'hnr_db': rnd(col('hnr'), 1), 'cpps_db': rnd(col('cpps'), 2), 'h1h2_db': rnd(col('h1h2'), 1),
        'formants_hz': [None if (x := med([r['F'][i] for r in rows])) is None else round(x) for i in range(3)],
    }


def glide(snd):
    p, f = pitch_of(snd, 50, 1100)                # 가성까지 넓게
    sv = semi(f[f > 0])
    if len(sv) < 20:
        return {'error': '음높이를 찾지 못했어요'}
    keep = [abs(sv[i] - np.median(sv[max(0, i - 2):i + 3])) < 3 for i in range(len(sv))]   # 튀는 값(옥타브 오류) 제거
    sv = sv[keep]
    lo, hi = (100 * 2 ** (np.percentile(sv, q) / 12) for q in (1, 99))
    return {'lowest_hz': round(float(lo), 1), 'lowest_note': note(lo),
            'highest_hz': round(float(hi), 1), 'highest_note': note(hi),
            'range_st': round(float(semi(hi) - semi(lo)), 1)}


# ---------- 출력 ----------
def fmt_f(F):
    return '/'.join(str(x) if x else '–' for x in F)


def show(kind, name, r):
    if 'error' in r:
        print(f'\n[{kind}] {name}: {r["error"]}')
        return
    if kind == 'speech':
        print(f'\n[말하기] {name}  ({r["duration_s"]}초)')
        print(f'  중심음      {r["f0_median_note"]} ({r["f0_median_hz"]} Hz), 5–95%: {r["f0_p5_hz"]}–{r["f0_p95_hz"]} Hz')
        print(f'  억양 폭     {r["f0_range_st"]}반음 (5–95%), 표준편차 {r["f0_sd_st"]}반음')
        print(f'  말 속도     {r["speech_rate"]} 음절/초 (쉼 포함), 조음 속도 {r["articulation_rate"]} 음절/초, 음절 약 {r["syllables"]}개')
        print(f'  쉼          {r["pauses"]}회 (0.25초 이상), 합계 {r["pause_s"]}초')
        print(f'  CPPS        {r["cpps_db"]} dB (유성 구간)')
        print(f'  포먼트      F1/F2/F3 {fmt_f(r["formants_hz"])} Hz (유성 프레임 중앙값, 상한 {r["formant_ceiling"]} Hz)')
    elif kind == 'vowel':
        print(f'\n[모음] {name}  ({r["reps"]}회, 가장 긴 것 {r["longest_s"]}초)')
        print(f'  음높이      {r["f0_median_note"]} ({r["f0_median_hz"]} Hz), 흔들림 {r["f0_sd_cents"]}센트 (표준편차)')
        print(f'  HNR         {r["hnr_db"]} dB')
        print(f'  CPPS        {r["cpps_db"]} dB')
        print(f'  H1–H2       {r["h1h2_db"]} dB (보정 전)')
        print(f'  포먼트      F1/F2/F3 {fmt_f(r["formants_hz"])} Hz')
    else:
        print(f'\n[글라이드] {name}')
        print(f'  음역        {r["lowest_note"]} ({r["lowest_hz"]} Hz) – {r["highest_note"]} ({r["highest_hz"]} Hz), {r["range_st"]}반음')


def compare(res):
    sp = [(n, r) for k, n, r in res if k == 'speech' and 'error' not in r]
    gl = [r for k, n, r in res if k == 'glide' and 'error' not in r]
    out = {}
    if len(sp) >= 2:
        n0, r0 = sp[0]
        print(f'\n[비교] {n0} 기준')
        out['vs_first_speech'] = []
        for n, r in sp[1:]:
            d = {'file': n, 'f0_st': round(float(semi(r['f0_median_hz']) - semi(r0['f0_median_hz'])), 1),
                 'range_st': round(r['f0_range_st'] - r0['f0_range_st'], 1),
                 'speech_rate': round(r['speech_rate'] - r0['speech_rate'], 2)}
            out['vs_first_speech'].append(d)
            print(f'  {n}: 중심음 {d["f0_st"]:+}반음, 억양 폭 {d["range_st"]:+}반음, 말 속도 {d["speech_rate"]:+} 음절/초')
    if sp and gl:
        lo, hi = min(g['lowest_hz'] for g in gl), max(g['highest_hz'] for g in gl)
        span = float(semi(hi) - semi(lo))
        print(f'\n[음역 안 위치] 전체 음역 {note(lo)}–{note(hi)} ({span:.1f}반음)')
        out['range_position'] = {'lowest_hz': lo, 'highest_hz': hi, 'span_st': round(span, 1), 'speech': []}
        for n, r in sp:
            pos = (float(semi(r['f0_median_hz'])) - float(semi(lo))) / span * 100
            out['range_position']['speech'].append({'file': n, 'percent_from_bottom': round(pos)})
            print(f'  {n}: 중심음 {r["f0_median_note"]}는 아래에서 {pos:.0f}% 지점')
    return out


def list_segments(spec):
    snd, name = load(spec)
    segs, _ = sounding(snd, min_pause=0.6)
    p, f = pitch_of(snd, 50, 1100)
    ts = p.xs()
    print(f'{name}  ({snd.duration:.1f}초, 발성 구간 {len(segs)}개)')
    for s, e in segs:
        v = f[(ts >= s) & (ts <= e) & (f > 0)]
        desc = '무성 또는 잡음'
        if len(v) > 10:
            sv = semi(v)
            desc = f'중심음 {note(np.median(v)):>4}  폭 {np.percentile(sv, 95) - np.percentile(sv, 5):4.1f}반음  유성 {len(v) * 0.01:4.1f}초'
        print(f'  {s:7.2f}–{e:7.2f}초  ({e - s:5.1f}초)  {desc}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--speech', nargs='+', default=[], metavar='FILE', help='말하기 (낭독, 자유 발화)')
    ap.add_argument('--vowel', nargs='+', default=[], metavar='FILE', help='길게 낸 "아—" (여러 번 이어서 녹음해도 됨)')
    ap.add_argument('--glide', nargs='+', default=[], metavar='FILE', help='최저음에서 최고음까지 글라이드')
    ap.add_argument('--segments', metavar='FILE', help='긴 녹음 하나에서 발성 구간 목록만 출력')
    ap.add_argument('--formant-ceiling', type=float, help='포먼트 상한 Hz (기본: 중심음 165 Hz 미만이면 5000, 아니면 5500)')
    ap.add_argument('--json', metavar='OUT', help='결과를 JSON으로 저장')
    a = ap.parse_args()
    if a.segments:
        list_segments(a.segments)
        return
    jobs = [('speech', f) for f in a.speech] + [('vowel', f) for f in a.vowel] + [('glide', f) for f in a.glide]
    if not jobs:
        ap.print_help()
        return
    res = []
    for kind, spec in jobs:
        snd, name = load(spec)
        r = speech(snd, a.formant_ceiling) if kind == 'speech' else vowel(snd, a.formant_ceiling) if kind == 'vowel' else glide(snd)
        res.append((kind, name, r))
        show(kind, name, r)
    extra = compare(res)
    print('\n참고: 진단이 아니에요. CPPS·HNR은 장비·설정·코덱에 따라 달라지니 같은 조건끼리 비교하세요.')
    if a.json:
        out = {'created': datetime.now().isoformat(timespec='seconds'), 'praat': parselmouth.PRAAT_VERSION,
               'files': [{'kind': k, 'file': n, **r} for k, n, r in res], **extra}
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'저장: {a.json}')


if __name__ == '__main__':
    main()
