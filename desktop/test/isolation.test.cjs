'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const isolation = require('../main/isolation.cjs');

function tempResources(payload) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kikusub-isolation-'));
  if (payload !== undefined) {
    const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
    fs.writeFileSync(path.join(dir, isolation.FILE_NAME), body, 'utf8');
  }
  return dir;
}

test('正式包没有身份文件：回落到 KikuSub 数据根', () => {
  const resourcesPath = tempResources();
  const config = isolation.readIsolation({ isPackaged: true, resourcesPath });
  assert.deepEqual(config, { appName: '', dataDirName: '' });
  assert.equal(isolation.dataDirName(config), 'KikuSub');
});

test('开发模式不读身份文件（开发照样用仓库目录）', () => {
  const resourcesPath = tempResources({ appName: 'KikuSub-Next', dataDirName: 'KikuSub-Next' });
  assert.deepEqual(isolation.readIsolation({ isPackaged: false, resourcesPath }), {
    appName: '',
    dataDirName: '',
  });
});

test('试用版读取独立产品名与数据根', () => {
  const resourcesPath = tempResources({
    appName: 'KikuSub-Next',
    dataDirName: 'KikuSub-Next',
  });
  const config = isolation.readIsolation({ isPackaged: true, resourcesPath });
  assert.deepEqual(config, { appName: 'KikuSub-Next', dataDirName: 'KikuSub-Next' });
  assert.equal(isolation.dataDirName(config), 'KikuSub-Next');
});

test('损坏的 JSON 不抛错，回落正式默认值', () => {
  const resourcesPath = tempResources('{ not json');
  assert.deepEqual(isolation.readIsolation({ isPackaged: true, resourcesPath }), {
    appName: '',
    dataDirName: '',
  });
});

test('拒绝路径穿越 / 绝对路径 / 空串', () => {
  for (const bad of ['../KikuSub-Next', '/tmp/KikuSub-Next', 'a/b', '..', '.', '', '   ']) {
    assert.equal(isolation.sanitizeName(bad), '', bad);
  }
  const resourcesPath = tempResources({ appName: '../evil', dataDirName: '../evil' });
  assert.deepEqual(isolation.readIsolation({ isPackaged: true, resourcesPath }), {
    appName: '',
    dataDirName: '',
  });
});

test('目录名允许的点号 / 下划线 / 连字符仍然可用', () => {
  assert.equal(isolation.sanitizeName('KikuSub-Next_2.0'), 'KikuSub-Next_2.0');
  assert.equal(isolation.sanitizeName('a'.repeat(64)), 'a'.repeat(64));
  assert.equal(isolation.sanitizeName('a'.repeat(65)), '');
});

test('隔离根未被允许时，环境变量不生效（正式包不会被搬走数据）', () => {
  const root = isolation.resolveRoot({
    appData: '/Users/example/Library/Application Support',
    dataDirName: 'KikuSub',
    env: { KIKUSUB_ISOLATION_ROOT: '/tmp/elsewhere' },
    allowOverride: false,
  });
  assert.equal(root, '/Users/example/Library/Application Support/KikuSub');
});

test('隔离包可以用绝对路径把数据根挪到临时目录（只给测试/调试）', () => {
  const root = isolation.resolveRoot({
    appData: '/Users/example/Library/Application Support',
    dataDirName: 'KikuSub-Next',
    env: { KIKUSUB_ISOLATION_ROOT: '/tmp/kikusub-next-root' },
    allowOverride: true,
  });
  assert.equal(root, '/tmp/kikusub-next-root');
});

test('相对路径的隔离根被忽略，仍落在应用数据目录', () => {
  const root = isolation.resolveRoot({
    appData: '/Users/example/Library/Application Support',
    dataDirName: 'KikuSub-Next',
    env: { KIKUSUB_ISOLATION_ROOT: '../escape' },
    allowOverride: true,
  });
  assert.equal(root, '/Users/example/Library/Application Support/KikuSub-Next');
});
