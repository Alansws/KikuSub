'use strict';

/**
 * 双开 / 试用版隔离身份（纯函数，2026-11-25）。
 *
 * 正式包不含 `Contents/Resources/app-isolation.json`，所有取值回落到现役默认
 * （产品名 KikuSub、数据根 `Application Support/KikuSub`），行为不变。
 * `tools/pack/build_trial.sh` 装配试用版时写入：
 *
 *   { "appName": "KikuSub-Next", "dataDirName": "KikuSub-Next" }
 *
 * 主进程据 `dataDirName` 换 Electron userData / sessionData 与用户数据根，从而
 * 与现役 KikuSub.app 真正双开、互不读写 settings / presets / `.ai-key`。
 *
 * 安全边界：只接受单段目录名（字母数字开头，允许 `. _ -`，≤64 字符），拒绝
 * `/`、`..`、空串与绝对路径，避免隔离配置把数据写到别处。
 */

const path = require('node:path');

const FILE_NAME = 'app-isolation.json';
const DEFAULT_DATA_DIR = 'KikuSub';
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function sanitizeName(value) {
  return typeof value === 'string' && SAFE_NAME.test(value) ? value : '';
}

/**
 * 读取包内隔离身份；任何异常都回落到空对象（= 正式包默认行为）。
 *
 * @param {{ isPackaged: boolean, resourcesPath?: string, readFile?: (p: string) => string }} input
 */
function readIsolation({ isPackaged, resourcesPath, readFile } = {}) {
  const empty = { appName: '', dataDirName: '' };
  if (!isPackaged || !resourcesPath) return empty;
  try {
    const reader = readFile || ((file) => require('node:fs').readFileSync(file, 'utf8'));
    const raw = JSON.parse(reader(path.join(resourcesPath, FILE_NAME)));
    if (!raw || typeof raw !== 'object') return empty;
    return {
      appName: sanitizeName(raw.appName),
      dataDirName: sanitizeName(raw.dataDirName),
    };
  } catch {
    return empty;
  }
}

/** 用户可写数据根的目录名：隔离包用自己的，正式包仍是 KikuSub。 */
function dataDirName(isolation) {
  return (isolation && isolation.dataDirName) || DEFAULT_DATA_DIR;
}

/**
 * 数据根（Chromium userData / sessionData 与 settings 等都落在这一处）。
 *
 * `KIKUSUB_ISOLATION_ROOT` 只对隔离包生效：给无窗口冒烟 / 调试一个可写的临时根，
 * 同时保证正式包永远不会因为一个环境变量把用户数据搬走。只接受绝对路径。
 */
function resolveRoot({ appData, dataDirName: name, env = {}, allowOverride = false } = {}) {
  if (allowOverride) {
    const override = String(env.KIKUSUB_ISOLATION_ROOT || '').trim();
    if (override && path.isAbsolute(override)) return path.resolve(override);
  }
  return path.join(appData, name || DEFAULT_DATA_DIR);
}

module.exports = {
  FILE_NAME,
  DEFAULT_DATA_DIR,
  sanitizeName,
  readIsolation,
  dataDirName,
  resolveRoot,
};
