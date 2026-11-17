import assert from 'node:assert/strict';
import test from 'node:test';

import {
  otherEngineKey,
  pickReviewEngine,
  sharesLanguage,
} from '../renderer/src/lib/secondOpinion.ts';
import { charDiff } from '../renderer/src/lib/textDiff.ts';

/** 把 diff 还原成某一侧的文本：eq 两边都有，del 只在当前稿，ins 只在另一引擎稿。 */
function render(ops, side) {
  return ops
    .filter((op) => op.op === 'eq' || op.op === side)
    .map((op) => op.text)
    .join('');
}

const current = (ops) => render(ops, 'del');
const alternative = (ops) => render(ops, 'ins');

test('charDiff 相同文本没有差异片段', () => {
  const diff = charDiff('大変でしたね', '大変でしたね');
  assert.equal(diff.equal, true);
  assert.equal(diff.hunks, 0);
  assert.deepEqual(diff.ops, [{ op: 'eq', text: '大変でしたね' }]);
});

test('charDiff 只多一个字时只标插入', () => {
  const diff = charDiff('大変でしたね', '大変でしたよね');
  assert.equal(diff.equal, false);
  assert.equal(diff.hunks, 1);
  assert.equal(current(diff.ops), '大変でしたね');
  assert.equal(alternative(diff.ops), '大変でしたよね');
  assert.deepEqual(
    diff.ops.filter((op) => op.op !== 'eq'),
    [{ op: 'ins', text: 'よ' }],
  );
});

test('charDiff 替换拆成 del + ins，两侧都能还原原文', () => {
  const diff = charDiff('今日は晴れです', '今日は雨です');
  assert.equal(diff.hunks, 1);
  assert.equal(current(diff.ops), '今日は晴れです');
  assert.equal(alternative(diff.ops), '今日は雨です');
  assert.ok(diff.ops.some((op) => op.op === 'del'));
  assert.ok(diff.ops.some((op) => op.op === 'ins'));
});

test('charDiff 统计的是分离的差异片段数', () => {
  const diff = charDiff('abc', 'axcy');
  assert.equal(diff.hunks, 2);
  assert.equal(current(diff.ops), 'abc');
  assert.equal(alternative(diff.ops), 'axcy');
});

test('charDiff 不拆代理对（表情 / 生僻字保持完整）', () => {
  const diff = charDiff('𠮷野家', '𠮷野屋');
  assert.equal(current(diff.ops), '𠮷野家');
  assert.equal(alternative(diff.ops), '𠮷野屋');
  for (const op of diff.ops) {
    assert.equal(Array.from(op.text).join(''), op.text);
  }
});

test('charDiff 空文本退化成单侧全量', () => {
  const allDel = charDiff('ありがとう', '');
  assert.equal(allDel.hunks, 1);
  assert.equal(current(allDel.ops), 'ありがとう');
  assert.equal(alternative(allDel.ops), '');

  const allIns = charDiff('', 'ありがとう');
  assert.equal(allIns.hunks, 1);
  assert.equal(current(allIns.ops), '');
  assert.equal(alternative(allIns.ops), 'ありがとう');

  const empty = charDiff('', '');
  assert.equal(empty.equal, true);
  assert.deepEqual(empty.ops, []);
});

test('sharesLanguage 只拒绝明确没有共同语种的两个引擎', () => {
  assert.equal(sharesLanguage(['日语'], ['日语']), true);
  assert.equal(sharesLanguage(['中文', '英语', '日语'], ['日语']), true);
  assert.equal(sharesLanguage(['日语'], ['中文']), false);
  // 语种未知（旧注册表 / 导入稿）不限制，交给 reviewable 能力位把关
  assert.equal(sharesLanguage(undefined, ['日语']), true);
  assert.equal(sharesLanguage(['日语'], []), true);
});

test('pickReviewEngine 尊重用户选择，且不会选当前引擎', () => {
  const choices = [
    { key: 'whisper', label: 'Anime Whisper', enabled: true, installed: true },
    { key: 'qwen', label: 'Qwen3-ASR + CTC', enabled: true, installed: true },
  ];
  assert.equal(pickReviewEngine(choices, 'whisper', 'qwen'), 'qwen');
  assert.equal(pickReviewEngine(choices, 'qwen', 'whisper'), 'whisper');
  // 偏好恰好是当前稿的引擎：退回两引擎互斥的默认
  assert.equal(pickReviewEngine(choices, 'whisper', 'whisper'), 'qwen');
  // 偏好已失效：默认，不瞎选
  assert.equal(pickReviewEngine(choices, 'whisper', 'firered'), 'qwen');
  assert.equal(otherEngineKey('whisper'), 'qwen');
  assert.equal(otherEngineKey('qwen'), 'whisper');
});

test('pickReviewEngine 只从已启用且已下载的引擎里挑', () => {
  const choices = [
    { key: 'whisper', label: 'Anime Whisper', enabled: true, installed: true },
    { key: 'qwen', label: 'Qwen3-ASR + CTC', enabled: true, installed: false },
  ];
  // qwen 没下载：不能把它当默认（否则按钮看起来能用、点下去才报错）
  assert.equal(pickReviewEngine(choices, 'whisper', 'qwen'), '');
  assert.equal(pickReviewEngine(choices, 'whisper'), '');
  assert.equal(
    pickReviewEngine(
      [
        { key: 'whisper', label: 'Anime Whisper', enabled: false, installed: true },
        { key: 'qwen', label: 'Qwen3-ASR + CTC', enabled: true, installed: true },
      ],
      'sensevoice',
      'whisper',
    ),
    'qwen',
  );
});
