/**
 * 转写页「产出 × 范围」决策的回归（2026-11-25）。
 *
 * 守的是用户报障的那条路径：逐章转录时（填了区间），换一个引擎，
 * 结果必须能写进第二版（双引擎复核），而不是被隐藏或静默写回核对台。
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import * as kernel from '../renderer/src/lib/applyMode.ts';
import {
  defaultTarget,
  resolvePlan,
  targetLabel,
} from '../renderer/src/lib/transcribePlan.ts';

const full = { fullCover: true, start: '', end: '' };
const range = { fullCover: false, start: '00:10.475', end: '14:06.704' };

function input(patch = {}) {
  return {
    target: 'primary',
    ctx: full,
    apply: 'replace',
    hasCues: true,
    engineLabel: 'Qwen3-ASR + CTC',
    primaryEngineLabel: 'Anime Whisper',
    secondary: '',
    secondaryLabel: '',
    candidates: [],
    alt: { exists: false, count: 0, engineLabel: '' },
    ...patch,
  };
}

test('主稿整片：两档，默认覆盖整片，按钮仍叫「开始转写」', () => {
  const plan = resolvePlan(input(), kernel);
  assert.deepEqual(plan.choices.map((c) => c.key), ['replace', 'append']);
  assert.equal(plan.apply, 'replace');
  assert.equal(plan.button, '开始转写');
  assert.equal(plan.altReview, false);
  assert.match(plan.hint, /写进核对台/);
  assert.equal(plan.destructive, false);
});

test('主稿区间：三档，停在替换选区时区间外的句不动', () => {
  const plan = resolvePlan(input({ ctx: range, apply: 'replace_range' }), kernel);
  assert.deepEqual(plan.choices.map((c) => c.key), ['replace_range', 'append', 'replace']);
  assert.equal(plan.apply, 'replace_range');
  assert.match(plan.hint, /只重写 00:10\.475 – 14:06\.704/);
  assert.equal(plan.destructive, false);
});

test('主稿区间 + 覆盖整片：标记为破坏性，交给界面二次确认', () => {
  const plan = resolvePlan(input({ ctx: range, apply: 'replace' }), kernel);
  assert.equal(plan.apply, 'replace');
  assert.equal(plan.destructive, true);
});

test('第二版整片：没有任何档位，按钮自己说明在生成第二版', () => {
  const plan = resolvePlan(input({ target: 'alt', engineLabel: 'Qwen3-ASR + CTC' }), kernel);
  assert.equal(plan.apply, 'replace');
  assert.equal(plan.altReview, true);
  assert.equal(plan.altRange, false);
  assert.deepEqual(plan.choices, []);
  assert.equal(plan.button, '生成第二版');
  assert.equal(plan.blocked, '');
  assert.match(plan.hint, /核对台一个字不动/);
});

test('第二版整片且已有 B：提示现有第二版会被替换', () => {
  const plan = resolvePlan(
    input({
      target: 'alt',
      alt: { exists: true, count: 219, engineLabel: 'Anime Whisper' },
    }),
    kernel,
  );
  assert.match(plan.hint, /现有第二版 Anime Whisper · 219 条会被替换/);
});

test('第二版区间：按区间合并，B 的其它区间保留（用户报障的核心路径）', () => {
  const plan = resolvePlan(
    input({
      target: 'alt',
      ctx: range,
      engineLabel: 'Qwen3-ASR + CTC',
      alt: { exists: false, count: 0, engineLabel: '' },
    }),
    kernel,
  );
  assert.equal(plan.apply, 'replace_range');
  assert.equal(plan.altReview, true);
  assert.equal(plan.altRange, true);
  assert.equal(plan.blocked, '');
  assert.match(plan.hint, /只把 00:10\.475 – 14:06\.704 的第二版换成这次结果/);
  assert.match(plan.hint, /B 的其它区间和核对台都不动/);
});

test('第二版没有主稿：不可执行，且理由直接可读', () => {
  const plan = resolvePlan(input({ target: 'alt', hasCues: false }), kernel);
  assert.match(plan.blocked, /还没有主稿/);
  assert.equal(plan.altReview, true);
});

test('第二版换引擎但只写区间：警告两份 B 会混用引擎', () => {
  const plan = resolvePlan(
    input({
      target: 'alt',
      ctx: range,
      engineLabel: 'Qwen3-ASR + CTC',
      alt: { exists: true, count: 100, engineLabel: 'Anime Whisper' },
    }),
    kernel,
  );
  assert.match(plan.warning, /现有第二版来自 Anime Whisper/);
});

test('第二版同引擎续写：不报警', () => {
  const plan = resolvePlan(
    input({
      target: 'alt',
      ctx: range,
      engineLabel: 'Qwen3-ASR + CTC',
      alt: { exists: true, count: 100, engineLabel: 'Qwen3-ASR + CTC' },
    }),
    kernel,
  );
  assert.equal(plan.warning, '');
});

test('两版一起：主稿 + 副引擎第二版，档位没有追加', () => {
  const plan = resolvePlan(
    input({
      target: 'both',
      ctx: range,
      engineLabel: 'Anime Whisper',
      secondary: 'qwen',
      secondaryLabel: 'Qwen3-ASR + CTC',
      candidates: ['qwen'],
    }),
    kernel,
  );
  assert.equal(plan.dualEngine, 'qwen');
  assert.deepEqual(plan.choices.map((c) => c.key), ['replace_range', 'replace']);
  assert.equal(plan.button, '两版一起跑');
  assert.match(plan.hint, /先按上面的档位写主稿/);
  assert.match(plan.hint, /再写第二版/);
});

test('两版一起没有副引擎：不可执行', () => {
  const plan = resolvePlan(input({ target: 'both', candidates: [] }), kernel);
  assert.match(plan.blocked, /再启用一个日语引擎/);
  assert.equal(plan.dualEngine, '');
});

test('两版一起 + 区间覆盖整片：仍是破坏性档位', () => {
  const plan = resolvePlan(
    input({
      target: 'both',
      ctx: range,
      apply: 'replace',
      secondary: 'qwen',
      secondaryLabel: 'Qwen3',
      candidates: ['qwen'],
    }),
    kernel,
  );
  assert.equal(plan.destructive, true);
});

test('默认产出：换引擎后默认写第二版，避免覆盖主稿', () => {
  assert.equal(defaultTarget({ hasCues: false, engine: 'qwen', primaryEngine: '' }), 'primary');
  assert.equal(defaultTarget({ hasCues: true, engine: 'qwen', primaryEngine: 'whisper' }), 'alt');
  assert.equal(defaultTarget({ hasCues: true, engine: 'qwen', primaryEngine: 'qwen' }), 'primary');
  assert.equal(defaultTarget({ hasCues: true, engine: 'qwen', primaryEngine: '' }), 'primary');
});

test('产出短名覆盖三种目标', () => {
  assert.equal(targetLabel('primary'), '主稿（核对台）');
  assert.equal(targetLabel('alt'), '第二版（对照）');
  assert.equal(targetLabel('both'), '两版一起（A + B）');
});
