'use strict';

/**
 * 启动失败计数与安全模式判定 —— **纯函数**，不碰 fs、不弹窗。
 *
 * 为什么需要：本项目以 DMG 手动分发、没有 autoUpdater。一旦发出去的版本一打开就崩
 * （加载历史工程、迁移旧配置、渲染首帧都可能崩），程序内置的更新检查根本没机会运行，
 * 用户既收不到"修复版已发布"，也不知道该怎么办——除了删掉整个 App。
 *
 * 兜底策略：
 *   1. 每次启动先把 `launchFailures` 加一；
 *   2. 真正跑起来（窗口 shown + sidecar 起好 + STABLE_AFTER_MS 没崩）才清零；
 *   3. 下次启动如果发现上次欠了 >= CRASH_LIMIT 次，直接进安全模式：不建窗口、
 *      不启 sidecar，只弹一个原生对话框给出下载页 / 日志目录 / "仍然尝试一次"。
 *
 * 正常关闭也必须清零（见 main.cjs 的 before-quit），否则"开一下就关"会被误判成崩溃。
 */

/** 多久算"跑起来了"。要盖住模型加载与首帧绘制。 */
const STABLE_AFTER_MS = 8000;

/** 连续几次算"打不开"。2 次足够避开偶发的单次崩溃。 */
const CRASH_LIMIT = 2;

/** 降级下载页：没有更新器时，用户唯一的自救入口。 */
const DOWNLOAD_URL = 'https://github.com/Alansws/KikuSub/releases';

function readFailureCount(prefs) {
  const raw = prefs && prefs.launchFailures;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.floor(n);
}

function shouldEnterSafeMode(prefs, limit = CRASH_LIMIT) {
  return readFailureCount(prefs) >= limit;
}

/** 本次启动要写回的补丁（失败次数 +1，留一条时间戳便于排查）。 */
function attemptPatch(prefs, now = new Date()) {
  return {
    launchFailures: readFailureCount(prefs) + 1,
    lastLaunchAt: now.toISOString(),
  };
}

/** 判定"这次起成功了"时要写回的补丁。已经是 0 时调用方应跳过写盘。 */
function stablePatch() {
  return { launchFailures: 0 };
}

module.exports = {
  STABLE_AFTER_MS,
  CRASH_LIMIT,
  DOWNLOAD_URL,
  readFailureCount,
  shouldEnterSafeMode,
  attemptPatch,
  stablePatch,
};
