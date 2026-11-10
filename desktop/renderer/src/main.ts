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
if (savedTheme === 'dark' || savedTheme === 'light') {
  document.documentElement.dataset.theme = savedTheme;
  window.kikusub?.setTheme?.(savedTheme);
}

// Svelte 5 用 mount()，不再是 new App()
mount(App, { target: document.getElementById('app')! });
