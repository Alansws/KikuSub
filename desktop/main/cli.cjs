'use strict';

/**
 * 「安装命令行工具」：把 app 内的 `kikusub` 软链到 `~/.local/bin/kikusub`。
 *
 * 为什么放主进程：渲染层没有文件系统权限。这里刻意只用 fs/path/os，不引
 * electron —— 于是可以像 windowmode.cjs / skill.cjs 一样被 `node --test` 覆盖。
 *
 * 选 `~/.local/bin` 而不是 `/usr/local/bin`：macOS 普通用户对后者通常没有写权限，
 * 首次安装会弹系统授权；`~/.local/bin` 不需要 sudo，卸载也只是删一个软链。
 * 代价是它默认不在 PATH 里（见 pathHint），设置页要给出可复制的 `.zshrc` 命令。
 *
 * 安全边界：
 * - 只覆盖**指向本 app 的符号链接**；遇到同名普通文件直接报错，绝不删用户文件；
 * - 目标不存在时拒绝安装（例如只跑了渲染层构建、没打 CLI）；
 * - 卸载只删 realpath 等于当前目标的软链。
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const COMMAND = 'kikusub';

function homeDir(home) {
  return home || os.homedir();
}

function binDir(home) {
  return path.join(homeDir(home), '.local', 'bin');
}

function linkPath(home) {
  return path.join(binDir(home), COMMAND);
}

/** app 内 CLI 的真实路径：打包态与主可执行文件同级；开发态用 build/pack/dist。 */
function targetPath({ isPackaged, execPath, repoRoot }) {
  if (isPackaged) return path.join(path.dirname(execPath), COMMAND);
  return path.join(repoRoot || process.cwd(), 'build', 'pack', 'dist', COMMAND);
}

function realpathOrNull(target) {
  try {
    return fs.realpathSync(target);
  } catch {
    return null;
  }
}

function inPathList(dir, pathEnv) {
  const wanted = realpathOrNull(dir) || path.resolve(dir);
  return String(pathEnv || '')
    .split(path.delimiter)
    .filter(Boolean)
    .some((entry) => (realpathOrNull(entry) || path.resolve(entry)) === wanted);
}

function status({ home, target, pathEnv = process.env.PATH }) {
  const link = linkPath(home);
  const dir = binDir(home);
  const result = {
    command: COMMAND,
    target: target || '',
    linkPath: link,
    binDir: dir,
    targetExists: Boolean(target && fs.existsSync(target)),
    installed: false,
    upToDate: false,
    inPath: inPathList(dir, pathEnv),
    conflict: false,
    error: '',
  };
  let info = null;
  try {
    info = fs.lstatSync(link);
  } catch {
    return result;
  }
  if (!info.isSymbolicLink()) {
    result.conflict = true;
    result.error = `${link} 已存在且不是软链（可能是用户自己放的文件），不会覆盖。`;
    return result;
  }
  const resolved = realpathOrNull(link);
  result.installed = true;
  result.upToDate = Boolean(target && resolved && resolved === realpathOrNull(target));
  return result;
}

function install({ home, target }) {
  if (!target || !fs.existsSync(target)) {
    throw new Error(`找不到 app 内的 kikusub：${target || '(空)'}；先重新构建 .app`);
  }
  const link = linkPath(home);
  fs.mkdirSync(path.dirname(link), { recursive: true });

  let info = null;
  try {
    info = fs.lstatSync(link);
  } catch {
    info = null;
  }
  if (info && !info.isSymbolicLink()) {
    throw new Error(`${link} 已存在且不是软链；请先手动移走它再安装。`);
  }

  const temp = `${link}.tmp.${process.pid}`;
  try {
    fs.rmSync(temp, { force: true });
    fs.symlinkSync(target, temp);
    fs.renameSync(temp, link);
  } finally {
    try {
      if (fs.existsSync(temp)) fs.rmSync(temp, { force: true });
    } catch {
      /* 清理失败不影响结果 */
    }
  }
  return { ok: true, linkPath: link, target };
}

function uninstall({ home, target }) {
  const link = linkPath(home);
  let info = null;
  try {
    info = fs.lstatSync(link);
  } catch {
    return { ok: true, removed: false };
  }
  if (!info.isSymbolicLink()) {
    throw new Error(`${link} 不是软链，拒绝删除（它不是 kikusub 安装的）。`);
  }
  const resolved = realpathOrNull(link);
  if (target && resolved && resolved !== realpathOrNull(target)) {
    throw new Error(`${link} 指向别的程序（${resolved || '已失效'}），拒绝删除。`);
  }
  fs.rmSync(link, { force: true });
  return { ok: true, removed: true };
}

/** 设置页展示的 PATH 引导（macOS 默认不读 ~/.local/bin）。 */
function pathHint({ home } = {}) {
  const dir = binDir(home);
  const line = `export PATH="$HOME/.local/bin:$PATH"`;
  return {
    binDir: dir,
    line,
    command: `echo '${line}' >> ~/.zshrc && source ~/.zshrc`,
    note: 'macOS 默认不把 ~/.local/bin 放进 PATH（默认不在 PATH 里）；写入后重开终端。部分 Agent 不读 .zshrc，必要时在它的环境里显式加。',
  };
}

module.exports = {
  COMMAND,
  binDir,
  linkPath,
  targetPath,
  status,
  install,
  uninstall,
  pathHint,
};
