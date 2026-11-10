/**
 * AI 密钥的本机加密（纯 Node，不依赖 Electron）。
 *
 * 为什么不用 `safeStorage`：它把密钥托管在系统钥匙串里，而 keychain 条目的 ACL 绑定
 * 的是**代码签名要求**。本项目以 DMG 分发、ad-hoc 签名，**每次发版 cdhash 都变**，
 * 用户升级后新二进制读不回旧条目——每个版本都要重填一次 Key，且没有 Developer ID
 * 就无从修复。本方案与版本号无关。
 *
 * 现在的方案：32 字节随机主密钥存在 `{dataDir}/.ai-key`（0600），preferences.json 里
 * 只放 AES-256-GCM 密文。重装、升级、换 Electron 版本都不影响。
 *
 * **诚实的边界**：这不是"防得住本机攻击者"的加密——主密钥和密文在同一台机器上，能读
 * 应用数据目录的人两者都拿得到。它挡的是「把 preferences.json 单独拷走/误传」，
 * 以及「明文躺在配置里」。
 */

'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

/** 密文前缀：用来区分历史遗留的 safeStorage blob（`v10…`）与本方案的密文。 */
const PREFIX = 'aik1:';
const KEY_BYTES = 32;
const IV_BYTES = 12;
const TAG_BYTES = 16;

function isLocalBlob(value) {
  return typeof value === 'string' && value.startsWith(PREFIX);
}

function encrypt(text, key) {
  if (!Buffer.isBuffer(key) || key.length !== KEY_BYTES) {
    throw new Error('主密钥长度不对');
  }
  const iv = crypto.randomBytes(IV_BYTES);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const body = Buffer.concat([cipher.update(String(text), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return PREFIX + Buffer.concat([iv, tag, body]).toString('base64');
}

/** 解不开一律返回 null：调用方据此区分「没配」与「配了但读不出来」。 */
function decrypt(blob, key) {
  if (!isLocalBlob(blob) || !Buffer.isBuffer(key) || key.length !== KEY_BYTES) return null;
  let raw;
  try {
    raw = Buffer.from(blob.slice(PREFIX.length), 'base64');
  } catch {
    return null;
  }
  if (raw.length < IV_BYTES + TAG_BYTES + 1) return null;
  const iv = raw.subarray(0, IV_BYTES);
  const tag = raw.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
  const body = raw.subarray(IV_BYTES + TAG_BYTES);
  try {
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(body), decipher.final()]).toString('utf8');
  } catch {
    // GCM 校验失败（文件被改过/换了主密钥）——当作读不出来
    return null;
  }
}

/** 读主密钥文件；不存在或长度不对返回 null（不在这里创建，方便区分"坏了"与"没有"）。 */
function readKeyFile(file) {
  try {
    const raw = fs.readFileSync(file);
    return raw.length === KEY_BYTES ? raw : null;
  } catch {
    return null;
  }
}

/** 取主密钥，没有就生成一个 0600 的文件。 */
function ensureKeyFile(file) {
  const existing = readKeyFile(file);
  if (existing) {
    try {
      fs.chmodSync(file, 0o600);
    } catch {
      /* 改不动就算了，不影响功能 */
    }
    return existing;
  }
  const key = crypto.randomBytes(KEY_BYTES);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, key, { mode: 0o600 });
  try {
    fs.chmodSync(file, 0o600);
  } catch {
    /* 同上 */
  }
  return key;
}

module.exports = { PREFIX, KEY_BYTES, isLocalBlob, encrypt, decrypt, readKeyFile, ensureKeyFile };
