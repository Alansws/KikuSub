import assert from 'node:assert/strict';
import test from 'node:test';

import { alignPreviewRows, bRefsFor } from '../renderer/src/lib/previewDiff.ts';

const cue = (start, end, text) => ({ start, end, text });

test('alignPreviewRows without a new draft returns one row per original cue', () => {
  const rows = alignPreviewRows([cue(0, 1, '一'), cue(1, 2, '二')]);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => row.kind), ['same', 'same']);
  assert.deepEqual(rows.map((row) => row.newIndexes), [[], []]);
});

test('alignPreviewRows pairs identical cues 1:1', () => {
  const rows = alignPreviewRows(
    [cue(0, 1, '一'), cue(1, 2, '二')],
    [cue(0, 1, '一'), cue(1, 2, '二')],
  );
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].oldIndexes, [0]);
  assert.deepEqual(rows[0].newIndexes, [0]);
  assert.equal(rows[0].kind, 'same');
});

test('alignPreviewRows puts 2→1 merge on one row instead of reading as a delete', () => {
  const rows = alignPreviewRows(
    [cue(0, 1, '一'), cue(1, 2, '二')],
    [cue(0, 2, '一 二')],
  );
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].oldIndexes, [0, 1]);
  assert.deepEqual(rows[0].newIndexes, [0]);
  assert.equal(rows[0].kind, 'diff');
  assert.equal(rows[0].start, 0);
  assert.equal(rows[0].end, 2);
});

test('alignPreviewRows puts 1→2 split on one row', () => {
  const rows = alignPreviewRows(
    [cue(0, 2, '一二')],
    [cue(0, 1, '一'), cue(1, 2, '二')],
  );
  assert.equal(rows.length, 1);
  assert.deepEqual(rows[0].oldIndexes, [0]);
  assert.deepEqual(rows[0].newIndexes, [0, 1]);
  assert.equal(rows[0].kind, 'diff');
});

test('alignPreviewRows keeps deleted and inserted cues as their own rows', () => {
  const rows = alignPreviewRows([cue(0, 1, '旧')], [cue(3, 4, '新')]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].kind, 'old');
  assert.deepEqual(rows[0].newIndexes, []);
  assert.equal(rows[1].kind, 'new');
  assert.deepEqual(rows[1].oldIndexes, []);
});

test('bRefsFor reports the overlapping B range and text per A cue', () => {
  const refs = bRefsFor(
    [cue(0, 1.0, 'A1'), cue(1.5, 2.5, 'A2'), cue(5, 6, 'A3')],
    [cue(0, 0.5, 'x'), cue(0.8, 1.2, 'y'), cue(1.6, 2.4, 'z')],
  );
  assert.deepEqual(refs[0], { first: 0, last: 1, text: 'xy', lines: ['x', 'y'] });
  assert.deepEqual(refs[1], { first: 2, last: 2, text: 'z', lines: ['z'] });
  assert.equal(refs[2], null);
});
