# Voice Practice

A single HTML page for practising English speaking voice and pronunciation on your own, plus a Praat script that analyzes recordings.
The goal is not to sound "like a native speaker" but to be **easy to understand** (comprehensibility).

The UI is bilingual (Korean/English) with a language toggle.

## Features

- **Live pitch**: tracks microphone input with YIN and shows the note name and a pitch curve.
- **Routine**: 1 min breathing/relaxation → 3 min SOVT → Vocal Function Exercises 1–4 → English reading aloud → shadowing. Each step has a timer and reference notes.
- **Recording**: lossless WAV (24-bit, mono) by default; switch it off for webm/opus. Recordings are stored in the browser's IndexedDB and can be downloaded as files.
- **Shadowing**: splits TTS or a native-speaker audio file at pauses so you can repeat after it, and shows how well your intonation curve matches (%).
- **Storage management**: shows usage and bulk-deletes old recordings (★-marked ones are kept).

The evidence for the routine is listed at the bottom of the page under "Evidence for this routine".

## Running

No build step. Microphone access only works in a secure context (https or localhost).

```bash
python3 -m http.server 8790 --bind 127.0.0.1
# http://127.0.0.1:8790/voice-practice.html
```

Recordings and logs are stored per browser (origin) and are never sent to a server.

## Voice analysis

With [uv](https://docs.astral.sh/uv/), dependencies (parselmouth, numpy, av) are installed automatically.

```bash
uv run analysis/analyze_voice.py --speech recordings/en_free.wav --vowel recordings/a.wav --glide recordings/glide.wav
uv run analysis/analyze_voice.py --segments recordings/all_in_one.wav   # find segments inside one file
```

Measures F0 distribution, pauses and syllable rate, CPPS, HNR, H1–H2, formants, and where your speaking pitch sits within your range. **It is not a diagnostic tool.** CPPS and HNR vary with equipment and settings, so use them to compare recordings made under the same conditions over time.

`recordings/` holds personal voice data and is excluded from git.

## Tests

```bash
npm install
npm test            # Playwright (installed Chrome) + pytest
```

Page tests replace `getUserMedia` with a 220 Hz oscillator inside the page, so they run without a real microphone. Analysis tests use synthetic sounds with known answers (vowel, glide, syllable train).

## License

MIT
