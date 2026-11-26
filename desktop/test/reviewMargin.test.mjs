import assert from 'node:assert/strict';
import test from 'node:test';

const { cueMarks, cueMarkTitle } = await import('../renderer/src/lib/reviewMargin.ts');

const cue = (start, end, text = 'x') => ({ start, end, text });
const CUES = [cue(0, 1.4), cue(1.5, 2.9), cue(3.0, 4.6), cue(4.7, 6.2)];

const payload = (items, statuses = {}) => ({ items, statuses });
const item = (id, start, end) => ({ id, start, end, kind: 'suspect', group: 'low' });

test('没有质检队列也没有译文：页边不画任何记号', () => {
  assert.equal(cueMarks(CUES, null, null).size, 0);
  assert.equal(cueMarks(CUES, payload([]), []).size, 0);
  assert.equal(cueMarks([], payload([item('a', 0, 1)]), ['译文']).size, 0);
});

test('待核项落在哪一句，哪一句就是朱点', () => {
  const marks = cueMarks(CUES, payload([item('a', 3.1, 4.0)]), null);
  assert.deepEqual([...marks.entries()], [[2, 'warn']]);
});

test('处理过的质检项给打勾，叠在待核下面时以待核为准', () => {
  const marks = cueMarks(
    CUES,
    payload(
      [item('a', 1.5, 2.0), item('b', 1.6, 2.2), item('c', 0, 1.4)],
      { a: { status: 'done' }, b: { status: 'pending' }, c: { status: 'skipped' } },
    ),
    null,
  );
  assert.equal(marks.get(0), 'ok'); // skipped 也算处理过
  assert.equal(marks.get(1), 'warn'); // 同一句上有 pending，不被 done 覆盖
  assert.equal(marks.get(2), undefined);
});

test('匹配不到字幕的质检项（整段空白 / 本来就没字幕）不在页边留记号', () => {
  const marks = cueMarks(CUES, payload([item('gap', 2.95, 4.6), item('miss', 2.9, 2.98)]), null);
  // 2.95–4.6 与第 3 句（3.0–4.6）重叠：仍要标；2.9–2.98 落在句间空白：不标
  assert.equal(marks.get(2), 'warn');
  assert.equal(marks.size, 1);
  const none = cueMarks(CUES, payload([item('x', 2.92, 2.98)]), null);
  assert.equal(none.size, 0);
});

test('有译文但没质检记录的行 = 蓝铅笔；空译文不算', () => {
  const marks = cueMarks(CUES, payload([]), ['甲', '', '   ', '丁']);
  assert.equal(marks.get(0), 'ai');
  assert.equal(marks.has(1), false);
  assert.equal(marks.has(2), false);
  assert.equal(marks.get(3), 'ai');
});

test('质检记号优先于蓝铅笔，译文条目少也不会越界', () => {
  const marks = cueMarks(CUES, payload([item('a', 0, 1.4)]), ['甲', '乙']);
  assert.equal(marks.get(0), 'warn');
  assert.equal(marks.get(1), 'ai');
  assert.equal(marks.has(2), false);
  assert.equal(marks.size, 2);
});

test('脏数据（缺 start/end、NaN）被跳过，不抛错', () => {
  const marks = cueMarks(
    CUES,
    payload([{ id: 'a' }, { id: 'b', start: 'x', end: 1 }, item('c', 4.8, 5.0)]),
    null,
  );
  assert.deepEqual([...marks.keys()], [3]);
});

test('悬停说明只认三种记号', () => {
  assert.match(cueMarkTitle('warn'), /质检队列/);
  assert.match(cueMarkTitle('ok'), /已经处理过/);
  assert.match(cueMarkTitle('ai'), /已经有译文/);
  assert.equal(cueMarkTitle(undefined), '还没有质检记录');
});
