#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["praat-parselmouth>=0.4.3", "numpy", "av"]
# ///
"""Voice analysis (Praat / parselmouth).

    uv run analysis/analyze_voice.py --speech en_free.m4a ko_free.m4a --vowel a.m4a --glide glide.m4a
    uv run analysis/analyze_voice.py --segments all_in_one.m4a     # find segments in a single-file recording

Use FILE@START-END (seconds) to analyze only part of a file, e.g. all_in_one.m4a@12.5-70
Praat reads wav/aiff/flac/mp3 directly; m4a/mp4/webm (page recordings) are decoded with PyAV.
Not a diagnostic tool: use it to compare changes over time with the same equipment and settings.
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
    """Semitones relative to 100 Hz."""
    return 12 * np.log2(np.asarray(hz, dtype=float) / 100.0)


def med(values):
    v = [x for x in values if x is not None and not math.isnan(x)]
    return float(np.median(v)) if v else None


# ---------- Loading ----------
def load(spec):
    path, rng = spec, None
    m = re.fullmatch(r'(.+)@([\d.]+)-([\d.]+)', spec)
    if m:
        path, rng = m.group(1), (float(m.group(2)), float(m.group(3)))
    if not Path(path).is_file():
        sys.exit(f'File not found: {path}')
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


# ---------- Measurements ----------
def pitch_of(snd, lo, hi):
    p = snd.to_pitch_ac(time_step=0.01, pitch_floor=lo, pitch_ceiling=hi)
    return p, p.selected_array['frequency']


def pitch_adaptive(snd):
    """Two-pass F0 range: measure once at 50–800 Hz, then again at 0.75·Q1 to 1.5·Q3 (reduces octave errors)."""
    _, f = pitch_of(snd, 50, 800)
    v = f[f > 0]
    lo, hi = (max(40.0, 0.75 * np.percentile(v, 25)), 1.5 * np.percentile(v, 75)) if len(v) >= 20 else (60.0, 500.0)
    p, f = pitch_of(snd, lo, hi)
    return p, f, (round(lo), round(hi))


def sounding(snd, min_pause=0.25, silence_db=-25.0):
    """Sounding segments [(start, end)] found by intensity. More than 25 dB below the top-1% intensity is silence; silence of min_pause or longer is a pause."""
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
    """Number of syllable nuclei (simplified De Jong & Wempe 2009): intensity peaks above the threshold
    that dip by more than 2 dB before the next peak and are voiced."""
    pk = np.flatnonzero((db[1:-1] > db[:-2]) & (db[1:-1] >= db[2:])) + 1
    pk = pk[db[pk] > thr]
    n = 0
    for k, i in enumerate(pk):
        j = pk[k + 1] if k + 1 < len(pk) else len(db) - 1
        if db[i] - db[i:j + 1].min() > min_dip and not math.isnan(pitch.get_value_at_time(t[i])):
            n += 1
    return n


def formants(snd, pitch, ceiling):
    """Median F1–F3 over voiced frames (Burg)."""
    fm = snd.to_formant_burg(time_step=0.01, max_number_of_formants=5, maximum_formant=ceiling,
                             window_length=0.025, pre_emphasis_from=50)
    f0 = pitch.selected_array['frequency']
    vals = [[], [], []]
    for t in pitch.xs()[f0 > 0]:
        for k in range(3):
            vals[k].append(fm.get_value_at_time(k + 1, t))
    return [round(x) if x else None for x in map(med, vals)]


def cpps(snd):
    """CPPS (dB), AVQI settings (Maryn & Weenink 2015)."""
    pc = call(snd, 'To PowerCepstrogram', 60, 0.002, 5000, 50)
    return call(pc, 'Get CPPS', 'no', 0.01, 0.001, 60, 330, 0.05, 'Parabolic', 0.001, 0, 'Straight', 'Robust')


def hnr(snd):
    h = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=75, silence_threshold=0.1, periods_per_window=1.0)
    return call(h, 'Get mean', 0, 0)


def h1h2(snd, pitch):
    """Uncorrected H1–H2 (dB): per frame, difference of the spectral maxima near f0 and 2·f0 in a 4-period Hann window.
    Only meaningful for /a/ with a high F1 (a low F1 inflates H1)."""
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


# ---------- Analysis by recording type ----------
def speech(snd, ceiling=None):
    p, f, rng = pitch_adaptive(snd)
    v = f[f > 0]
    segs, (t, db, thr) = sounding(snd)
    if len(v) < 20 or not segs:
        return {'error': 'Hardly any voiced sound found'}
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
        cut = 0.1 * (e - s)                       # drop the first and last 10%, keep the stable part
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
        return {'error': 'No sustained vowel of 1 s or longer found'}
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
    p, f = pitch_of(snd, 50, 1100)                # wide enough to include falsetto
    sv = semi(f[f > 0])
    if len(sv) < 20:
        return {'error': 'No pitch found'}
    keep = [abs(sv[i] - np.median(sv[max(0, i - 2):i + 3])) < 3 for i in range(len(sv))]   # drop outliers (octave errors)
    sv = sv[keep]
    lo, hi = (100 * 2 ** (np.percentile(sv, q) / 12) for q in (1, 99))
    return {'lowest_hz': round(float(lo), 1), 'lowest_note': note(lo),
            'highest_hz': round(float(hi), 1), 'highest_note': note(hi),
            'range_st': round(float(semi(hi) - semi(lo)), 1)}


# ---------- Output ----------
def fmt_f(F):
    return '/'.join(str(x) if x else '–' for x in F)


def show(kind, name, r):
    if 'error' in r:
        print(f'\n[{kind}] {name}: {r["error"]}')
        return
    if kind == 'speech':
        print(f'\n[Speech] {name}  ({r["duration_s"]} s)')
        print(f'  Center pitch  {r["f0_median_note"]} ({r["f0_median_hz"]} Hz), 5–95%: {r["f0_p5_hz"]}–{r["f0_p95_hz"]} Hz')
        print(f'  Pitch range   {r["f0_range_st"]} st (5–95%), SD {r["f0_sd_st"]} st')
        print(f'  Speech rate   {r["speech_rate"]} syl/s (incl. pauses), articulation rate {r["articulation_rate"]} syl/s, about {r["syllables"]} syllables')
        print(f'  Pauses        {r["pauses"]} (0.25 s or longer), total {r["pause_s"]} s')
        print(f'  CPPS          {r["cpps_db"]} dB (voiced segments)')
        print(f'  Formants      F1/F2/F3 {fmt_f(r["formants_hz"])} Hz (median of voiced frames, ceiling {r["formant_ceiling"]} Hz)')
    elif kind == 'vowel':
        print(f'\n[Vowel] {name}  ({r["reps"]} reps, longest {r["longest_s"]} s)')
        print(f'  Pitch         {r["f0_median_note"]} ({r["f0_median_hz"]} Hz), wobble {r["f0_sd_cents"]} cents (SD)')
        print(f'  HNR           {r["hnr_db"]} dB')
        print(f'  CPPS          {r["cpps_db"]} dB')
        print(f'  H1–H2         {r["h1h2_db"]} dB (uncorrected)')
        print(f'  Formants      F1/F2/F3 {fmt_f(r["formants_hz"])} Hz')
    else:
        print(f'\n[Glide] {name}')
        print(f'  Range         {r["lowest_note"]} ({r["lowest_hz"]} Hz) – {r["highest_note"]} ({r["highest_hz"]} Hz), {r["range_st"]} st')


def compare(res):
    sp = [(n, r) for k, n, r in res if k == 'speech' and 'error' not in r]
    gl = [r for k, n, r in res if k == 'glide' and 'error' not in r]
    out = {}
    if len(sp) >= 2:
        n0, r0 = sp[0]
        print(f'\n[Comparison] relative to {n0}')
        out['vs_first_speech'] = []
        for n, r in sp[1:]:
            d = {'file': n, 'f0_st': round(float(semi(r['f0_median_hz']) - semi(r0['f0_median_hz'])), 1),
                 'range_st': round(r['f0_range_st'] - r0['f0_range_st'], 1),
                 'speech_rate': round(r['speech_rate'] - r0['speech_rate'], 2)}
            out['vs_first_speech'].append(d)
            print(f'  {n}: center pitch {d["f0_st"]:+} st, pitch range {d["range_st"]:+} st, speech rate {d["speech_rate"]:+} syl/s')
    if sp and gl:
        lo, hi = min(g['lowest_hz'] for g in gl), max(g['highest_hz'] for g in gl)
        span = float(semi(hi) - semi(lo))
        print(f'\n[Position in range] full range {note(lo)}–{note(hi)} ({span:.1f} st)')
        out['range_position'] = {'lowest_hz': lo, 'highest_hz': hi, 'span_st': round(span, 1), 'speech': []}
        for n, r in sp:
            pos = (float(semi(r['f0_median_hz'])) - float(semi(lo))) / span * 100
            out['range_position']['speech'].append({'file': n, 'percent_from_bottom': round(pos)})
            print(f'  {n}: center pitch {r["f0_median_note"]} is {pos:.0f}% up from the bottom')
    return out


def list_segments(spec):
    snd, name = load(spec)
    segs, _ = sounding(snd, min_pause=0.6)
    p, f = pitch_of(snd, 50, 1100)
    ts = p.xs()
    print(f'{name}  ({snd.duration:.1f} s, {len(segs)} sounding segments)')
    for s, e in segs:
        v = f[(ts >= s) & (ts <= e) & (f > 0)]
        desc = 'unvoiced or noise'
        if len(v) > 10:
            sv = semi(v)
            desc = f'center {note(np.median(v)):>4}  range {np.percentile(sv, 95) - np.percentile(sv, 5):4.1f} st  voiced {len(v) * 0.01:4.1f} s'
        print(f'  {s:7.2f}–{e:7.2f} s  ({e - s:5.1f} s)  {desc}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--speech', nargs='+', default=[], metavar='FILE', help='speech (reading aloud, free speech)')
    ap.add_argument('--vowel', nargs='+', default=[], metavar='FILE', help='sustained "ah" (several reps in one recording is fine)')
    ap.add_argument('--glide', nargs='+', default=[], metavar='FILE', help='glide from lowest to highest note')
    ap.add_argument('--segments', metavar='FILE', help='only list sounding segments in one long recording')
    ap.add_argument('--formant-ceiling', type=float, help='formant ceiling in Hz (default: 5000 if center pitch is below 165 Hz, else 5500)')
    ap.add_argument('--json', metavar='OUT', help='save results as JSON')
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
    print('\nNote: this is not a diagnosis. CPPS and HNR depend on equipment, settings and codec, so compare only recordings made under the same conditions.')
    if a.json:
        out = {'created': datetime.now().isoformat(timespec='seconds'), 'praat': parselmouth.PRAAT_VERSION,
               'files': [{'kind': k, 'file': n, **r} for k, n, r in res], **extra}
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Saved: {a.json}')


if __name__ == '__main__':
    main()
