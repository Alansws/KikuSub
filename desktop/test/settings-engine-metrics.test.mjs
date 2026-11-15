import assert from 'node:assert/strict';
import test from 'node:test';

import {
  UNKNOWN_SEGMENT_RATIO,
  engineGroupOf,
  engineMetrics,
  formatSpeed,
  isMeasuredEngine,
  segmentFlex,
  segmentLegend,
  speedMultiplier,
  usageSummary,
} from '../renderer/src/lib/settings/engineMetrics.ts';

const rows = (key) => Object.fromEntries(engineMetrics(key).map((row) => [row.key, row]));

test('速度用正向倍数：数字越大 = 越快，且和条长同向', () => {
  // 830s 素材：Whisper 116s、Qwen 54s；345s 素材：SenseVoice 7.5s、FireRed 103s
  assert.equal(formatSpeed(speedMultiplier('whisper')), '7.2× 实时');
  assert.equal(formatSpeed(speedMultiplier('qwen')), '15.4× 实时');
  assert.equal(formatSpeed(speedMultiplier('sensevoice')), '46× 实时');
  assert.equal(formatSpeed(speedMultiplier('firered')), '3.3× 实时');

  const ja = rows('whisper');
  assert.ok(
    Number.parseFloat(rows('qwen').speed.value) > Number.parseFloat(ja.speed.value),
    'Qwen 的倍数应大于 Whisper',
  );
  assert.ok(rows('qwen').speed.bar > ja.speed.bar, '更快的那个条必须更长');

  const zh = rows('sensevoice');
  assert.ok(zh.speed.bar > rows('firered').speed.bar, '更快的那个条必须更长（中文）');
});

test('条长：同语种内归一，跨数量级仍可读', () => {
  assert.equal(rows('qwen').speed.bar, 100);
  assert.equal(rows('whisper').speed.bar, 68);
  assert.equal(rows('sensevoice').speed.bar, 100);
  // 46× 比 3.3× 快 14 倍，线性会只剩 7%，平方根压缩后是 27 —— 既单调又能看见
  assert.equal(rows('firered').speed.bar, 27);
});

test('时间轴：日语用起点 p90，中文用边界 F1，都是「越大越好」', () => {
  assert.equal(rows('qwen').timeline.value, '±0.36s');
  assert.equal(rows('whisper').timeline.value, '±1.35s');
  assert.equal(rows('sensevoice').timeline.value, 'F1 0.68');
  assert.equal(rows('firered').timeline.value, 'F1 0.55');

  assert.equal(rows('qwen').timeline.bar, 100);
  assert.equal(rows('whisper').timeline.bar, 27);
  assert.equal(rows('sensevoice').timeline.bar, 100);
  assert.equal(rows('firered').timeline.bar, 80);
});

test('内存：日语是实测峰值，中文是权重体积，条越长越费', () => {
  assert.equal(rows('whisper').memory.value, '6.7 GB');
  assert.equal(rows('qwen').memory.value, '5.1 GB');
  assert.equal(rows('sensevoice').memory.value, '0.23 GB 权重');
  assert.equal(rows('firered').memory.value, '1.4 GB 权重');

  assert.equal(rows('whisper').memory.bar, 100);
  assert.equal(rows('qwen').memory.bar, 76);
  assert.equal(rows('sensevoice').memory.bar, 16);
  assert.equal(rows('firered').memory.bar, 100);

  // 内存条是「成本」色，速度/时间轴是「分数」色
  assert.equal(rows('whisper').memory.tone, 'cost');
  assert.equal(rows('whisper').speed.tone, 'score');
});

test('未收录的引擎返回空数组，不编造指标', () => {
  assert.deepEqual(engineMetrics('tts'), []);
  assert.deepEqual(engineMetrics('unknown-engine'), []);
  assert.equal(isMeasuredEngine('whisper'), true);
  assert.equal(isMeasuredEngine('omnivoice'), false);
  assert.equal(engineGroupOf('qwen'), 'ja');
  assert.equal(engineGroupOf('firered'), 'zh');
  assert.equal(engineGroupOf('tts'), null);
});

const GB = 1024 ** 3;
const engines = [
  { key: 'whisper', installed: true, sizeBytes: 2.8 * GB },
  { key: 'qwen', installed: true, sizeBytes: 3.8 * GB },
  { key: 'sensevoice', installed: true, sizeBytes: 229 * 1024 ** 2 },
  { key: 'firered', installed: false, sizeBytes: 0 },
];

test('占用条：日语/中文按已安装体积求和，未安装用 0', () => {
  const summary = usageSummary(engines, false);
  const byId = Object.fromEntries(summary.segments.map((s) => [s.id, s]));
  assert.equal(byId.ja.bytes, Math.round(6.6 * GB));
  assert.equal(byId.zh.bytes, Math.round(229 * 1024 ** 2));
  assert.equal(byId.zh.installed, true);
  assert.equal(byId.ja.known, true);
  assert.equal(summary.totalBytes, Math.round(6.6 * GB) + Math.round(229 * 1024 ** 2));

  // 未安装的引擎不计入体积，但「这一类有没有装」仍要正确
  assert.equal(usageSummary([{ key: 'firered', installed: false, sizeBytes: 0 }], false).totalBytes, 0);
});

test('音色克隆没有字节数：标成未计量，但条上留固定视觉位', () => {
  const summary = usageSummary(engines, true);
  const clone = summary.segments.find((s) => s.id === 'clone');
  assert.equal(clone.known, false);
  assert.equal(clone.bytes, 0);
  assert.equal(clone.installed, true);
  assert.equal(summary.cloneInstalled, true);

  const flex = segmentFlex(summary);
  assert.equal(flex.length, 3);
  assert.equal(flex[0], Math.round(6.6 * GB));
  assert.equal(flex[2], Math.round(summary.totalBytes * UNKNOWN_SEGMENT_RATIO));

  assert.equal(segmentLegend(clone, () => 'x'), '音色克隆 已安装（未计量）');
  assert.equal(
    segmentLegend({ ...clone, installed: false }, () => 'x'),
    '音色克隆 未安装',
  );
  assert.equal(segmentLegend(summary.segments[0], () => '6.6 GB'), '日语 6.6 GB');
  assert.equal(
    segmentLegend({ ...summary.segments[0], bytes: 0 }, () => '0 B'),
    '日语 未安装',
  );
});

test('占用条在总量为 0 时也不会算出 NaN / 0 宽的未计量段', () => {
  const summary = usageSummary([], false);
  assert.equal(summary.totalBytes, 0);
  const flex = segmentFlex(summary);
  assert.deepEqual(flex, [0, 0, 1], '占位段至少 1，避免除零');
});
