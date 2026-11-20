/**
 * 检查器草稿提交桥（2026-11-17）。
 *
 * 复制 / 粘贴字幕既可以从检查器按钮触发，也可以从 App.svelte 的快捷键触发。
 * 两条路径都必须先把「右侧文本框里还没失焦的草稿」提交掉，否则会复制到旧文本，
 * 或者在 PATCH 还没返回时插入新句、造成覆盖冲突。
 *
 * 检查器在自己的生命周期里注册 `commit()`；这里只保留一个回调，不碰 store，
 * 因此不会给 `store.svelte.ts` 增加行数（红线 11）。
 */

type CommitFn = () => Promise<void> | void;

let commitFn: CommitFn | null = null;

/** 检查器挂载时注册；返回注销函数，交给 `onMount` 的 cleanup。 */
export function registerCueDraftCommit(fn: CommitFn): () => void {
  commitFn = fn;
  return () => {
    if (commitFn === fn) commitFn = null;
  };
}

/**
 * 等当前草稿提交完成。
 *
 * 没有注册（检查器未挂载）或提交本身出错时都不抛出：`updateCue` 已经会 toast，
 * 复制 / 粘贴继续按当前已落地的状态执行。
 */
export async function flushCueDraft(): Promise<void> {
  if (!commitFn) return;
  try {
    await commitFn();
  } catch {
    /* 检查器的 commit 自己处理错误；这里只保证调用方不会卡住 */
  }
}
