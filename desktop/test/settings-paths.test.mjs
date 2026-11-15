import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  ALL_PATHS,
  EDITABLE_PATHS,
  INTERNAL_PATHS,
  allPathKeys,
  isCustomDir,
  pathBadge,
  pathValue,
  videoExportDisplay,
  videoFollowsExport,
} from '../renderer/src/lib/settings/pathGroups.ts';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/**
 * 路径分组必须覆盖后端 `SettingsPayload['paths']` 的全部键（`log_path` 除外，
 * 它是日志文件本身，显示在「日志与诊断」的摘要行里，不进路径列表）。
 *
 * 直接解析 api.ts 而不是抄一份键名：后端加了一条路径、这里忘了分组时，
 * 它既不在明面也不在折叠区——等于静默消失，用户再也点不到它。
 */
function backendPathKeys() {
  const source = fs.readFileSync(
    path.join(HERE, '..', 'renderer', 'src', 'lib', 'api.ts'),
    'utf8',
  );
  const start = source.indexOf('export interface SettingsPayload');
  assert.notEqual(start, -1, '找不到 SettingsPayload');
  const pathsAt = source.indexOf('paths: {', start);
  assert.notEqual(pathsAt, -1, 'SettingsPayload 里没有 paths 定义');
  const close = source.indexOf('};', pathsAt);
  const block = source.slice(pathsAt, close);
  return [...block.matchAll(/^\s{4}([a-z_]+):\s*string;/gm)].map((match) => match[1]);
}

test('路径分组覆盖后端全部键：3 条可改 + 8 条只读', () => {
  assert.equal(EDITABLE_PATHS.length, 3);
  assert.equal(INTERNAL_PATHS.length, 8);
  assert.equal(ALL_PATHS.length, 11);

  const keys = allPathKeys();
  assert.equal(new Set(keys).size, keys.length, '路径键不能重复');

  const backend = backendPathKeys().filter((key) => key !== 'log_path');
  assert.deepEqual(
    [...keys].sort(),
    [...backend].sort(),
    '后端新增/删除了路径时，pathGroups.ts 要同步（log_path 由日志面板显示）',
  );
});

test('每行都有标签；可改的 3 条顺序固定为 导出 → 成片 → 模型', () => {
  assert.deepEqual(
    EDITABLE_PATHS.map((row) => row.key),
    ['export_dir', 'video_export_dir', 'models_dir'],
  );
  for (const row of ALL_PATHS) {
    assert.ok(row.label, `${row.key} 缺少标签`);
    assert.ok(row.hint, `${row.key} 缺少说明`);
  }
});

test('pathValue 对缺失/空路径安全', () => {
  assert.equal(pathValue({ export_dir: '/tmp/out' }, 'export_dir'), '/tmp/out');
  assert.equal(pathValue({}, 'export_dir'), '');
  assert.equal(pathValue(null, 'models_dir'), '');
  assert.equal(pathValue(undefined, 'log_dir'), '');
});

test('成片目录：空字符串表示跟随导出文件夹', () => {
  assert.equal(videoFollowsExport(''), true);
  assert.equal(videoFollowsExport('   '), true);
  assert.equal(videoFollowsExport(null), true);
  assert.equal(videoFollowsExport('/Users/sws/Movies/out'), false);

  assert.equal(videoExportDisplay('', '/resolved/path'), '跟随导出文件夹');
  assert.equal(videoExportDisplay('/Users/sws/Movies/out', '/resolved/path'), '/resolved/path');
});

test('行尾标记：自定义 / 默认', () => {
  assert.equal(pathBadge({ export_dir: '/tmp/out' }, 'export_dir'), '自定义');
  assert.equal(pathBadge({ export_dir: '' }, 'export_dir'), '默认');
  assert.equal(pathBadge(null, 'export_dir'), '默认');

  assert.equal(pathBadge({ video_export_dir: '/tmp/v' }, 'video_export_dir'), '自定义');
  assert.equal(pathBadge({ video_export_dir: '' }, 'video_export_dir'), '默认');
  assert.equal(isCustomDir({ export_dir: '/tmp/x' }, 'export_dir'), true);
  assert.equal(isCustomDir({}, 'video_export_dir'), false);
});
