# 목소리 연습실 (Voice Practice)

개인용 영어 말하기 발성·발음 연습 페이지와 음성 분석 도구.
claude.ai 대화에서 시작해 2026-10-17에 Claude Code로 옮겼다.

개인 장비·배포 정보는 git에서 제외한 `CLAUDE.local.md`에 있다.

## 목표
- **영어** 말하기 발성(우선) → 3–4주 뒤 노래 발성 추가. 목표는 "원어민처럼"이 아니라 "잘 알아듣게"(comprehensibility).

## 파일
- `voice-practice.html`: 페이지 원본. 단일 파일, 프레임워크 없음. claude.ai 아티팩트의 소스.
- `analysis/analyze_voice.py`: Praat(parselmouth) 기반 분석. 의존성은 PEP 723 인라인이라 `uv run`으로 바로 실행.
- `recordings/`: 분석할 녹음 파일을 두는 곳. 개인 음성이라 git에서 제외한다(`.gitkeep`만 커밋).
- `tests/`, `playwright.config.js`, `package.json`, `analysis/test_analyze_voice.py`: 자동 테스트 (아래 "테스트").
- `.claude/launch.json`: 로컬 미리보기 서버 (`voice-practice`, http://127.0.0.1:8790).

## 아티팩트 배포
- 페이지는 claude.ai 아티팩트(capability `downloads`)로도 배포한다. URL과 재배포 절차는 `CLAUDE.local.md`.

## 로컬 실행 시 주의
- localhost는 secure context라 마이크 권한이 동작한다.
- origin이 달라서 아티팩트 쪽 녹음·기록은 보이지 않는다.
- 녹음 "저장"(`saveTake()`)은 claude.ai 안에서는 downloads capability로, 밖(로컬 파일·localhost)에서는 `<a download>`로 받는다.
- 미리보기 서버와 브라우저 탭은 턴 사이에 닫힐 수 있다. 연결이 안 되면 `preview_start`로 다시 띄운다.

## 테스트
처음 한 번 `npm install`. 전체는 `npm test` (페이지 → 분석 순서).

- `npm run test:page`: Playwright가 설치된 Chrome(채널 `chrome`, `PW_CHANNEL`로 바꿀 수 있음)을 띄운다. 정적 서버는 127.0.0.1:8791에서 자동으로 뜬다.
  - 마이크: `tests/helpers.js`의 `fakeMic()`이 페이지 안에서 `getUserMedia`를 220 Hz(A3) OscillatorNode 스트림으로 바꾼다. 자동 재생(`vp-autoplay`)은 꺼서 소리가 나지 않게 한다.
  - Chrome의 `--use-fake-device-for-media-stream`으로 진짜 `getUserMedia`를 쓰면 macOS 마이크 권한 단계에서 멈추고 권한 창이 뜬다. 그래서 쓰지 않는다.
  - 오래된 녹음은 `seedTakes()`로 IndexedDB에 직접 넣는다.
  - 공간 부족은 `IDBObjectStore.prototype.put` 직후 `transaction.abort()`를 하고, `IDBTransaction.prototype.error` getter가 `{name: 'QuotaExceededError'}`를 돌려주게 해서 흉내 낸다.
  - `tests/encoder.spec.js`는 페이지 소스에서 `encodeWav`를 정규식으로 꺼내 Node에서 돌린다. 함수가 줄 맨 앞의 `}`로 끝나는 형식에 의존한다.
- `npm run test:analysis`: uv로 pytest를 돌린다(`analysis/test_analyze_voice.py`). 합성 모음(110 Hz, 포먼트 5개), 글라이드(80→600 Hz), 쉼·음절 수, webm/opus 디코딩과 `@구간`을 확인한다.

## 페이지 구조 (`voice-practice.html`)
- 상태 객체 `S`. localStorage 키는 `vp-*`, 일별 최고 기록은 `vp-log`. IndexedDB `voice-practice` v2 (`takes`, `models`).
- 실시간 음높이: AnalyserNode(fftSize 4096) + `yin()`(임계 0.15), 최근 5프레임 중앙값. 녹음 중 40 ms마다 MIDI 값(무성 = -1)을 `recContour`에 쌓고, `analyze()`가 p10/p50/p90과 0.25 s 이상 쉼 횟수를 계산.
- 녹음: 기본은 **무손실 WAV** (24-bit PCM, 모노, AudioContext 샘플레이트, 보통 48 kHz). `capture()`가 AudioWorklet(blob URL 모듈)로 원본 float를 모으고, 막히면(CSP 등) ScriptProcessor로 대신한다. `encodeWav()`가 파일로 쓴다. 토글(`vp-wav`)을 끄면 예전처럼 MediaRecorder(webm/opus 우선, 128 kbps, 손실 압축).
- 저장 공간 관리 (WAV는 1분에 약 8.6 MB):
  - 목록 위 줄(`renderStore()`)은 페이지가 직접 더한 녹음 용량을 보여 준다. 브라우저 집계(`navigator.storage.estimate`)는 지운 직후에 늦게 줄어들어서 정리 창에만 쓰고, 한도의 80%를 넘으면 경고한다.
  - "정리" 창(`renderClean()`, `cleanOld()`): 고른 기간(`vp-clean-age`, 기본 30일)보다 오래된 녹음을 한 트랜잭션으로 지운다(`DB.delMany`). `take.keep`(★, `toggleKeep()`)은 빠진다.
  - 목록은 40개씩 보여 주고 "더 보기"로 늘린다(`S.listMax`).
  - 첫 저장 성공 때 `navigator.storage.persist()`를 한 번만 요청한다(`askPersist()`, `vp-persist-asked`).
- IndexedDB 쓰기(`DB.req`)는 트랜잭션 커밋이나 중단까지 기다리고, 실패 이유를 `DB.err`에 남긴다. `QuotaExceededError`면 저장만 건너뛰고(`S.idbOk` 유지) 경고와 함께 정리 창을 연다. 다음 저장이 성공하면 경고를 지운다.
- 루틴 `STEPS`: 호흡 1분 → SOVT 3분 → VFE 1–4 → 영어 낭독 5분 → 쉐도잉 5분 → (3–4주 뒤) 5음 스케일. 기준음 `REF.low`: VFE1 F3, VFE4 C3–G3.
- 쉐도잉: TTS(`speechSynthesis`) 또는 원어민 파일(오프라인 YIN, 쉼 기준으로 구간 분할). "억양 일치 %"는 각자 중심음 기준 상대 곡선의 Pearson r.

## 근거 기반 설계 결정 (바꾸기 전에 근거부터 확인)
| 결정 | 근거 |
|---|---|
| 호흡근 훈련은 빼고 1분 이완만 | Roy et al. 2003 RCT: 호흡근 훈련은 유의한 개선 없음 |
| VFE를 핵심 루틴으로, 하루 2회 | Angadi, Croake & Stemple 2019 체계적 문헌고찰 |
| SOVT(빨대·립트릴·허밍)는 3분 워밍업만 | Titze 2006(원리), Pozzali et al. 2024(효과 근거의 질 매우 낮음) |
| 낭독 초점은 운율(강세·의미 덩어리·억양) 우선 | Derwing, Munro & Wiebe 1998; Field 2005; Munro & Derwing 1995 |
| "3번 녹음 후 몰아 듣기"가 기본값 | Maas et al. 2008(운동 학습 원리, 말 영역 근거는 제한적) |
| 쉐도잉 + 음높이 곡선 비교 | Foote & McDonough 2017; Hardison 2004 |

전체 참고문헌은 페이지 하단 "이 루틴의 근거"에 있다.

## 진행 중: 목소리 분석
사용자가 녹음을 주면 `analysis/analyze_voice.py`로 분석하고, 평소 목소리에서 힘을 덜 들이고 낼 수 있는 톤 방향을 추천한다.

녹음은 페이지에서 WAV로 하고 저장 버튼으로 받은 파일을 그대로 쓰면 된다 (QuickTime "최대"나 음성 메모 "무손실"도 가능).

녹음 프로토콜 (마이크에서 5–10 cm, 조용한 방, 평소처럼):
1. 영어 낭독: 페이지의 Morning walk를 평소 속도로 1회
2. 영어 자유 발화 1분 (가장 중요)
3. 한국어 자유 발화 30초 (언어별 음높이·톤 비교용)
4. "아—" 편한 높이로 5초씩 3회
5. 글라이드: 가장 낮은 음에서 가장 높은 음까지 2회

```bash
uv run analysis/analyze_voice.py --speech recordings/en_read.m4a recordings/en_free.m4a recordings/ko_free.m4a \
  --vowel recordings/a.m4a --glide recordings/glide.m4a --json analysis/results/$(date +%F).json
uv run analysis/analyze_voice.py --segments recordings/all_in_one.m4a   # 한 파일로 녹음했을 때 구간 찾기
# 일부 구간만 분석: FILE@START-END (초), 예: all_in_one.m4a@12.5-70
```

해석 원칙: 진단이 아니다. CPPS·HNR은 설정·장비·코덱에 따라 값이 달라지므로 같은 조건끼리 시간에 따라 비교한다. 어떤 톤이 "좋은 목소리"인지는 취향이라 데이터로 정하지 않는다. 데이터로 말할 수 있는 건 구조적으로 덜 무리하는 방향뿐이다.

## Development methods

- **Architecture**: concept design + Let It Slop. Each folder in `analysis/modules` is one independent, replaceable module. Modules never import each other; they meet only in `analysis/syncs`. Detailed rules load from `.claude/rules/let-it-slop.md` when you work on module files, and a PostToolUse hook checks imports after every edit.
- **Designing** a new feature, service or data model: use the `concept-design` skill before writing code.
- **Changing** a module materially: write a new version with the `slop-module` skill instead of refactoring the old one.
- **TCR**: when the current branch starts with `tcr/`, a Stop hook runs `npx playwright test --max-failures=1 --reporter=dot && uv run --with pytest --with praat-parselmouth --with numpy --with av pytest -q -x analysis` at the end of every turn. Green is committed automatically and red is reverted automatically. Before editing on such a branch, read the "Working rules" section of `.claude/skills/tcr/SKILL.md`.
