import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// 渲染进程通过 file:// 加载（Electron 打包后），所以 base 必须是相对的
export default defineConfig({
  root: 'renderer',
  base: './',
  plugins: [svelte()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'chrome132',
    assetsInlineLimit: 0,
  },
  server: { port: 5183, strictPort: true },
});
