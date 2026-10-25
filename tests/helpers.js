import { expect } from '@playwright/test';

// Fake mic: returns 220 Hz (A3) plus weak harmonics as a MediaStream. Not connected to the speakers.
function fakeMic() {
  const ac = new AudioContext(), mix = ac.createGain(), dst = ac.createMediaStreamDestination();
  mix.gain.value = 0.3 / 1.4;
  for (const [f, a] of [[220, 1], [440, 0.3], [660, 0.1]]) {
    const o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = f; g.gain.value = a;
    o.connect(g).connect(mix); o.start();
  }
  mix.connect(dst);
  navigator.mediaDevices.getUserMedia = async () => { await ac.resume(); return dst.stream; };
}

// Autoplay is turned off so tests make no sound. The UI language is English unless `lang` says otherwise.
// init runs before the page script.
export async function openPage(page, init, lang = 'en') {
  await page.addInitScript(l => { try { localStorage.setItem('vp-autoplay', 'false'); if (!localStorage.getItem('vp-lang')) localStorage.setItem('vp-lang', JSON.stringify(l)); } catch (e) {} }, lang);
  await page.addInitScript(fakeMic);
  if (init) await page.addInitScript(init);
  await page.goto('/voice-practice.html');
  await expect(page.locator('#storeInfo')).toContainText(lang === 'en' ? 'takes' : '녹음');
}

export async function micOn(page) {
  await page.locator('#micBtn').click();
  await expect(page.locator('#micBtn')).toHaveText('Turn mic off');
}

// "N takes" above the list counts takes in memory, including ones that failed to save.
export async function takeCount(page) {
  const m = (await page.locator('#storeInfo').textContent()).match(/(\d+) takes/);
  return m ? +m[1] : 0;
}

export async function record(page, ms) {
  const n = await takeCount(page);
  await page.locator('#recBtn').click();
  await page.waitForTimeout(ms);
  await page.locator('#recBtn').click();
  await expect(page.locator('#storeInfo')).toContainText(`${n + 1} takes`);
}

export function idbIds(page) {
  return page.evaluate(async () => {
    const db = await new Promise((res, rej) => { const r = indexedDB.open('voice-practice'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
    const keys = await new Promise(res => { const q = db.transaction('takes').objectStore('takes').getAllKeys(); q.onsuccess = () => res(q.result); });
    db.close();
    return keys;
  });
}

// Format of the newest take, and its frequency measured by zero crossings
export function newestTake(page) {
  return page.evaluate(async () => {
    const db = await new Promise((res, rej) => { const r = indexedDB.open('voice-practice'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
    const all = await new Promise(res => { const q = db.transaction('takes').objectStore('takes').getAll(); q.onsuccess = () => res(q.result); });
    db.close();
    const t = all.sort((a, b) => b.created - a.created)[0];
    const ab = await t.blob.arrayBuffer(), v = new DataView(ab), out = { mime: t.mime, size: t.blob.size };
    if (String.fromCharCode(...new Uint8Array(ab, 0, 4)) === 'RIFF') {
      Object.assign(out, { fmt: v.getUint16(20, true), ch: v.getUint16(22, true), sr: v.getUint32(24, true), bits: v.getUint16(34, true) });
    }
    const buf = await new OfflineAudioContext(1, 1, 48000).decodeAudioData(ab);
    const x = buf.getChannelData(0);
    let zc = 0;
    for (let i = 1; i < x.length; i++) if ((x[i - 1] < 0) !== (x[i] < 0)) zc++;
    return { ...out, dur: buf.duration, hz: zc / 2 / buf.duration };
  });
}

// Puts takes straight into IndexedDB. age is in days; each is a 100 KB silent WAV.
export function seedTakes(page, list) {
  return page.evaluate(async list => {
    const pad = n => String(n).padStart(2, '0');
    const dayKey = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    const n = 100000, buf = new ArrayBuffer(44 + n), v = new DataView(buf), u8 = new Uint8Array(buf);
    const tag = (o, s) => { for (let i = 0; i < 4; i++) u8[o + i] = s.charCodeAt(i); };
    tag(0, 'RIFF'); v.setUint32(4, 36 + n, true); tag(8, 'WAVE'); tag(12, 'fmt '); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 48000, true); v.setUint32(28, 144000, true);
    v.setUint16(32, 3, true); v.setUint16(34, 24, true); tag(36, 'data'); v.setUint32(40, n, true);
    const now = Date.now();
    const takes = list.map(({ age, keep }, i) => {
      const created = now - age * 864e5 - i * 60000;
      return { id: 'seed' + i, created, day: dayKey(new Date(created)), step: 'breath', stepName: '호흡 정리', kind: 'breath',
        focus: null, lang: null, mime: 'audio/wav', dur: 1, contour: [], band: null, pending: false, keep: !!keep,
        a: { p10: null, p50: null, p90: null, lo: null, hi: null, pauses: 0, voiced: 0 }, blob: new Blob([buf], { type: 'audio/wav' }) };
    });
    const db = await new Promise((res, rej) => { const r = indexedDB.open('voice-practice'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
    await new Promise((res, rej) => { const tx = db.transaction('takes', 'readwrite'); takes.forEach(t => tx.objectStore('takes').put(t)); tx.oncomplete = res; tx.onabort = () => rej(tx.error); });
    db.close();
  }, list);
}
