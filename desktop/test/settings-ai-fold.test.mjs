import assert from 'node:assert/strict';
import test from 'node:test';

import { advancedAiInUse, advancedAiMeta } from '../renderer/src/lib/settings/aiFold.ts';

/** 默认配置：没填判定覆盖、没开自动判定。 */
const base = {
  auto_arbitrate: false,
  arbitrate_base_url: '',
  arbitrate_model: '',
  arbitrate_loopback: false,
};

test('读不到配置时不展开、也没有摘要', () => {
  assert.equal(advancedAiInUse(null, false), false);
  assert.equal(advancedAiInUse(null, true), false);
  assert.equal(advancedAiMeta(null, false), '');
});

test('全新配置默认收起：跟随全局、自动判定关', () => {
  assert.equal(advancedAiInUse(base, false), false);
  assert.equal(advancedAiMeta(base, false), '跟随全局 · 自动判定关');
});

test('填过判定服务地址或判定模型就默认展开', () => {
  assert.equal(advancedAiInUse({ ...base, arbitrate_base_url: 'http://127.0.0.1:1234/v1' }, false), true);
  assert.equal(advancedAiInUse({ ...base, arbitrate_model: 'qwen3.8-27b' }, false), true);
});

test('只存过判定 Key 也算配过，默认展开（否则 Key 被折叠藏起来）', () => {
  assert.equal(advancedAiInUse(base, true), true);
  assert.equal(advancedAiMeta(base, true), '已单独配置 · 自动判定关');
});

test('开了自动判定就默认展开', () => {
  const cfg = { ...base, auto_arbitrate: true };
  assert.equal(advancedAiInUse(cfg, false), true);
  assert.equal(advancedAiMeta(cfg, false), '跟随全局 · 自动判定开');
});

test('空白字符不算「填过」', () => {
  assert.equal(advancedAiInUse({ ...base, arbitrate_base_url: '   ', arbitrate_model: ' ' }, false), false);
  assert.equal(advancedAiMeta({ ...base, arbitrate_base_url: '  ' }, false), '跟随全局 · 自动判定关');
});

test('本机 loopback 时摘要写「本机 LM Studio」，远程覆盖写「已单独配置」', () => {
  const local = {
    ...base,
    arbitrate_base_url: 'http://127.0.0.1:1234/v1',
    arbitrate_model: 'qwen3.8-27b',
    arbitrate_loopback: true,
    auto_arbitrate: true,
  };
  assert.equal(advancedAiMeta(local, false), '本机 LM Studio · 自动判定开');

  const remote = { ...base, arbitrate_base_url: 'https://api.example.com/v1', arbitrate_model: 'm' };
  assert.equal(advancedAiMeta(remote, false), '已单独配置 · 自动判定关');
});
