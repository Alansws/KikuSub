'use strict';

/**
 * AI 密钥本机加密的回归用例。
 *
 * 这里守的是"升级应用不会把 key 弄丢"这条：整套逻辑不碰钥匙串，只依赖一个
 * 0600 的主密钥文件，所以 roundtrip、篡改、换密钥三种情况都必须有确定行为。
 */

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  PREFIX,
  decrypt,
  encrypt,
  ensureKeyFile,
  isLocalBlob,
  readKeyFile,
} = require('../main/aikey.cjs');

const KEY = crypto.randomBytes(32);

function tmpfile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kikusub-key-'));
  return path.join(dir, 'key.bin');
}

test('roundtrip', () => {
  const blob = encrypt('sk-1234567890', KEY);
  assert.ok(blob.startsWith(PREFIX));
  assert.equal(decrypt(blob, KEY), 'sk-1234567890');
});

test('两次加密的密文不同（随机 IV）', () => {
  assert.notEqual(encrypt('same', KEY), encrypt('same', KEY));
});

test('换一把主密钥解不开', () => {
  const blob = encrypt('secret', KEY);
  assert.equal(decrypt(blob, crypto.randomBytes(32)), null);
});

test('篡改密文会被 GCM 拦住', () => {
  const blob = encrypt('secret', KEY);
  const raw = Buffer.from(blob.slice(PREFIX.length), 'base64');
  raw[raw.length - 1] ^= 0xff;
  assert.equal(decrypt(PREFIX + raw.toString('base64'), KEY), null);
});

test('历史 safeStorage blob 不会被误认成本机密文', () => {
  const legacy = crypto.randomBytes(40).toString('base64');
  assert.equal(isLocalBlob(legacy), false);
  assert.equal(decrypt(legacy, KEY), null);
});

test('空串与超短密文返回 null', () => {
  assert.equal(decrypt(PREFIX, KEY), null);
  assert.equal(decrypt('', KEY), null);
  assert.equal(decrypt(null, KEY), null);
});

test('主密钥文件第一次生成、第二次复用，权限 600', () => {
  const file = tmpfile();
  assert.equal(readKeyFile(file), null);

  const first = ensureKeyFile(file);
  assert.equal(first.length, 32);
  const second = ensureKeyFile(file);
  assert.ok(first.equals(second), '重复调用不能换密钥，否则旧密文全废');

  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test('主密钥文件长度损坏时视为没有，会重新生成', () => {
  const file = tmpfile();
  ensureKeyFile(file);
  fs.writeFileSync(file, Buffer.alloc(7));
  assert.equal(readKeyFile(file), null);
  assert.equal(ensureKeyFile(file).length, 32);
});
