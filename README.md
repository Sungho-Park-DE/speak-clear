# 목소리 연습실 (Voice Practice)

영어 말하기 발성·발음을 혼자 연습하기 위한 단일 HTML 페이지와, 녹음을 분석하는 Praat 스크립트.
목표는 "원어민처럼"이 아니라 **잘 알아듣게**(comprehensibility) 말하기다.

A single-file browser page for practising English speaking voice and prosody, plus a Praat-based analysis script. UI is in Korean.

## 기능

- **실시간 음높이**: 마이크 입력을 YIN으로 추적해 음 이름과 곡선으로 보여 준다.
- **루틴**: 호흡 이완 1분 → SOVT 3분 → Vocal Function Exercises 1–4 → 영어 낭독 → 쉐도잉. 단계마다 타이머와 기준음.
- **녹음**: 기본은 무손실 WAV(24-bit, 모노). 끄면 webm/opus. 녹음은 브라우저 IndexedDB에 저장되고 파일로 내려받을 수 있다.
- **쉐도잉**: TTS나 원어민 오디오 파일을 쉼 기준으로 나눠 따라 하고, 억양 곡선 일치도(%)를 보여 준다.
- **저장 공간 관리**: 사용량 표시, 오래된 녹음 일괄 정리(★ 표시는 보존).

루틴의 근거 문헌은 페이지 하단 "이 루틴의 근거"에 있다.

## 실행

빌드 없음. 마이크 권한은 secure context(https 또는 localhost)에서만 동작한다.

```bash
python3 -m http.server 8790 --bind 127.0.0.1
# http://127.0.0.1:8790/voice-practice.html
```

녹음과 기록은 브라우저(origin)별로 저장되며 서버로 전송되지 않는다.

## 음성 분석

[uv](https://docs.astral.sh/uv/)가 있으면 의존성(parselmouth, numpy, av)이 자동으로 설치된다.

```bash
uv run analysis/analyze_voice.py --speech recordings/en_free.wav --vowel recordings/a.wav --glide recordings/glide.wav
uv run analysis/analyze_voice.py --segments recordings/all_in_one.wav   # 한 파일 안의 구간 찾기
```

F0 분포, 쉼·음절 속도, CPPS, HNR, H1–H2, 포먼트, 음역 안에서의 위치를 잰다. **진단 도구가 아니다.** CPPS·HNR은 장비와 설정에 따라 달라지므로 같은 조건끼리 시간에 따라 비교하는 용도다.

`recordings/`는 개인 음성이라 git에서 제외된다.

## 테스트

```bash
npm install
npm test            # Playwright(설치된 Chrome) + pytest
```

페이지 테스트는 `getUserMedia`를 페이지 안의 220 Hz 발진기로 바꿔서 실제 마이크 없이 돈다. 분석 테스트는 정답을 아는 합성음(모음, 글라이드, 음절열)을 쓴다.

## 라이선스

MIT
