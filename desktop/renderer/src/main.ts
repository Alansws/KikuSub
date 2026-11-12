import './error-capture';
import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';

/**
 * 在挂载前先把外观定下来。
 *
 * 以前主题要等 sidecar 握手完成（`boot()`）才写进 `<html data-theme>`，于是
 * 深色模式每次启动都会先闪一下浅色侧栏；同时主进程的原生 vibrancy 还停在
 * 系统外观，红绿灯那一列会透成灰白。这里同步应用一次，并通知主进程。
 */
const savedTheme = localStorage.getItem('kikusub.theme');
// 旧版本把「明朝墨」存成 'cool'：冷启动时先迁移，避免闪一下默认主题
const bootTheme = savedTheme === 'cool' ? 'mincho' : savedTheme;
if (bootTheme === 'dark' || bootTheme === 'light' || bootTheme === 'mincho') {
  document.documentElement.dataset.theme = bootTheme;
  window.kikusub?.setTheme?.(bootTheme);
}

// Svelte 5 用 mount()，不再是 new App()
mount(App, { target: document.getElementById('app')! });
