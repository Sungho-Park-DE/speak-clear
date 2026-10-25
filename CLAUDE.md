# Voice Practice

A personal page for practising English speaking voice and pronunciation, plus a voice analysis tool.
Started in a claude.ai conversation and moved to Claude Code on 2026-10-17.

Personal equipment and deployment details are in `CLAUDE.local.md`, which is excluded from git.

## Goal
- **English** speaking voice first → add singing voice after 3–4 weeks. The goal is not "like a native speaker" but "easy to understand" (comprehensibility).

## Files
- `voice-practice.html`: page source. Single file, no framework. Source of the claude.ai artifact.
- `analysis/analyze_voice.py`: analysis based on Praat (parselmouth). Dependencies are inline (PEP 723), so it runs directly with `uv run`.
- `recordings/`: put recordings to analyze here. Personal voice data, so excluded from git (only `.gitkeep` is committed).
- `tests/`, `playwright.config.js`, `package.json`, `analysis/test_analyze_voice.py`: automated tests (see "Tests" below).
- `.claude/launch.json`: local preview server (`voice-practice`, http://127.0.0.1:8790).

## Artifact deployment
- The page is also deployed as a claude.ai artifact (capability `downloads`). URL and redeploy steps are in `CLAUDE.local.md`.

## Running locally
- localhost is a secure context, so microphone permission works.
- The origin differs, so recordings and logs from the artifact are not visible.
- Saving a take (`saveTake()`) uses the downloads capability inside claude.ai and `<a download>` outside it (local file, localhost).
- The preview server and browser tab may close between turns. If you cannot connect, start it again with `preview_start`.

## Tests
Run `npm install` once. Run everything with `npm test` (page, then analysis).

- `npm run test:page`: Playwright launches the installed Chrome (channel `chrome`, override with `PW_CHANNEL`). A static server starts automatically on 127.0.0.1:8791.
  - Microphone: `fakeMic()` in `tests/helpers.js` replaces `getUserMedia` inside the page with a 220 Hz (A3) OscillatorNode stream. Autoplay (`vp-autoplay`) is turned off so no sound plays.
  - Using real `getUserMedia` with Chrome's `--use-fake-device-for-media-stream` stalls at the macOS microphone permission step and opens a permission dialog, so it is not used.
  - Old recordings are inserted directly into IndexedDB with `seedTakes()`.
  - Out-of-space is simulated by calling `transaction.abort()` right after `IDBObjectStore.prototype.put` and making the `IDBTransaction.prototype.error` getter return `{name: 'QuotaExceededError'}`.
  - `tests/encoder.spec.js` extracts `encodeWav` from the page source with a regex and runs it in Node. It relies on the function ending with a `}` at the start of a line.
- `npm run test:analysis`: runs pytest via uv (`analysis/test_analyze_voice.py`). Checks a synthetic vowel (110 Hz, 5 formants), a glide (80→600 Hz), pauses and syllable count, webm/opus decoding and `@range`.

## Page structure (`voice-practice.html`)
- State object `S`. localStorage keys are `vp-*`; the daily best record is `vp-log`. IndexedDB `voice-practice` v2 (`takes`, `models`).
- UI language: bilingual (Korean/English) with a toggle button, stored in localStorage key `vp-lang`. Default is Korean if `navigator.language` starts with `ko`, otherwise English.
- Live pitch: AnalyserNode (fftSize 4096) + `yin()` (threshold 0.15), median of the last 5 frames. While recording, a MIDI value (unvoiced = -1) is pushed to `recContour` every 40 ms, and `analyze()` computes p10/p50/p90 and the number of pauses of 0.25 s or longer.
- Recording: default is **lossless WAV** (24-bit PCM, mono, AudioContext sample rate, usually 48 kHz). `capture()` collects raw floats with an AudioWorklet (blob URL module) and falls back to ScriptProcessor if blocked (CSP etc.). `encodeWav()` writes the file. Turning the toggle (`vp-wav`) off uses MediaRecorder as before (webm/opus preferred, 128 kbps, lossy).
- Storage management (WAV is about 8.6 MB per minute):
  - The line above the list (`renderStore()`) shows recording size summed by the page itself. The browser total (`navigator.storage.estimate`) shrinks late right after deletions, so it is used only in the cleanup panel, which warns above 80% of the quota.
  - "Clean up" panel (`renderClean()`, `cleanOld()`): deletes recordings older than the chosen age (`vp-clean-age`, default 30 days) in one transaction (`DB.delMany`). `take.keep` (★, `toggleKeep()`) is skipped.
  - The list shows 40 at a time and grows with "Show more" (`S.listMax`).
  - On the first successful save, `navigator.storage.persist()` is requested once (`askPersist()`, `vp-persist-asked`).
- IndexedDB writes (`DB.req`) wait for the transaction to commit or abort and record the failure reason in `DB.err`. On `QuotaExceededError` only the save is skipped (`S.idbOk` stays), a warning is shown and the cleanup panel opens. The next successful save clears the warning.
- Routine `STEPS`: breathing 1 min → SOVT 3 min → VFE 1–4 → English reading 5 min → shadowing 5 min → (after 3–4 weeks) 5-note scale. Reference notes `REF.low`: VFE1 F3, VFE4 C3–G3.
- Shadowing: TTS (`speechSynthesis`) or a native-speaker file (offline YIN, split into segments at pauses). "Intonation match %" is the Pearson r of the relative curves, each centered on its own center pitch.

## Evidence-based design decisions (check the evidence before changing)
| Decision | Evidence |
|---|---|
| No respiratory muscle training, only 1 min of relaxation | Roy et al. 2003 RCT: respiratory muscle training showed no significant improvement |
| VFE as the core routine, twice a day | Angadi, Croake & Stemple 2019 systematic review |
| SOVT (straw, lip trill, humming) only as a 3 min warm-up | Titze 2006 (mechanism), Pozzali et al. 2024 (very low quality of evidence for effect) |
| Reading aloud focuses on prosody first (stress, thought groups, intonation) | Derwing, Munro & Wiebe 1998; Field 2005; Munro & Derwing 1995 |
| "Record 3 times, then listen back together" is the default | Maas et al. 2008 (motor learning principles; limited evidence in the speech domain) |
| Shadowing + pitch curve comparison | Foote & McDonough 2017; Hardison 2004 |

The full reference list is at the bottom of the page under "Evidence for this routine".

## In progress: voice analysis
When the user provides recordings, analyze them with `analysis/analyze_voice.py` and recommend a tone direction that can be produced with less effort than the user's usual voice.

Record as WAV on the page and use the file from the save button as is (QuickTime "Maximum" or Voice Memos "Lossless" also work).

Recording protocol (5–10 cm from the microphone, quiet room, speak normally):
1. English reading: the page's Morning walk text once at normal speed
2. English free speech, 1 min (most important)
3. Korean free speech, 30 s (to compare pitch and tone across languages)
4. "Ah" at a comfortable pitch, 5 s, 3 times
5. Glide: from the lowest to the highest note, 2 times

```bash
uv run analysis/analyze_voice.py --speech recordings/en_read.m4a recordings/en_free.m4a recordings/ko_free.m4a \
  --vowel recordings/a.m4a --glide recordings/glide.m4a --json analysis/results/$(date +%F).json
uv run analysis/analyze_voice.py --segments recordings/all_in_one.m4a   # find segments when everything is in one file
# Analyze only part of a file: FILE@START-END (seconds), e.g. all_in_one.m4a@12.5-70
```

Interpretation principles: this is not a diagnosis. CPPS and HNR vary with settings, equipment and codec, so compare only recordings made under the same conditions over time. Which tone is a "good voice" is a matter of taste and is not decided by data. Data can only point to directions that are structurally less strained.

## Development methods

- **Architecture**: concept design + Let It Slop. Each folder in `analysis/modules` is one independent, replaceable module. Modules never import each other; they meet only in `analysis/syncs`. Detailed rules load from `.claude/rules/let-it-slop.md` when you work on module files, and a PostToolUse hook checks imports after every edit.
- **Designing** a new feature, service or data model: use the `concept-design` skill before writing code.
- **Changing** a module materially: write a new version with the `slop-module` skill instead of refactoring the old one.
- **TCR**: when the current branch starts with `tcr/`, a Stop hook runs `npx playwright test --max-failures=1 --reporter=dot && uv run --with pytest --with praat-parselmouth --with numpy --with av pytest -q -x analysis` at the end of every turn. Green is committed automatically and red is reverted automatically. Before editing on such a branch, read the "Working rules" section of `.claude/skills/tcr/SKILL.md`.
