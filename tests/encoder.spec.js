import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// 페이지 안의 encodeWav를 소스에서 그대로 꺼내 Node에서 돌린다 (브라우저 없이).
const html = readFileSync(new URL('../voice-practice.html', import.meta.url), 'utf8');
const encodeWav = new Function(html.match(/function encodeWav\(chunks, sr\) \{[\s\S]*?\n\}/)[0] + '; return encodeWav;')();

const sample24 = (buf, i) => {
  const v = buf[44 + 3 * i] | (buf[45 + 3 * i] << 8) | (buf[46 + 3 * i] << 16);
  return v & 0x800000 ? v - 0x1000000 : v;
};

test('encodeWav는 24-bit PCM WAV를 비트 단위까지 정확하게 쓴다', async () => {
  const sr = 48000, x = new Float32Array(9000);
  for (let i = 0; i < x.length; i++) x[i] = 0.6 * Math.sin(2 * Math.PI * 220 * i / sr);
  Object.assign(x, { 0: 1, 1: -1, 2: 1.5, 3: -1.5, 4: 0, 5: -1 / 8388607 });   // 경계값, 클리핑, 음수
  const buf = Buffer.from(await encodeWav([x.subarray(0, 4096), x.subarray(4096)], sr).arrayBuffer());
  expect(buf.toString('ascii', 0, 4)).toBe('RIFF');
  expect([buf.readUInt16LE(20), buf.readUInt16LE(22), buf.readUInt32LE(24), buf.readUInt16LE(34), buf.readUInt32LE(40)])
    .toEqual([1, 1, sr, 24, x.length * 3]);
  let bad = 0;
  for (let i = 0; i < x.length; i++) if (sample24(buf, i) !== Math.round(Math.max(-1, Math.min(1, x[i])) * 8388607)) bad++;
  expect(bad).toBe(0);
});

test('encodeWav는 홀수 길이 데이터를 패딩하고, 빈 입력은 빈 Blob을 돌려준다', async () => {
  const odd = Buffer.from(await encodeWav([new Float32Array(3)], 48000).arrayBuffer());
  expect([odd.length, odd.readUInt32LE(4), odd.readUInt32LE(40)]).toEqual([54, 46, 9]);
  expect(encodeWav([], 48000).size).toBe(0);
});
