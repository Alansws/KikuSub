'use strict';

/**
 * 窗口可见性判定 —— **纯函数**，不碰 electron、不碰 fs，`node --test` 直接覆盖。
 *
 * 为什么需要（2026-11-16，用户红线）：智能体每改完一个功能都会「实际过一遍界面」，
 * 于是 `npx electron .` 与截图矩阵把 Electron 窗口反复弹到用户桌面上，打断同一台电脑上
 * 其他正在做的事。弹不弹窗与验证本身无关，所以把「能不能出现可见窗口」变成**必须显式开启**
 * 的决策，而不是默认行为：
 *
 *   1. 截图取证（`--screenshot` / `KIKUSUB_SHOT`）：永不显示，透明窗口取帧；
 *   2. `KIKUSUB_NO_WINDOW=1`：CI / 远程 / 自动化用的总开关，永不显示；
 *   3. 未打包（开发模式）：**默认拒绝启动**，只有 `KIKUSUB_ALLOW_WINDOW=1` 才显示
 *      （`npm start` 与 `desktop/run.sh` 会设置它——那是人的入口）；
 *   4. 打包后的 .app：用户双击就是要看见窗口，默认显示。
 *
 * 刻意不认 `KIKUSUB_ALLOW_WINDOW=true/yes`：环境里随手设个值不该把窗口放出来。
 * 规则出处：`AGENTS.md` §0.5 与 `docs/contracts/desktop-lifecycle.md` §3.7；
 * 单元测试：`desktop/test/window-mode.test.cjs`。
 */

const REASON = {
  /** `--screenshot` 取证：不显示，也不在 Dock 留图标。 */
  SCREENSHOT: 'screenshot',
  /** `KIKUSUB_NO_WINDOW=1`：进程照常跑，但界面对用户不可见。 */
  NO_WINDOW_ENV: 'no-window-env',
  /** 未打包又没许可：直接拒绝启动，别留下一个「跑着但看不见」的进程。 */
  DEV_GUARD: 'dev-guard',
  /** 开发模式 + 显式 `KIKUSUB_ALLOW_WINDOW=1`。 */
  ALLOWED: 'allowed',
  /** 打包版：正常显示。 */
  PACKAGED: 'packaged',
};

/**
 * @param {{ isPackaged?: boolean, shotPath?: string | null, env?: Record<string, string | undefined> }} options
 * @returns {{ visible: boolean, reason: string }}
 */
function resolveWindowMode({ isPackaged = false, shotPath = null, env = {} } = {}) {
  const source = env || {};
  // 截图优先：取证永远不显示，哪怕同时带了 ALLOW_WINDOW。
  if (shotPath) return { visible: false, reason: REASON.SCREENSHOT };
  // 总开关压过一切：自动化说不要窗口就是不要。
  if (source.KIKUSUB_NO_WINDOW === '1') return { visible: false, reason: REASON.NO_WINDOW_ENV };
  if (!isPackaged && source.KIKUSUB_ALLOW_WINDOW !== '1') {
    return { visible: false, reason: REASON.DEV_GUARD };
  }
  if (!isPackaged) return { visible: true, reason: REASON.ALLOWED };
  return { visible: true, reason: REASON.PACKAGED };
}

/** 被拒时打印的说明：必须给出「那该怎么验证」，否则下一个人只会换个命令再试。 */
const NO_WINDOW_REFUSAL = [
  '✋ 已拒绝创建可见窗口：开发模式的 KikuSub 默认不弹窗（AGENTS.md §0.5「无窗口铁律」）。',
  '   验证不需要把界面摆到用户桌面上，所以这里直接退出，而不是默默隐藏。',
  '',
  '   静默取证（不显示任何窗口）：',
  '     bash tools/shots/capture_matrix.sh --states "review settings"',
  '     node tools/shots/verify_reshape_flow.mjs',
  '     (cd desktop && npx electron . --screenshot=/tmp/kikusub.png)',
  '',
  '   人类自己要看见界面（这是人的动作，自动化不要用）：',
  '     cd desktop && npm start            # 或 desktop/run.sh',
  '     KIKUSUB_ALLOW_WINDOW=1 npx electron .',
].join('\n');

module.exports = {
  REASON,
  NO_WINDOW_REFUSAL,
  resolveWindowMode,
};
