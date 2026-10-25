import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { openPage, micOn, record, idbIds, newestTake, seedTakes } from './helpers.js';

const between = (x, lo, hi) => { expect(x).toBeGreaterThan(lo); expect(x).toBeLessThan(hi); };

test.describe('Recording', () => {
  test('saves 24-bit WAV through AudioWorklet by default', async ({ page }) => {
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

  test('falls back to ScriptProcessor for WAV when AudioWorklet is blocked', async ({ page }) => {
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

  test('turning WAV off goes back to compressed (webm) recording', async ({ page }) => {
    await openPage(page);
    await page.locator('#wavRec').uncheck();
    await expect(page.locator('#storeInfo')).toContainText('Compressed');
    await micOn(page);
    await record(page, 1500);
    const t = await newestTake(page);
    expect(t.mime).toMatch(/^audio\/webm/);
    between(t.hz, 210, 230);
  });

  test('locally, Save downloads the WAV as a normal download', async ({ page }) => {
    await openPage(page);
    await micOn(page);
    await record(page, 1000);
    const t = await newestTake(page);
    const [dl] = await Promise.all([page.waitForEvent('download'), page.locator('[data-save]').first().click()]);
    expect(dl.suggestedFilename()).toMatch(/^voice-\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9]+\.wav$/);
    const buf = readFileSync(await dl.path());
    expect(buf.length).toBe(t.size);
    expect(buf.toString('ascii', 0, 4)).toBe('RIFF');
    await expect(page.locator('#status')).toContainText('Saved via browser download');
  });
});

test.describe('Storage management', () => {
  test('Clean up deletes only takes older than the age and keeps ★ takes', async ({ page }) => {
    await openPage(page);
    await seedTakes(page, [{ age: 40, keep: true }, { age: 40 }, { age: 40 }, { age: 10 }, { age: 10 }, ...Array(40).fill({ age: 0 })]);
    await page.reload();
    await expect(page.locator('#storeInfo')).toContainText('45 takes');
    await expect(page.locator('#takeList .take')).toHaveCount(40);
    await expect(page.locator('#moreTakes')).toHaveText('Show more (5 left)');

    await page.locator('#cleanBtn').click();
    await expect(page.locator('#cleanPanel')).toContainText('kept 1');
    await expect(page.locator('#cleanGo')).toContainText('Delete (2 takes');   // default 30 days
    await page.locator('#cleanAge').selectOption('7');
    await expect(page.locator('#cleanGo')).toContainText('Delete (4 takes');

    page.once('dialog', d => d.accept());
    await page.locator('#cleanGo').click();
    await expect(page.locator('#status')).toHaveText('Deleted 4 takes (0.4 MB).');
    await expect(page.locator('#storeInfo')).toContainText('41 takes');
    const ids = await idbIds(page);
    expect(ids).toHaveLength(41);
    expect(ids).toContain('seed0');
    expect(ids).not.toContain('seed3');

    await page.locator('#moreTakes').click();
    await expect(page.locator('#takeList .take')).toHaveCount(41);
    await expect(page.locator('#moreTakes')).toBeHidden();
    await expect(page.locator('[data-keep="seed0"]')).toHaveAttribute('aria-pressed', 'true');
  });

  test('★ keep survives a reload', async ({ page }) => {
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

  test('when storage is full, warns and opens Clean up, and the next take saves again', async ({ page }) => {
    await openPage(page);
    await micOn(page);
    // Fake a full disk: abort the transaction right after put and report the error as QuotaExceededError
    await page.evaluate(() => {
      window.__q = { put: IDBObjectStore.prototype.put, err: Object.getOwnPropertyDescriptor(IDBTransaction.prototype, 'error') };
      IDBObjectStore.prototype.put = function (...a) { const r = window.__q.put.apply(this, a); this.transaction.abort(); return r; };
      Object.defineProperty(IDBTransaction.prototype, 'error', { configurable: true, get() { return { name: 'QuotaExceededError' }; } });
    });
    await record(page, 800);
    await expect(page.locator('#status')).toContainText('Storage is full');
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

test.describe('Language', () => {
  test('the toggle switches the UI between Korean and English and is remembered', async ({ page }) => {
    await openPage(page, null, 'ko');
    await expect(page.locator('h1 [data-l]:visible')).toHaveText('목소리 연습실');
    await expect(page.locator('#micBtn')).toHaveText('마이크 켜기');
    await expect(page.locator('#langBtn')).toHaveText('English');
    await page.locator('#langBtn').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('h1 [data-l]:visible')).toHaveText('Voice Practice');
    await expect(page.locator('#micBtn')).toHaveText('Turn mic on');
    await expect(page.locator('#steps')).toContainText('Breath release');
    await expect(page.locator('#panel h2')).not.toHaveText(/[가-힣]/);
    await expect(page.locator('#storeInfo')).toContainText('takes');
    await page.reload();
    await expect(page.locator('h1 [data-l]:visible')).toHaveText('Voice Practice');
    await expect(page.locator('#langBtn')).toHaveText('한국어');
  });
});
