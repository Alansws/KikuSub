/**
 * 条号批次（`lib/cueBatch.ts`）纯函数。
 *
 * 这些用例钉的是「手动自由分批」的三条边界：
 * 1. 批次永远夹在处理范围里，用户输错数字不崩、不越界；
 * 2. 上一批 / 下一批按每批 N 条步进，首批 / 末批不越界；
 * 3. 指纹只看媒体 + 范围 + 批次 + 条数，不含文本——改前面某句的字不会换指纹。
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_BATCH_SIZE,
  batchKey,
  batchLabel,
  clampRange,
  isWholeRange,
  nextBatch,
  previousBatch,
  rangeCount,
  resizeBatch,
  EMPTY_RANGE,
} from '../renderer/src/lib/cueBatch.ts';

const SPAN = { from: 1, to: 291, count: 291 };
const MID = { from: 152, to: 291, count: 140 };

test('clampRange 把任意输入夹进处理范围，起止反了也不抛错', () => {
  assert.deepEqual(clampRange({ from: 1, to: 151 }, SPAN), { from: 1, to: 151 });
  assert.deepEqual(clampRange({ from: 152, to: 291 }, SPAN), { from: 152, to: 291 });
  assert.deepEqual(clampRange({ from: 200, to: 100 }, SPAN), { from: 200, to: 200 });
  assert.deepEqual(clampRange({ from: -5, to: 9999 }, SPAN), { from: 1, to: 291 });
  assert.deepEqual(clampRange({ from: 0, to: 0 }, SPAN), { from: 1, to: 1 });
});

test('空范围返回空批次，不产生 from=0 的假区间', () => {
  const empty = { from: 0, to: 0, count: 0 };
  assert.deepEqual(clampRange({ from: 3, to: 5 }, empty), EMPTY_RANGE);
  assert.deepEqual(nextBatch({ from: 1, to: 5 }, empty, 10), EMPTY_RANGE);
  assert.deepEqual(previousBatch({ from: 1, to: 5 }, empty, 10), EMPTY_RANGE);
});

test('下一批从当前 to 之后继续，末批不越界', () => {
  assert.deepEqual(nextBatch({ from: 1, to: 151 }, SPAN, 151), { from: 152, to: 291 });
  const mid = nextBatch(MID, SPAN, 151);
  assert.deepEqual({ from: mid.from, to: mid.to }, { from: MID.from, to: MID.to });
});

test('上一批从当前 from 之前回退，首批不越界', () => {
  assert.deepEqual(previousBatch({ from: 152, to: 291 }, SPAN, 151), { from: 1, to: 151 });
  assert.deepEqual(previousBatch({ from: 1, to: 151 }, SPAN, 151), { from: 1, to: 151 });
});

test('「每批 N 条」从当前起点重切，保留起点', () => {
  assert.deepEqual(resizeBatch({ from: 1, to: 291 }, SPAN, 151), { from: 1, to: 151 });
  assert.deepEqual(resizeBatch({ from: 152, to: 291 }, SPAN, 151), { from: 152, to: 291 });
  assert.deepEqual(resizeBatch({ from: 1, to: 291 }, SPAN, 0), {
    from: 1,
    to: DEFAULT_BATCH_SIZE,
  });
});

test('处理范围变小时批次跟着缩，状态仍可用', () => {
  const small = { from: 10, to: 20, count: 11 };
  assert.deepEqual(clampRange({ from: 152, to: 291 }, small), { from: 20, to: 20 });
  assert.equal(rangeCount({ from: 20, to: 20 }), 1);
});

test('整段判断与摘要', () => {
  assert.equal(isWholeRange({ from: 1, to: 291 }, SPAN), true);
  assert.equal(isWholeRange({ from: 1, to: 151 }, SPAN), false);
  assert.equal(batchLabel({ from: 1, to: 151 }), '1–151');
  assert.equal(batchLabel(EMPTY_RANGE), '—');
});

test('批次指纹不含文本：改一句文字不会换指纹；换范围 / 批次才算另一批', () => {
  const base = batchKey('film-a', SPAN, { from: 1, to: 151 }, 291, 'polish');
  assert.equal(batchKey('film-a', SPAN, { from: 1, to: 151 }, 291, 'polish'), base);
  assert.notEqual(batchKey('film-a', SPAN, { from: 152, to: 291 }, 291, 'polish'), base);
  assert.notEqual(batchKey('film-a', { from: 1, to: 200, count: 200 }, { from: 1, to: 151 }, 291, 'polish'), base);
  assert.notEqual(batchKey('film-b', SPAN, { from: 1, to: 151 }, 291, 'polish'), base);
});
