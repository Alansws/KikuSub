/**
 * 主进程的文件维护（无 Electron 依赖，方便用 node 直接验证）。
 *
 * 两件事：
 *  1. 退出前列出「转写选区碎 SRT」与视频代理，供渲染进程勾选保留；
 *  2. 日志目录的保留策略（按天 + 总量），防止主进程/侧车日志越堆越多。
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SUBTITLE_EXTS = new Set(['.srt', '.vtt', '.txt']);
// 与 core/subtitles.py 的 format_time_tag 对应：00m40s-00m52s / 01h02m03s
const RANGE_TAG = /_(?:(?:\d{1,})h)?\d{1,}m\d{1,}s-(?:(?:\d{1,})h)?\d{1,}m\d{1,}s(?=[._-]|$)/;
const OPEN_TAG = /_(?:from|to)_(?:(?:\d{1,})h)?\d{1,}m\d{1,}s(?=[._-]|$)/;
// 这些是「工作稿/已导出」而不是临时碎片：即使是区间转写，也不能在退出时默认清掉。
// .autosave_draft 是核对期暂存，用户重新打开应用后要靠它恢复进度。
const WORKING_SUFFIX = /\.(?:autosave_draft|review_draft|reviewed|clean)$/;

/** 文件名本身是否是「区间转写」产物（含 .qwen / .part_cancelled / .fixed 等尾缀）。 */
function isFragmentSubtitle(name) {
  const lower = String(name || '').toLowerCase();
  if (!SUBTITLE_EXTS.has(path.extname(lower))) return false;
  const stem = path.basename(lower, path.extname(lower));
  if (WORKING_SUFFIX.test(stem)) return false;
  return RANGE_TAG.test(name) || OPEN_TAG.test(name);
}

function safeStat(target) {
  try {
    return fs.statSync(target);
  } catch {
    return null;
  }
}

/**
 * 本次运行产生的临时产物。
 *
 * `sinceMs` 用进程启动时间：只把这一次运行新写的文件拿来问用户，避免把历史
 * 项目里仍有用的素材/字幕一股脑列出来。传 0 表示列出全部（诊断用）。
 */
function listCleanupCandidates(outputDir, sinceMs = 0) {
  const out = path.resolve(outputDir);
  const items = [];
  const threshold = Number(sinceMs) || 0;

  const collect = (dir, kind) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      const full = path.join(dir, entry.name);
      const isFragment = kind === 'fragment' && isFragmentSubtitle(entry.name);
      const isProxy = kind === 'proxy' && entry.name.toLowerCase().endsWith('.mp4');
      if (!isFragment && !isProxy) continue;
      const stat = safeStat(full);
      if (!stat) continue;
      if (threshold && stat.mtimeMs < threshold) continue;
      items.push({
        path: full,
        name: entry.name,
        kind,
        size: stat.size,
        mtime: stat.mtimeMs,
      });
    }
  };

  collect(out, 'fragment');
  collect(path.join(out, 'web_proxies'), 'proxy');

  items.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'fragment' ? -1 : 1;
    return a.name.localeCompare(b.name, 'zh-Hans-CN');
  });
  return items;
}

/**
 * 删除未勾选的候选文件。
 *
 * 只允许删除 `candidates` 里出现过的路径，渲染进程无法通过伪造路径删别的文件。
 */
function deleteCleanupCandidates(candidates, keepPaths = []) {
  const allowed = new Map(candidates.map((item) => [path.resolve(item.path), item]));
  const keep = new Set((keepPaths || []).map((p) => path.resolve(String(p))));
  let removed = 0;
  let failed = 0;
  let freed = 0;
  const errors = [];

  for (const [full, item] of allowed) {
    if (keep.has(full)) continue;
    try {
      const stat = safeStat(full);
      fs.unlinkSync(full);
      removed += 1;
      freed += stat ? stat.size : item.size || 0;
    } catch (err) {
      failed += 1;
      errors.push(`${item.name}: ${err && err.message ? err.message : err}`);
    }
  }
  return { removed, failed, freed, errors };
}

function isLogFile(name) {
  const lower = String(name || '').toLowerCase();
  return lower.endsWith('.log') || lower.includes('.log.');
}

/**
 * 日志保留：默认保留 14 天、整个日志目录最多 64 MB。
 *
 * 只删轮转出来的备份（kikusub.log.1 / main.log.1 …），永远不碰正在写的
 * `kikusub.log` 与 `main.log`——正在写的那个由 RotatingFileHandler 自己轮转。
 */
function pruneLogs(logDir, options = {}) {
  const dir = path.resolve(logDir);
  const maxAgeDays = options.maxAgeDays ?? 14;
  const maxTotalBytes = options.maxTotalBytes ?? 64 * 1024 * 1024;
  const activeNames = new Set(options.activeNames || ['kikusub.log', 'main.log']);
  const cutoff = Date.now() - maxAgeDays * 24 * 60 * 60 * 1000;

  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return { removed: 0, freed: 0, totalBytes: 0, kept: 0 };
  }

  const files = [];
  for (const entry of entries) {
    if (!entry.isFile() || !isLogFile(entry.name)) continue;
    const full = path.join(dir, entry.name);
    const stat = safeStat(full);
    if (!stat) continue;
    files.push({ path: full, name: entry.name, size: stat.size, mtimeMs: stat.mtimeMs });
  }

  let removed = 0;
  let freed = 0;
  const remove = (file) => {
    try {
      fs.unlinkSync(file.path);
      removed += 1;
      freed += file.size;
      return true;
    } catch {
      return false;
    }
  };

  // 1) 过期备份
  for (const file of files) {
    if (activeNames.has(file.name)) continue;
    if (file.mtimeMs < cutoff) remove(file);
  }

  // 2) 总量上限：从最旧的备份开始删，直到达标或只剩活动日志
  let remaining = files.filter((file) => fs.existsSync(file.path));
  let total = remaining.reduce((n, file) => n + file.size, 0);
  const backups = remaining
    .filter((file) => !activeNames.has(file.name))
    .sort((a, b) => a.mtimeMs - b.mtimeMs);
  for (const file of backups) {
    if (total <= maxTotalBytes) break;
    if (remove(file)) total -= file.size;
  }
  remaining = files.filter((file) => fs.existsSync(file.path));

  return {
    removed,
    freed,
    totalBytes: remaining.reduce((n, file) => n + file.size, 0),
    kept: remaining.length,
  };
}

module.exports = {
  deleteCleanupCandidates,
  isFragmentSubtitle,
  listCleanupCandidates,
  pruneLogs,
};
