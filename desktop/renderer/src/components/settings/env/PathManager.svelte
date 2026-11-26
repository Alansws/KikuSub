<script lang="ts">
  /**
   * 路径管理：明面只有交付物相关的 3 条（导出 / 成片 / 模型），其余 8 条内部路径默认折叠。
   *
   * 折叠不是"藏起来"——每一行仍然能打开；只是不再让 11 条绝对路径把首屏占满。
   * 3+8 的分组在 lib/settings/pathGroups.ts 里，测试会核对它覆盖后端全部键。
   */
  import Icon from '../../Icon.svelte';
  import { settings } from '../../../lib/store.svelte';
  import { diagnostics } from '../../../lib/settings/diagnostics.svelte';
  import {
    EDITABLE_PATHS,
    INTERNAL_PATHS,
    pathBadge,
    pathValue,
    videoExportDisplay,
    videoFollowsExport,
    type PathKey,
  } from '../../../lib/settings/pathGroups';
  import {
    changeExportDir,
    changeModelsDir,
    changeVideoExportDir,
    openPath,
    pathState,
    resetExportDir,
    resetVideoExportDir,
    reveal,
  } from '../../../lib/settings/paths.svelte';

  const paths = $derived(settings.data?.paths ?? diagnostics.data?.paths ?? null);
  const saved = $derived(settings.data?.settings ?? null);

  const editableValues = $derived<Record<string, string>>({
    export_dir: pathValue(paths, 'export_dir'),
    video_export_dir: videoExportDisplay(saved?.video_export_dir ?? '', pathValue(paths, 'video_export_dir')),
    models_dir: pathValue(paths, 'models_dir'),
  });

  function badgeOf(key: PathKey): string {
    if (key === 'export_dir' || key === 'video_export_dir') return pathBadge(saved, key);
    return '';
  }

  function isCustom(key: PathKey): boolean {
    if (key === 'export_dir') return Boolean(pathBadge(saved, 'export_dir') === '自定义');
    if (key === 'video_export_dir') return Boolean(pathBadge(saved, 'video_export_dir') === '自定义');
    return false;
  }

  function onChange(key: PathKey) {
    if (key === 'export_dir') void changeExportDir();
    else if (key === 'video_export_dir') void changeVideoExportDir();
    else if (key === 'models_dir') void changeModelsDir();
  }

  function onReset(key: PathKey) {
    if (key === 'export_dir') void resetExportDir();
    else if (key === 'video_export_dir') void resetVideoExportDir();
  }

  function openRow(key: PathKey) {
    if (key === 'video_export_dir') {
      const follow = videoFollowsExport(saved?.video_export_dir);
      openPath(follow ? pathValue(paths, 'export_dir') : pathValue(paths, 'video_export_dir'));
      return;
    }
    openPath(pathValue(paths, key));
  }

  function openInternal(key: PathKey) {
    const value = pathValue(paths, key);
    if (key === 'presets_path' || key === 'settings_path') reveal(value);
    else openPath(value);
  }

  const busy = $derived(pathState.changingExport || pathState.changingModels);
</script>

<div class="set-group">
  {#each EDITABLE_PATHS as row (row.key)}
    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">{row.label}</span>
        <span class="set-row-desc">{row.hint}</span>
      </div>
      <div class="set-row-ctl grow">
        <span class="set-path" title={editableValues[row.key]}>{editableValues[row.key] || '—'}</span>
        {#if badgeOf(row.key)}
          <span class="path-badge">{badgeOf(row.key)}</span>
        {/if}
        <button class="btn sm" onclick={() => onChange(row.key)} disabled={busy}>
          {busy ? '处理中…' : '更改'}
        </button>
        {#if isCustom(row.key)}
          <button class="btn sm ghost" onclick={() => onReset(row.key)} disabled={busy}>恢复默认</button>
        {/if}
        <button
          class="btn sm ghost"
          onclick={() => openRow(row.key)}
          disabled={!editableValues[row.key] || editableValues[row.key] === '跟随导出文件夹'}
        >
          打开
        </button>
      </div>
    </div>
  {/each}
</div>

<details class="paths-more">
  <summary>
    <span class="more-chev"><Icon name="chevron-down" size={11} /></span>
    其余 {INTERNAL_PATHS.length} 个内部路径
  </summary>
  <div class="set-group">
    {#each INTERNAL_PATHS as row (row.key)}
      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">{row.label}</span>
          <span class="set-row-desc">{row.hint}</span>
        </div>
        <div class="set-row-ctl grow">
          <span class="set-path" title={pathValue(paths, row.key)}>{pathValue(paths, row.key) || '—'}</span>
          <button class="btn sm ghost" onclick={() => openInternal(row.key)} disabled={!pathValue(paths, row.key)}>
            {row.key === 'presets_path' || row.key === 'settings_path' ? '显示' : '打开'}
          </button>
        </div>
      </div>
    {/each}
  </div>
</details>

<style>
  .paths-more {
    margin-top: var(--sp-2);
  }
  .paths-more > summary {
    list-style: none;
    cursor: default;
    display: flex;
    align-items: center;
    gap: 6px;
    height: var(--ctl-h);
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    font-size: var(--fs-label);
    color: var(--text-2);
  }
  .paths-more > summary::-webkit-details-marker {
    display: none;
  }
  .paths-more > summary:hover {
    background: var(--fill);
    color: var(--text);
  }
  .more-chev {
    display: grid;
    place-items: center;
    transition: transform var(--dur) var(--ease);
  }
  .paths-more[open] .more-chev {
    transform: rotate(180deg);
  }
  .paths-more .set-group {
    margin-top: 6px;
  }
  .path-badge {
    display: inline-flex;
    align-items: center;
    height: 20px;
    padding: 0 6px;
    border-radius: var(--rad-control);
    background: var(--fill);
    color: var(--text-3);
    font-size: 11px;
    white-space: nowrap;
  }
</style>
