<script lang="ts">
  /**
   * 退出前清理面板。
   *
   * 规则由用户定：默认全部不勾选 = 全部删除；勾选的项目保留。这里只负责收集
   * 勾选结果，真正删文件的是主进程（渲染进程没有文件系统权限）。
   */
  import Icon from './Icon.svelte';
  import { formatBytes } from '../lib/time';

  type CleanupFile = {
    path: string;
    name: string;
    kind: 'fragment' | 'proxy';
    size: number;
    mtime: number;
  };

  let {
    files,
    busy,
    onconfirm,
    oncancel,
  }: {
    files: CleanupFile[];
    busy: boolean;
    onconfirm: (keep: string[]) => void;
    oncancel: () => void;
  } = $props();

  let keep = $state<Record<string, boolean>>({});
  const selected = $derived(files.filter((f) => keep[f.path]).length);
  const fragments = $derived(files.filter((f) => f.kind === 'fragment'));
  const proxies = $derived(files.filter((f) => f.kind === 'proxy'));
  const totalBytes = $derived(files.reduce((n, f) => n + (f.size || 0), 0));
  const deleting = $derived(files.length - selected);

  function toggle(path: string, checked: boolean) {
    keep = { ...keep, [path]: checked };
  }

  function setAll(value: boolean) {
    const next: Record<string, boolean> = {};
    for (const file of files) next[file.path] = value;
    keep = next;
  }

  function confirm() {
    onconfirm(files.filter((f) => keep[f.path]).map((f) => f.path));
  }
</script>

<div class="quit-overlay">
  <div class="quit-card">
    <div class="head">
      <div class="title">
        <Icon name="warn" size={15} />
        <b>退出前清理临时文件</b>
      </div>
      <span class="total">{files.length} 个 · {formatBytes(totalBytes)}</span>
    </div>

    <p class="desc">
      这些是输出目录里「转写选区」产生的碎片字幕与 480p 视频代理。
      <b>勾选的要保留，未勾选的会在退出时删除。</b>
      视频代理删除后，下次导入同一片源需要重新压制。
    </p>

    <div class="tools">
      <button class="btn tiny" onclick={() => setAll(true)} disabled={busy}>全选</button>
      <button class="btn tiny" onclick={() => setAll(false)} disabled={busy}>全不选</button>
      <span class="count">{selected} 个保留 · {deleting} 个删除</span>
    </div>

    <div class="list">
      {#if fragments.length}
        <div class="group">选区字幕 · {fragments.length}</div>
        {#each fragments as file (file.path)}
          <label class="item">
            <input
              type="checkbox"
              checked={!!keep[file.path]}
              onchange={(e) => toggle(file.path, (e.currentTarget as HTMLInputElement).checked)}
              disabled={busy}
            />
            <span class="name" title={file.path}>{file.name}</span>
            <span class="size">{formatBytes(file.size)}</span>
          </label>
        {/each}
      {/if}

      {#if proxies.length}
        <div class="group">视频代理 · {proxies.length}</div>
        {#each proxies as file (file.path)}
          <label class="item">
            <input
              type="checkbox"
              checked={!!keep[file.path]}
              onchange={(e) => toggle(file.path, (e.currentTarget as HTMLInputElement).checked)}
              disabled={busy}
            />
            <span class="name" title={file.path}>{file.name}</span>
            <span class="size">{formatBytes(file.size)}</span>
          </label>
        {/each}
      {/if}
    </div>

    <div class="actions">
      <button class="btn" onclick={oncancel} disabled={busy}>取消（不退出）</button>
      <button class="btn danger-solid" onclick={confirm} disabled={busy}>
        {busy ? '正在清理…' : deleting ? `删除 ${deleting} 个并退出` : '保留全部并退出'}
      </button>
    </div>
  </div>
</div>

<style>
  .quit-overlay {
    position: fixed;
    inset: 0;
    z-index: 340;
    background: rgba(0, 0, 0, 0.32);
    backdrop-filter: blur(3px);
    display: grid;
    place-items: center;
    padding: 28px;
  }
  .quit-card {
    width: min(620px, 100%);
    max-height: min(76vh, 680px);
    display: flex;
    flex-direction: column;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 12px;
    box-shadow: var(--shadow-pop);
    padding: 18px 20px 16px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .title {
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--text);
  }
  .title b {
    font-size: 14px;
    font-weight: 600;
  }
  .title :global(svg) {
    color: #ff9f0a;
  }
  .total {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .desc {
    margin: 10px 0 12px;
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-2);
  }
  .desc b {
    color: var(--text);
    font-weight: 500;
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 6px;
    padding-bottom: 9px;
    border-bottom: 1px solid var(--separator-soft);
  }
  .count {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .list {
    flex: 1;
    min-height: 80px;
    overflow-y: auto;
    padding-top: 4px;
  }
  .group {
    position: sticky;
    top: 0;
    background: var(--bg-content);
    padding: 8px 2px 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
    letter-spacing: 0.02em;
    z-index: 1;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 5px 6px;
    border-radius: 4px;
    font-size: 12px;
    color: var(--text);
  }
  .item:hover {
    background: var(--row-hover);
  }
  .item input {
    flex: 0 0 auto;
    margin: 0;
    accent-color: var(--accent);
  }
  .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    user-select: text;
  }
  .size {
    flex: 0 0 auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding-top: 13px;
    margin-top: 8px;
    border-top: 1px solid var(--separator-soft);
  }
  .actions .btn {
    height: 28px;
  }
  .danger-solid {
    background: #e5484d;
    color: #fff;
    font-weight: 500;
  }
  .danger-solid:hover:not(:disabled) {
    background: #d33d42;
  }
  .tiny {
    height: 20px;
    font-size: 12px;
    padding: 0 7px;
  }
</style>
