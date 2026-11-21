'use strict';

/** ~/.local/bin/kikusub 安装器：软链语义、冲突保护、PATH 提示。 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const cli = require('../main/cli.cjs');

function sandbox() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kikusub-cli-'));
  const home = path.join(root, 'home');
  const target = path.join(root, 'KikuSub.app', 'Contents', 'MacOS', 'kikusub');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, '#!/bin/sh\n', { mode: 0o755 });
  fs.mkdirSync(home, { recursive: true });
  return { root, home, target };
}

test('targetPath: packaged 与主可执行文件同级', () => {
  assert.equal(
    cli.targetPath({ isPackaged: true, execPath: '/Applications/KikuSub.app/Contents/MacOS/KikuSub' }),
    '/Applications/KikuSub.app/Contents/MacOS/kikusub',
  );
  assert.equal(
    cli.targetPath({ isPackaged: false, execPath: '/x/y', repoRoot: '/repo' }),
    '/repo/build/pack/dist/kikusub',
  );
});

test('install 建立软链，status 反映 upToDate', () => {
  const { home, target } = sandbox();
  assert.equal(cli.status({ home, target, pathEnv: '' }).installed, false);

  cli.install({ home, target });
  const state = cli.status({ home, target, pathEnv: '' });
  assert.equal(state.installed, true);
  assert.equal(state.upToDate, true);
  assert.equal(state.conflict, false);
  assert.equal(fs.realpathSync(cli.linkPath(home)), fs.realpathSync(target));
  assert.equal(fs.lstatSync(cli.linkPath(home)).isSymbolicLink(), true);
});

test('install 遇到同名普通文件时拒绝覆盖', () => {
  const { home, target } = sandbox();
  fs.mkdirSync(cli.binDir(home), { recursive: true });
  fs.writeFileSync(cli.linkPath(home), 'user file');
  assert.throws(() => cli.install({ home, target }), /不是软链/);
  assert.equal(fs.readFileSync(cli.linkPath(home), 'utf8'), 'user file');
  assert.equal(cli.status({ home, target, pathEnv: '' }).conflict, true);
});

test('install 目标不存在时拒绝', () => {
  const { home } = sandbox();
  assert.throws(() => cli.install({ home, target: path.join(home, 'missing') }), /找不到/);
});

test('uninstall 只删指向当前目标的软链', () => {
  const { root, home, target } = sandbox();
  cli.install({ home, target });
  assert.equal(cli.uninstall({ home, target }).removed, true);
  assert.equal(cli.status({ home, target, pathEnv: '' }).installed, false);

  const other = path.join(root, 'other-kikusub');
  fs.writeFileSync(other, '#!/bin/sh\n');
  fs.symlinkSync(other, cli.linkPath(home));
  assert.throws(() => cli.uninstall({ home, target }), /别的程序/);
  assert.equal(fs.existsSync(cli.linkPath(home)), true);
});

test('inPath 同时接受原路径与 realpath', () => {
  const { home } = sandbox();
  const dir = cli.binDir(home);
  assert.equal(cli.status({ home, target: '', pathEnv: dir }).inPath, true);
  assert.equal(cli.status({ home, target: '', pathEnv: '/usr/bin:/bin' }).inPath, false);
});

test('pathHint 给出 zshrc 命令与兜底说明', () => {
  const { home } = sandbox();
  const hint = cli.pathHint({ home });
  assert.match(hint.command, /\.zshrc/);
  assert.match(hint.line, /\$HOME\/\.local\/bin/);
  assert.ok(hint.note.includes('默认不在 PATH'));
});
