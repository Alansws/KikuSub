'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  deleteCleanupCandidates,
  isFragmentSubtitle,
  listCleanupCandidates,
  pruneLogs,
} = require('../main/files.cjs');

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'kikusub-files-'));
}

test('fragment subtitle classifier', () => {
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.srt'), true);
  assert.equal(isFragmentSubtitle('剧集_25m10s-25m43s.qwen.srt'), true);
  assert.equal(isFragmentSubtitle('剧集_01h02m03s-01h02m10s.part_cancelled.srt'), true);
  assert.equal(isFragmentSubtitle('剧集_from_00m10s.vtt'), true);
  assert.equal(isFragmentSubtitle('剧集.srt'), false);
  // 核对工作草稿与已导出的成片不是临时碎片，退出清理不得默认删除
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.autosave_draft.srt'), false);
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.reviewed.srt'), false);
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.clean.srt'), false);
  // 译文交付物也不是碎片：只导译文 / 双语，两种后缀
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.zh-Hans.srt'), false);
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.bilingual.srt'), false);
  assert.equal(isFragmentSubtitle('剧集_05m00s-05m15s.en.vtt'), false);
  assert.equal(isFragmentSubtitle('2026-11-10.txt'), false);
});

test('lists fragments and proxies only, filters by mtime', () => {
  const root = tmpdir();
  fs.mkdirSync(path.join(root, 'web_proxies'), { recursive: true });
  fs.writeFileSync(path.join(root, '剧集_00m01s-00m02s.srt'), 'x');
  fs.writeFileSync(path.join(root, '剧集.srt'), 'x');
  fs.writeFileSync(path.join(root, 'web_proxies', '剧集_1_preview.mp4'), 'x');

  const all = listCleanupCandidates(root, 0);
  assert.deepEqual(all.map((item) => item.kind).sort(), ['fragment', 'proxy']);
  const future = listCleanupCandidates(root, Date.now() + 60000);
  assert.equal(future.length, 0);
});

test('delete removes unchecked and keeps checked paths only', () => {
  const root = tmpdir();
  const keep = path.join(root, '剧集_00m01s-00m02s.srt');
  const drop = path.join(root, '剧集_00m03s-00m04s.srt');
  fs.writeFileSync(keep, 'k');
  fs.writeFileSync(drop, 'd');
  const candidates = listCleanupCandidates(root, 0);

  const result = deleteCleanupCandidates(candidates, [keep]);

  assert.equal(result.removed, 1);
  assert.equal(fs.existsSync(keep), true);
  assert.equal(fs.existsSync(drop), false);
  // 渲染进程伪造一个不在候选里的路径，不能删任何东西
  const outside = path.join(root, 'important.srt');
  fs.writeFileSync(outside, 'keep me');
  const forged = deleteCleanupCandidates(
    [{ path: outside, name: 'important.srt', kind: 'fragment', size: 6, mtime: 0 }].filter(
      () => false,
    ),
    [],
  );
  assert.equal(forged.removed, 0);
  assert.equal(fs.existsSync(outside), true);
});

test('pruneLogs enforces age and size without touching active logs', () => {
  const root = tmpdir();
  const active = path.join(root, 'kikusub.log');
  const old = path.join(root, 'kikusub.log.3');
  const backup = path.join(root, 'main.log.1');
  fs.writeFileSync(active, 'a'.repeat(10));
  fs.writeFileSync(old, 'o'.repeat(20));
  fs.writeFileSync(backup, 'b'.repeat(20));
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000);
  fs.utimesSync(old, thirtyDaysAgo, thirtyDaysAgo);

  const result = pruneLogs(root, { maxAgeDays: 14, maxTotalBytes: 1024 });

  assert.equal(result.removed, 1);
  assert.equal(fs.existsSync(active), true);
  assert.equal(fs.existsSync(old), false);
  assert.equal(fs.existsSync(backup), true);
});
