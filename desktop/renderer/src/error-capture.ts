/**
 * 把渲染进程的未捕获异常留一份在 window.__lastError 里。
 *
 * Electron 的 `console-message` 只给一行消息，Svelte 的
 * `effect_update_depth_exceeded` 不带堆栈，光看日志根本定位不到是哪个组件。
 * 这份捕获让 `KIKUSUB_DEV_EVAL=JSON.stringify(window.__lastError)` 能拿到堆栈。
 */
declare global {
  interface Window {
    __lastError?: { message: string; stack?: string; at: number };
  }
}

function remember(message: string, stack?: string) {
  window.__lastError = { message, stack, at: Date.now() };
}

window.addEventListener('error', (e) => {
  remember(e.message, e.error?.stack);
});
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason as { message?: string; stack?: string } | undefined;
  remember(String(reason?.message ?? reason), reason?.stack);
});

export {};
