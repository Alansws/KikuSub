<script lang="ts">
  /**
   * 「90/10 减法」的 10：把 15 个 VAD / 静音 / 留白 / n-gram 滑块与预设管理
   * 整体收进一个默认收起的抽屉（2026-11-21 Step 4）。
   *
   * 关键约束：这不是删功能，只是换默认可见层级。参数绑定、预设按引擎过滤、
   * 保存 / 载入 / 删除与跨引擎校验仍然走 `lib/store.svelte.ts` 里原来的那几个
   * 函数；组件只负责把这一整块从主区搬进二级抽屉。
   */
  import Icon from '../Icon.svelte';
  import ParamPanel from '../ParamPanel.svelte';
  import {
    applyPreset,
    deletePreset,
    savePresetAs,
    tuning,
  } from '../../lib/store.svelte';

  let { engine }: { engine: string } = $props();

  let open = $state(false);
  let picked = $state('');
  let presetName = $state('');

  /** 只列与当前引擎绑定的预设；跨引擎载入由服务端 409 兜底，前端二次校验。 */
  const presetsForEngine = $derived(tuning.presets.filter((p) => p.engine === engine));
  /** 当前引擎自己的「已载入预设」；切引擎后不能把上一个引擎的预设当成可删对象。 */
  const deletablePreset = $derived(
    picked || (tuning.activePresetEngine === engine ? tuning.activePreset : ''),
  );
  const paramCount = $derived.by(() => {
    const entry = tuning.schema?.find((item) => item.key === engine);
    return (entry?.groups ?? []).reduce((sum, group) => sum + (group.params?.length ?? 0), 0);
  });
  /**
   * 与默认值不同的参数项数。用户最常踩的坑是「上一轮调过阈值、下一轮忘了」，
   * 折叠态直接把「已改 N 项」露在标题上，不用展开也知道当前引擎不是默认参数。
   */
  const changedCount = $derived.by(() => {
    const entry = tuning.schema?.find((item) => item.key === engine);
    const current = tuning.values[engine] ?? {};
    if (!entry?.defaults) return 0;
    return Object.entries(current).filter(([key, value]) => entry.defaults[key] !== value).length;
  });

  // 换引擎时清掉上一套引擎的选中项；参数面板本身按引擎分开存，不互相污染。
  // 用普通变量而不是 $state：它只记录「上一次看到的引擎」，不参与渲染。
  let lastPresetEngine = '';
  $effect(() => {
    const current = engine;
    if (!lastPresetEngine) {
      lastPresetEngine = current;
      return;
    }
    if (lastPresetEngine === current) return;
    lastPresetEngine = current;
    picked = '';
    if (tuning.activePresetEngine && tuning.activePresetEngine !== current) {
      tuning.activePreset = '';
      tuning.activePresetEngine = '';
    }
  });

  async function onPick(name: string) {
    picked = name;
    if (!name) return;
    const ok = await applyPreset(name, engine);
    if (!ok) picked = '';
  }

  async function onSave() {
    await savePresetAs(presetName || picked, engine);
    presetName = '';
  }

  async function onDelete() {
    const target = deletablePreset;
    if (!target) return;
    await deletePreset(target);
    picked = '';
  }
</script>

<section class="expert" class:open>
  <button
    type="button"
    class="expert-head"
    aria-expanded={open}
    aria-controls="expert-params-body"
    onclick={() => (open = !open)}
  >
    <span class="expert-title">
      <Icon name="gear" size={13} />
      <span>专家参数与预设</span>
      <span class="expert-sub">VAD / 分句阈值</span>
    </span>
    <span class="expert-meta">
      {#if deletablePreset}
        当前预设：{deletablePreset}{#if changedCount} · 已改 {changedCount} 项{/if}
      {:else if open}
        收合
      {:else}
        {paramCount ? `${paramCount} 项参数` : '按需调整'}{#if changedCount} · 已改 {changedCount} 项{/if} · 展开
      {/if}
      <span class="chev" class:open aria-hidden="true">
        <Icon name="chevron-right" size={11} />
      </span>
    </span>
  </button>

  {#if open}
    <div class="expert-body" id="expert-params-body">
      <div class="preset-bar">
        <span class="pb-label">预设</span>
        <select
          value={picked}
          title="只显示与当前识别引擎绑定的预设"
          aria-label="按当前引擎载入预设"
          onchange={(e) => onPick(e.currentTarget.value)}
        >
          <option value="">（未选择）</option>
          {#each presetsForEngine as p (p.name)}
            <option value={p.name}>{p.name}</option>
          {/each}
        </select>
        <div class="field preset-name">
          <input
            bind:value={presetName}
            placeholder="存为新预设…"
            aria-label="新预设名称"
            onkeydown={(e) => {
              if (e.key === 'Enter') onSave();
            }}
          />
        </div>
        <button class="btn" type="button" onclick={onSave} disabled={!presetName.trim() && !picked}>
          <Icon name="check" size={11} />保存
        </button>
        <button
          class="btn ghost"
          type="button"
          onclick={onDelete}
          disabled={!deletablePreset}
          title="删除当前引擎的已选预设"
        >
          <Icon name="trash" size={11} />
        </button>
      </div>
      <p class="preset-hint">
        预设保存的是当前引擎的完整参数快照；只列出本引擎的预设，跨引擎载入会被服务端拒绝。
      </p>

      <ParamPanel {engine} />
    </div>
  {/if}
</section>

<style>
  .expert {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    background: var(--bg-content);
    min-width: 0;
    overflow: hidden;
  }
  .expert.open {
    border-color: var(--separator);
  }

  .expert-head {
    appearance: none;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: 11px var(--sp-4);
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: default;
    min-width: 0;
  }
  .expert-head:hover {
    background: var(--fill);
  }
  .expert.open .expert-head {
    border-bottom: 1px solid var(--separator-soft);
    background: var(--fill);
  }

  .expert-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-2);
  }
  .expert-sub {
    font-weight: 400;
    font-size: 11px;
    color: var(--text-3);
  }
  .expert-meta {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
    max-width: 55%;
    font-size: 11px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chev {
    display: grid;
    place-items: center;
    color: var(--text-3);
    transition: transform 160ms var(--ease);
  }
  .chev.open {
    transform: rotate(90deg);
    color: var(--accent);
  }

  .expert-body {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4) var(--sp-4);
    min-width: 0;
  }

  .preset-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .pb-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
  }
  .preset-bar select {
    appearance: none;
    height: 26px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background-color: var(--bg-content);
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    padding: 0 22px 0 var(--sp-2);
    max-width: 240px;
    min-width: 150px;
    background-image: linear-gradient(45deg, transparent 50%, var(--text-3) 50%),
      linear-gradient(135deg, var(--text-3) 50%, transparent 50%);
    background-position: calc(100% - 12px) 11px, calc(100% - 8px) 11px;
    background-size: 4px 4px, 4px 4px;
    background-repeat: no-repeat;
  }
  .preset-name {
    width: 160px;
    flex: 0 1 160px;
  }
  .preset-hint {
    margin: 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
  }
</style>
