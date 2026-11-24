import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MIN_CHAPTER_SPAN,
  beginDraft,
  pendingEdge,
  readyError,
  setEdge,
  span,
  toMarkTimes,
} from '../renderer/src/lib/chapterDraft.ts';

const pointAt = (time, edge) =>
  beginDraft({ id: 'ch-1', title: '场景 1 结束', time, edge });

test('先找到章末：起点待定，章末就是那个时刻点', () => {
  const draft = pointAt(846.283, 'end');
  assert.equal(draft.from, 'ch-1');
  assert.equal(draft.title, '场景 1 结束');
  assert.equal(draft.start, null);
  assert.equal(draft.end, 846.283);
  assert.equal(pendingEdge(draft), 'start');
  assert.equal(readyError(draft), '还没有起点');
});

test('先找到章首：终点待定', () => {
  const draft = pointAt(10.4, 'start');
  assert.equal(draft.start, 10.4);
  assert.equal(draft.end, null);
  assert.equal(pendingEdge(draft), 'end');
});

test('补起点：落在章末之前就成立，越界则原样不动', () => {
  const draft = pointAt(846.283, 'end');
  const ok = setEdge(draft, 'start', 10.4, 7200);
  assert.equal(ok.error, '');
  assert.equal(ok.draft.start, 10.4);

  const late = setEdge(draft, 'start', 846.28, 7200);
  assert.notEqual(late.error, '');
  assert.equal(late.draft.start, null, '失败时草稿不能被改');
});

test('补终点：必须比起点至少晚 0.2 秒', () => {
  const draft = pointAt(10.4, 'start');
  const tooEarly = setEdge(draft, 'end', 10.4 + MIN_CHAPTER_SPAN / 2, 7200);
  assert.notEqual(tooEarly.error, '');
  assert.equal(tooEarly.draft.end, null);

  const ok = setEdge(draft, 'end', 846.283, 7200);
  assert.equal(ok.error, '');
  assert.equal(readyError(ok.draft), '');
});

test('时间落到毫秒：点击算出的 9.99998 显示成 10.000', () => {
  const draft = pointAt(846.2834, 'end');
  assert.equal(draft.end, 846.283);
  const ok = setEdge(pointAt(846.283, 'end'), 'start', 9.99998, 7200);
  assert.equal(ok.draft.start, 10);
});

test('播放头时间被夹进媒体范围', () => {
  const draft = pointAt(100, 'start');
  assert.equal(setEdge(draft, 'end', 9999, 300).draft.end, 300);
  assert.equal(setEdge(draft, 'end', -5, 300).error !== '', true, '早于起点：拒绝');
});

test('锚点那一端不许被误按覆盖（另一端还没补）', () => {
  const draft = pointAt(50, 'end');
  const wrong = setEdge(draft, 'end', 40, 60);
  assert.notEqual(wrong.error, '');
  assert.equal(wrong.draft.end, 50, '锚点保持 50');
  assert.equal(wrong.draft.start, null);

  // 两端都落位后就可以互相微调
  const done = { ...draft, start: 10 };
  assert.equal(setEdge(done, 'end', 52, 60).draft.end, 52);
  assert.equal(setEdge(done, 'start', 8, 60).draft.start, 8);
});

test('预览区间：待定那一端跟着播放头，顺序自动摆正', () => {
  const draft = pointAt(846.283, 'end');
  assert.deepEqual(span(draft, 10), { start: 10, end: 846.283 });
  assert.deepEqual(span(draft, 900), { start: 846.283, end: 900 });

  const done = { ...draft, start: 10 };
  assert.deepEqual(span(done, 500), { start: 10, end: 846.283 });

  assert.equal(span(null, 10), null);
});

test('保存校验：两端齐 + 不短于 0.2 秒', () => {
  assert.equal(readyError(null), '还没有章节草稿');
  assert.equal(readyError({ from: 'a', title: '', start: 10, end: null }), '还没有终点');
  assert.equal(
    readyError({ from: 'a', title: '', start: 10, end: 10.1 }),
    '章节太短（至少 0.2 秒）',
  );
  assert.equal(readyError({ from: 'a', title: '', start: 10, end: 10.3 }), '');
});

test('落库时间四舍五入到毫秒', () => {
  const times = toMarkTimes({ from: 'a', title: '', start: 10.40049, end: 846.2834 });
  assert.deepEqual(times, { start: 10.4, end: 846.283 });
  assert.equal(toMarkTimes({ from: 'a', title: '', start: null, end: 10 }), null);
  assert.equal(toMarkTimes({ from: 'a', title: '', start: 10, end: 10.05 }), null);
});
