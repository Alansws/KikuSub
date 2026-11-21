import assert from 'node:assert/strict';
import test from 'node:test';

import { setupSummary } from '../renderer/src/lib/engineSetup.ts';

test('有勾选时展示勾选数与体积', () => {
  const items = [{ installed: false }, { installed: false }];
  assert.equal(setupSummary(items, 2, '6.6 GB'), '已选 2 项 · 6.6 GB');
});

test('全部装好且没有勾选时，不再说「未选择任何要下载的模型」', () => {
  const items = [{ installed: true }, { installed: true }, { installed: true }];
  assert.equal(setupSummary(items, 0, '0 B'), '全部模型都已安装，无需再下载');
});

test('装了一部分、这次不勾选：说明本次不下载，已有项可用', () => {
  const items = [{ installed: true }, { installed: true }, { installed: false }];
  assert.equal(setupSummary(items, 0, '0 B'), '本次不下载新模型；已安装的 2 项照常可用');
});

test('一个都没装、也没勾选：给出可执行的下一步', () => {
  const items = [{ installed: false }, { installed: false }];
  assert.equal(
    setupSummary(items, 0, '0 B'),
    '还没有勾选模型；也可以稍后在「设置 → 引擎与模型」里下载',
  );
});

test('模型包缺失时单独给出提示', () => {
  const items = [{ installed: false, packageMissing: true }];
  assert.equal(setupSummary(items, 0, '0 B'), '模型包缺失，请检查安装包或稍后重试');
});

test('还没有读到模型列表时不假装「没勾选」', () => {
  assert.equal(setupSummary([], 0, '0 B'), '正在读取模型状态…');
});
