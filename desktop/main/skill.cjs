'use strict';

/**
 * 「一键配置 Agent 技能」：把随包的 skill 目录装到用户的技能根目录。
 *
 * 为什么放主进程：渲染进程没有文件系统权限（contextIsolation + 无 node）。
 * 这里刻意只用 fs，不引 electron —— 于是可以被 `node --test` 直接覆盖。
 *
 * 安装语义：
 *   - 先删目标目录再整份复制，避免旧版本残留的 references 留在那里；
 *   - 复制完写一份 `references/paths.json`，告诉 agent「字幕在哪、提案写到哪」；
 *   - 幂等：重复安装结果一致，`paths.json` 用最新的目录覆盖。
 */

const fs = require('node:fs');
const path = require('node:path');

const SKILL_NAME = 'kikusub-subtitle';
const SKILL_DIR_NAME = 'kikusub-subtitle';

/**
 * 用户级技能根：`<home>/.agents/skills/kikusub-subtitle`。
 *
 * DSH（DeepSeek Harness）的用户级技能根只有 `<dshHome>/skills`（`~/.dsh/skills`）与
 * `<agentsHome>/skills`（`~/.agents/skills`）；`~/.claude/skills` 是 Claude Code 的根，
 * DSH **不扫**（`@deepseek-ai/dsh-skill-filesystem` 的根目录表）。装错根的表现就是：
 * 目录明明存在、`SKILL.md` 也合法，但 `/` 斜杠菜单里永远看不到它。
 */
function defaultTargetDir({ home }) {
  return path.join(home, '.agents', 'skills', SKILL_DIR_NAME);
}

/** 递归列出目录下的文件（相对路径，正斜杠）。 */
function listFiles(dir, prefix = '') {
  let out = [];
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) out = out.concat(listFiles(path.join(dir, entry.name), rel));
    else out.push(rel);
  }
  return out.sort();
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * 当前安装状态。
 *
 * `upToDate` 用来提示用户"随包技能更新了，点一下重新配置"：比较文件清单与大小，
 * 任一文件缺失或大小不同就算需要更新。
 */
function status({ sourceDir, targetDir }) {
  const sourceFiles = listFiles(sourceDir);
  const installed = fs.existsSync(path.join(targetDir, 'SKILL.md'));
  const installedFiles = installed ? listFiles(targetDir) : [];

  const missing = sourceFiles.filter((rel) => !installedFiles.includes(rel));
  let changed = [];
  if (installed && !missing.length) {
    for (const rel of sourceFiles) {
      try {
        const a = fs.statSync(path.join(sourceDir, rel)).size;
        const b = fs.statSync(path.join(targetDir, rel)).size;
        if (a !== b) changed.push(rel);
      } catch {
        changed.push(rel);
      }
    }
  }

  const meta = installed ? readJson(path.join(targetDir, 'references', 'paths.json')) : null;

  return {
    name: SKILL_NAME,
    sourceDir,
    targetDir,
    installed,
    upToDate: installed && !missing.length && !changed.length,
    fileCount: installedFiles.filter((rel) => rel !== 'references/paths.json').length,
    sourceFileCount: sourceFiles.length,
    installedAt: meta && typeof meta.installed_at === 'number' ? meta.installed_at : 0,
    paths: meta || null,
  };
}

/** 整份安装/覆盖。`paths` 由渲染层给（它知道 export_dir / output_dir）。 */
function install({ sourceDir, targetDir, paths = {} }) {
  if (!fs.existsSync(path.join(sourceDir, 'SKILL.md'))) {
    throw new Error(`随包技能目录不完整：${sourceDir}`);
  }

  fs.rmSync(targetDir, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(targetDir), { recursive: true });
  fs.cpSync(sourceDir, targetDir, { recursive: true });

  const payload = {
    version: 1,
    skill: SKILL_NAME,
    installed_at: Math.floor(Date.now() / 1000),
    output_dir: String(paths.output_dir || ''),
    export_dir: String(paths.export_dir || ''),
  };
  fs.mkdirSync(path.join(targetDir, 'references'), { recursive: true });
  fs.writeFileSync(
    path.join(targetDir, 'references', 'paths.json'),
    `${JSON.stringify(payload, null, 2)}\n`,
    'utf8',
  );

  return status({ sourceDir, targetDir });
}

module.exports = { SKILL_NAME, defaultTargetDir, listFiles, status, install };
