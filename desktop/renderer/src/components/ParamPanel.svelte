<script lang="ts">
  import Icon from './Icon.svelte';
  import { resetParams, setParam, tuning } from '../lib/store.svelte';
  import type { ParamSpec } from '../lib/api';

  let { engine }: { engine: string } = $props();

  const entry = $derived(tuning.schema?.find((e) => e.key === engine) ?? null);
  const values = $derived(tuning.values[engine] ?? {});

  function display(spec: ParamSpec, value: number | boolean): string {
    if (spec.kind === 'bool') return value ? '开' : '关';
    const num = Number(value);
    if (spec.step && spec.step < 0.1) return num.toFixed(2);
    if (spec.step && spec.step < 1) return num.toFixed(2);
    return String(Math.round(num));
  }
</script>

<div class="panel">
  <div class="head">
    <span title="调小更灵敏、更容易切碎；调大更稳健、更容易吞掉短音">可调参数</span>
    <button class="btn ghost small" onclick={() => resetParams(engine)}>
      <Icon name="undo" size={11} />恢复默认
    </button>
  </div>

  {#if !entry}
    <div class="empty">参数加载中…</div>
  {:else}
    {#each entry.groups as group (group.group)}
      <div class="group">
        <div class="group-title">{group.group}</div>
        <div class="grid">
          {#each group.params as spec (spec.key)}
            {@const value = values[spec.key] ?? spec.default}
            {#if spec.kind === 'bool'}
              <label class="switch-row" title={spec.help}>
                <span class="label">{spec.label}</span>
                <button
                  class="switch"
                  class:on={Boolean(value)}
                  role="switch"
                  aria-checked={Boolean(value)}
                  onclick={() => setParam(engine, spec.key, !value)}
                >
                  <span class="knob"></span>
                </button>
              </label>
            {:else}
              <div class="slider-row" title={spec.help}>
                <div class="slider-head">
                  <span class="label">{spec.label}</span>
                  <span class="value">{display(spec, value)}</span>
                </div>
                <input
                  type="range"
                  min={spec.min ?? 0}
                  max={spec.max ?? 1}
                  step={spec.step ?? 0.01}
                  value={Number(value)}
                  oninput={(e) =>
                    setParam(engine, spec.key, Number(e.currentTarget.value))}
                />
              </div>
            {/if}
          {/each}
        </div>
      </div>
    {/each}
  {/if}
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-height: 0;
    overflow-y: auto;
    padding-right: var(--sp-1);
  }

  .head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 12.5px;
    font-weight: 600;
  }
  .head .hint {
    font-weight: 400;
    font-size: 12px;
    color: var(--text-3);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .small {
    height: 22px;
    font-size: 12px;
    padding: 0 var(--sp-2);
  }

  .group-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
    margin-bottom: 6px;
    letter-spacing: 0.02em;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-2) 18px;
  }

  .switch-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    height: 26px;
    padding: 0 2px;
  }

  .label {
    font-size: 12.5px;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .switch {
    appearance: none;
    border: 0;
    width: 32px;
    height: 19px;
    border-radius: 8px;
    background: var(--fill-strong);
    padding: 2px;
    flex: 0 0 32px;
    transition: background var(--dur) var(--ease);
  }
  .switch.on {
    background: var(--control-on);
  }
  .switch .knob {
    display: block;
    width: 15px;
    height: 15px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    transition: transform var(--dur) var(--ease);
  }
  .switch.on .knob {
    transform: translateX(13px);
  }

  .slider-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 2px 2px 0;
  }
  .slider-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--sp-2);
  }
  .value {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  /* 轨道必须画在 runnable-track 上：只给 input 设背景的话，
     thumb 一撑高轨道就被盖住了（第一版就是这么翻车的）。 */
  input[type='range'] {
    appearance: none;
    width: 100%;
    height: 16px;
    background: transparent;
    outline: none;
    margin: 2px 0 0;
  }
  input[type='range']::-webkit-slider-runnable-track {
    height: 3px;
    border-radius: 2px;
    background: var(--fill-strong);
  }
  input[type='range']::-webkit-slider-thumb {
    appearance: none;
    width: 12px;
    height: 12px;
    margin-top: -4.5px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3), 0 0 0 0.5px rgba(0, 0, 0, 0.14);
    cursor: default;
  }
  input[type='range']:hover::-webkit-slider-runnable-track {
    background: var(--separator);
  }
  input[type='range']:active::-webkit-slider-thumb {
    background: var(--accent);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
  }

  .empty {
    color: var(--text-3);
    font-size: 12px;
  }
</style>
