import assert from 'node:assert/strict';
import test from 'node:test';

import { optimisticTranscribeJob, rangeDoneText } from '../renderer/src/lib/transcribeJob.ts';

test('乐观任务态：排队中、0%、只有转写这一类', () => {
  const job = optimisticTranscribeJob('正在识别选区…');
  assert.equal(job.status, 'queued');
  assert.equal(job.kind, 'transcribe');
  assert.equal(job.percent, 0);
  assert.equal(job.stage, '正在识别选区…');
  assert.equal(job.id, '');
  assert.equal(job.result, null);
});

test('转写页的区间任务说「选区转写完成」，核对台说「局部转写完成」', () => {
  assert.match(rangeDoneText({ origin: 'transcribe', added: 0, removed: 2, total: 9, saved: false }), /^选区转写完成/);
  assert.match(rangeDoneText({ origin: 'review', added: 0, removed: 2, total: 9, saved: false }), /^局部转写完成/);
});

test('替换 / 更新 / 新增 / 无变化 四种结果各有说法', () => {
  const base = { origin: 'transcribe', total: 100, saved: false };
  assert.match(rangeDoneText({ ...base, added: 4, removed: 3 }), /替换 3 条、新增 4 条/);
  assert.match(rangeDoneText({ ...base, added: 0, removed: 3 }), /更新该区间 3 条/);
  assert.match(rangeDoneText({ ...base, added: 4, removed: 0 }), /新增 4 条/);
  assert.match(rangeDoneText({ ...base, added: 0, removed: 0 }), /已有相同字幕/);
});

test('自动保存的提示接在最后', () => {
  assert.match(
    rangeDoneText({ origin: 'transcribe', added: 1, removed: 1, total: 5, saved: true }),
    /时间轴共 5 条，已自动保存到导出文件夹$/,
  );
});
