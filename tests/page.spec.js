import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { openPage, micOn, record, idbIds, newestTake, seedTakes } from './helpers.js';

const between = (x, lo, hi) => { expect(x).toBeGreaterThan(lo); expect(x).toBeLessThan(hi); };

test.describe('녹음', () => {
  test('기본은 AudioWorklet으로 24-bit WAV를 저장한다', async ({ page }) => {
    await openPage(page, () => {
      window.__cap = { worklet: 0, script: 0 };
      const am = AudioWorklet.prototype.addModule;
      AudioWorklet.prototype.addModule = function (...a) { window.__cap.worklet++; return am.apply(this, a); };
      const sp = AudioContext.prototype.createScriptProcessor;
      AudioContext.prototype.createScriptProcessor = function (...a) { window.__cap.script++; return sp.apply(this, a); };
    });
    await expect(page.locator('#wavRec')).toBeChecked();
    await micOn(page);
    await expect(page.locator('#hNote')).toHaveText('A3');
    await record(page, 2000);
    const t = await newestTake(page);
    expect(t).toMatchObject({ mime: 'audio/wav', fmt: 1, ch: 1, bits: 24 });
    between(t.hz, 215, 225);
    between(t.dur, 1.8, 2.5);
    expect(await page.evaluate(() => window.__cap)).toEqual({ worklet: 1, script: 0 });
    await expect(page.locator('#takeList .take .chips').first()).toContainText('WAV');
    expect(await page.evaluate(() => localStorage.getItem('vp-persist-asked'))).toBe('true');
  });

  test('AudioWorklet이 막히면 ScriptProcessor로 WAV를 저장한다', async ({ page }) => {
    await openPage(page, () => {
      window.__script = 0;
      const sp = AudioContext.prototype.createScriptProcessor;
      AudioContext.prototype.createScriptProcessor = function (...a) { window.__script++; return sp.apply(this, a); };
      window.AudioWorkletNode = undefined;
    });
    await micOn(page);
    await record(page, 1500);
    const t = await newestTake(page);
    expect(t).toMatchObject({ mime: 'audio/wav', bits: 24 });
    between(t.hz, 215, 225);
    expect(await page.evaluate(() => window.__script)).toBe(1);
  });

  test('WAV를 끄면 압축(webm) 녹음으로 돌아간다', async ({ page }) => {
    await openPage(page);
    await page.locator('#wavRec').uncheck();
    await expect(page.locator('#storeInfo')).toContainText('압축 녹음');
    await micOn(page);
    await record(page, 1500);
    const t = await newestTake(page);
    expect(t.mime).toMatch(/^audio\/webm/);
    between(t.hz, 210, 230);
  });

  test('로컬에서는 저장 버튼이 일반 다운로드로 WAV를 내려 준다', async ({ page }) => {
    await openPage(page);
    await micOn(page);
    await record(page, 1000);
    const t = await newestTake(page);
    const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('[data-save]').first().click()]);
    expect(dl.suggestedFilename()).toMatch(/^voice-\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9]+\.wav$/);
    const buf = readFileSync(await dl.path());
    expect(buf.length).toBe(t.size);
    expect(buf.toString('ascii', 0, 4)).toBe('RIFF');
    await expect(page.locator('#status')).toContainText('브라우저 다운로드로 저장했어요');
  });
});

test.describe('저장 공간 관리', () => {
  test('정리는 기간보다 오래된 녹음만 지우고 ★ 보관은 남긴다', async ({ page }) => {
    await openPage(page);
    await seedTakes(page, [{ age: 40, keep: true }, { age: 40 }, { age: 40 }, { age: 10 }, { age: 10 }, ...Array(40).fill({ age: 0 })]);
    await page.reload();
    await expect(page.locator('#storeInfo')).toContainText('녹음 45개');
    await expect(page.locator('#takeList .take')).toHaveCount(40);
    await expect(page.locator('#moreTakes')).toHaveText('더 보기 (5개 남음)');

    await page.locator('#cleanBtn').click();
    await expect(page.locator('#cleanPanel')).toContainText('보관 1개');
    await expect(page.locator('#cleanGo')).toContainText('지우기 (2개');   // 기본 30일
    await page.locator('#cleanAge').selectOption('7');
    await expect(page.locator('#cleanGo')).toContainText('지우기 (4개');

    page.once('dialog', d => d.accept());
    await page.locator('#cleanGo').click();
    await expect(page.locator('#status')).toHaveText('4개 녹음을 지웠어요 (0.4 MB).');
    await expect(page.locator('#storeInfo')).toContainText('녹음 41개');
    const ids = await idbIds(page);
    expect(ids).toHaveLength(41);
    expect(ids).toContain('seed0');
    expect(ids).not.toContain('seed3');

    await page.locator('#moreTakes').click();
    await expect(page.locator('#takeList .take')).toHaveCount(41);
    await expect(page.locator('#moreTakes')).toBeHidden();
    await expect(page.locator('[data-keep="seed0"]')).toHaveAttribute('aria-pressed', 'true');
  });

  test('★ 보관은 새로고침 뒤에도 남는다', async ({ page }) => {
    await openPage(page);
    await seedTakes(page, [{ age: 0 }]);
    await page.reload();
    const star = page.locator('[data-keep="seed0"]');
    await expect(star).toHaveText('☆');
    await star.click();
    await expect(star).toHaveText('★');
    await page.reload();
    await expect(page.locator('[data-keep="seed0"]')).toHaveAttribute('aria-pressed', 'true');
  });

  test('공간이 모자라면 경고하고 정리 창을 열며, 다음 녹음은 다시 저장한다', async ({ page }) => {
    await openPage(page);
    await micOn(page);
    // 저장 직후 트랜잭션을 중단시키고 오류 이름을 QuotaExceededError로 바꿔 공간 부족을 흉내 낸다
    await page.evaluate(() => {
      window.__q = { put: IDBObjectStore.prototype.put, err: Object.getOwnPropertyDescriptor(IDBTransaction.prototype, 'error') };
      IDBObjectStore.prototype.put = function (...a) { const r = window.__q.put.apply(this, a); this.transaction.abort(); return r; };
      Object.defineProperty(IDBTransaction.prototype, 'error', { configurable: true, get() { return { name: 'QuotaExceededError' }; } });
    });
    await record(page, 800);
    await expect(page.locator('#status')).toContainText('저장 공간이 부족해서');
    await expect(page.locator('#cleanPanel')).toBeVisible();
    expect(await idbIds(page)).toHaveLength(0);

    await page.evaluate(() => {
      IDBObjectStore.prototype.put = window.__q.put;
      Object.defineProperty(IDBTransaction.prototype, 'error', window.__q.err);
    });
    await record(page, 800);
    await expect(page.locator('#status')).toHaveText('');
    expect(await idbIds(page)).toHaveLength(1);
  });
});
