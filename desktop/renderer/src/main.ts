import './error-capture';
import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { resolveTheme } from './lib/themes';
import { readAppearancePrefs } from './lib/appearance';
import { initAppearance } from './lib/appearanceState.svelte';

/**
 * 在挂载前先把外观定下来。
 *
 * 以前外观要等 sidecar 握手完成（`boot()`）才写进 `<html data-theme>`，于是
 * 深色模式每次启动都会先闪一下浅色侧栏；同时主进程的原生 vibrancy 还停在
 * 系统外观，红绿灯那一列会透成灰白。这里同步应用一次，并通知主进程。
 *
 * 2026-11-25：外观模型改成「偏好（auto/light/dark）× 系统外观 → data-theme」，
 * 字幕字体单独一个 `data-cue-font`。旧的三主题 key 在这里只做只读迁移，
 * 真正的迁移落在 store 的 `initAppearance()`（它会清掉旧 key）。
 */
const prefs = readAppearancePrefs(localStorage);
const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

document.documentElement.dataset.theme = resolveTheme(prefs.appearance, systemDark ? 'dark' : 'light');
document.documentElement.dataset.cueFont = prefs.cueFont;
window.kikusub?.setAppearance?.(prefs.appearance);

// 补齐 store 状态、迁旧 key、挂上「系统外观变化」监听（auto 时要实时跟着变）
initAppearance();

// Svelte 5 用 mount()，不再是 new App()
mount(App, { target: document.getElementById('app')! });
