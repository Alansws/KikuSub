import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyChoices,
  applyHint,
  dualChoices,
  resolveDualApply,
  confirmDestructiveText,
  isDestructiveChoice,
  needsAbsoluteTimeline,
  rangeSpan,
  resolveApplyChoice,
} from '../renderer/src/lib/applyMode.ts';

const range = { fullCover: false, start: '40:20', end: '44:24' };
const full = { fullCover: true, start: '', end: '' };

test('区间任务给三档，「替换选区」在最前（也是默认）', () => {
  assert.deepEqual(
    applyChoices(range).map((c) => c.key),
    ['replace_range', 'append', 'replace'],
  );
  assert.equal(applyChoices(range)[0].label, '替换选区');
});

test('整片任务没有「替换选区」：整片替换一段没有意义', () => {
  assert.deepEqual(
    applyChoices(full).map((c) => c.key),
    ['replace', 'append'],
  );
});

test('整片任务里残留的 replace_range 退回覆盖，不静默沿用', () => {
  assert.equal(resolveApplyChoice('replace_range', full), 'replace');
});

test('区间任务里「覆盖整片」是合法档位，不替用户改选', () => {
  // 用户明确点过「覆盖整片」再填区间：保留他的选择，靠警示色 + 二次确认兜底，
  // 而不是偷偷换回另一档（那又变成一次「自动」）。
  assert.equal(resolveApplyChoice('replace', range), 'replace');
});

test('合法档位原样保留', () => {
  assert.equal(resolveApplyChoice('append', range), 'append');
  assert.equal(resolveApplyChoice('replace', full), 'replace');
});

test('只有区间任务的「覆盖整片」是破坏性的', () => {
  assert.equal(isDestructiveChoice('replace', range), true);
  assert.equal(isDestructiveChoice('replace', full), false);
  assert.equal(isDestructiveChoice('replace_range', range), false);
  assert.equal(isDestructiveChoice('append', range), false);
});

test('提示文案带上真实区间，读得出会动哪一段', () => {
  const hint = applyHint('replace_range', range);
  assert.match(hint, /40:20 – 44:24/);
  assert.match(hint, /区间外一条不动/);
  // 覆盖整片必须自己说清楚是丢数据的，不能只写「替换整张表」
  assert.match(applyHint('replace', range), /全部丢失/);
  assert.match(applyHint('replace', full), /替换整张表/);
  assert.match(applyHint('append', range), /合并去重/);
});

test('空输入退化成片头 / 片尾，提示仍然成句', () => {
  assert.equal(rangeSpan('', ''), '片头 – 片尾');
  assert.equal(rangeSpan(' 40:20 ', ''), '40:20 – 片尾');
  assert.match(confirmDestructiveText({ fullCover: false, start: '', end: '44:24' }), /片头 – 44:24/);
});

test('替换选区强制原片绝对时间轴', () => {
  assert.equal(needsAbsoluteTimeline('replace_range'), true);
  assert.equal(needsAbsoluteTimeline('append'), false);
  assert.equal(needsAbsoluteTimeline('replace'), false);
});

test('「自动」这一档不存在了', () => {
  // 残留的 'auto' 不该被当成合法值悄悄接受（类型层已排除，这里守运行时）。
  const keys = [...applyChoices(range), ...applyChoices(full)].map((c) => c.key);
  assert.equal(keys.includes('auto'), false);
});


test('双引擎协同不提供「追加」：服务端会 422，界面别让点', () => {
  assert.deepEqual(
    dualChoices(full).map((c) => c.key),
    ['replace'],
  );
  assert.deepEqual(
    dualChoices(range).map((c) => c.key),
    ['replace_range', 'replace'],
  );
});

test('双引擎下残留的追加退回该范围的默认档', () => {
  assert.equal(resolveDualApply('append', full), 'replace');
  assert.equal(resolveDualApply('append', range), 'replace_range');
  assert.equal(resolveDualApply('replace_range', range), 'replace_range');
});
