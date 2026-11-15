import assert from 'node:assert/strict';
import test from 'node:test';

import {
  alignDoneText,
  optimisticTranscribeJob,
  rangeDoneText,
} from '../renderer/src/lib/transcribeJob.ts';

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


test('逐字对齐说明只在 Qwen 且有语音段时出现', () => {
  const stats = {
    enabled: true,
    segments: 257,
    aligned: 230,
    noop: 5,
    degraded: 20,
    empty: 2,
  };
  const text = alignDoneText(stats, 'qwen');
  assert.match(text, /257 个语音段/);
  assert.match(text, /不是字幕条数/);
  assert.match(text, /230 段完成逐字对齐/);
  assert.match(text, /对齐降级 20/);
  assert.match(text, /纯符号 5/);
  assert.match(text, /无台词 2/);
});

test('非 CTC 引擎不给 0/0 或多余的对齐汇总', () => {
  const stats = { enabled: true, segments: 0, aligned: 0 };
  assert.equal(alignDoneText(stats, 'whisper'), '');
  assert.equal(alignDoneText(stats, 'sherpa'), '');
  assert.equal(alignDoneText({ enabled: false, segments: 30, aligned: 30 }, 'qwen'), '');
  assert.equal(alignDoneText(null, 'qwen'), '');
});

test('全部对齐时说清分母并给一句解释', () => {
  const text = alignDoneText(
    { enabled: true, segments: 30, aligned: 30, noop: 0, degraded: 0, empty: 0 },
    'qwen',
  );
  assert.match(text, /30 个语音段全部完成逐字对齐/);
});
