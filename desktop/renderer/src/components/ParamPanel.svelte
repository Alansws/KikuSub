<script lang="ts">
  import Icon from './Icon.svelte';
  import { resetParams, setParam, tuning } from '../lib/store.svelte';
  import type { ParamSpec } from '../lib/api';

  let { engine }: { engine: string } = $props();

  const entry = $derived(tuning.schema?.find((e) => e.key === engine) ?? null);
  const values = $derived(tuning.values[engine] ?? {});

  /**
   * 当前引擎的「兄弟枚举」值（现在是 VAD 切分器）。参数规格表可以声明
   * `backend_only` / `backend_notes` / `backend_recommended`，都按这个值生效；
   * 前端不另写一份「哪些参数只对 Silero 生效」。
   */
  const backendValue = $derived.by(() => {
    const all = (entry?.groups ?? []).flatMap((group) => group.params ?? []);
    const spec = all.find((item) => item.key === `${engine}.vad_backend`);
    if (!spec) return '';
    return String(values[spec.key] ?? spec.default ?? '');
  });

  function isScopedOut(spec: ParamSpec): boolean {
    return Boolean(spec.backend_only) && backendValue !== spec.backend_only;
  }

  function scopeLabel(spec: ParamSpec): string {
    const raw = String(spec.backend_only ?? '');
    return raw === 'silero' ? 'Silero' : raw;
  }

  function noteFor(spec: ParamSpec): string {
    return String(spec.backend_notes?.[backendValue] ?? '');
  }

  function recommendedFor(spec: ParamSpec): number | null {
    const value = spec.backend_recommended?.[backendValue];
    return typeof value === 'number' ? value : null;
  }

  function display(spec: ParamSpec, value: number | boolean | string): string {
    if (spec.kind === 'bool') return value ? '开' : '关';
    if (spec.kind === 'enum') {
      const key = String(value);
      return spec.choice_labels?.[key] ?? key;
    }
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
            {@const scopedOut = isScopedOut(spec)}
            {#if spec.kind === 'enum'}
              <label
                class="select-row"
                class:scoped-out={scopedOut}
                title={scopedOut
                  ? `${spec.help}（当前切分器下不生效）`
                  : spec.help}
              >
                <span class="label">{spec.label}</span>
                <select
                  class="choice"
                  value={String(value)}
                  onchange={(e) => setParam(engine, spec.key, e.currentTarget.value)}
                >
                  {#each spec.choices ?? [] as choice (choice)}
                    <option value={choice}>{spec.choice_labels?.[choice] ?? choice}</option>
                  {/each}
                </select>
              </label>
            {:else if spec.kind === 'bool'}
              <label class="switch-row" class:scoped-out={scopedOut} title={spec.help}>
                <span class="label">
                  {spec.label}
                  {#if scopedOut}<em class="scope-tag">仅 {scopeLabel(spec)} 生效</em>{/if}
                </span>
                <button
                  class="switch"
                  class:on={Boolean(value)}
                  role="switch"
                  aria-checked={Boolean(value)}
                  disabled={scopedOut}
                  onclick={() => setParam(engine, spec.key, !value)}
                >
                  <span class="knob"></span>
                </button>
              </label>
            {:else}
              {@const recommended = recommendedFor(spec)}
              {@const note = noteFor(spec)}
              <div
                class="slider-row"
                class:scoped-out={scopedOut}
                title={scopedOut
                  ? `${spec.help}（当前切分器下不生效）`
                  : spec.help}
              >
                <div class="slider-head">
                  <span class="label">
                    {spec.label}
                    {#if scopedOut}<em class="scope-tag">仅 {scopeLabel(spec)} 生效</em>{/if}
                  </span>
                  <span class="value">{display(spec, value)}</span>
                </div>
                <input
                  type="range"
                  min={spec.min ?? 0}
                  max={spec.max ?? 1}
                  step={spec.step ?? 0.01}
                  value={Number(value)}
                  disabled={scopedOut}
                  oninput={(e) =>
                    setParam(engine, spec.key, Number(e.currentTarget.value))}
                />
                {#if note}
                  <div class="calib">
                    <span>{note}</span>
                    {#if recommended !== null && Math.abs(Number(value) - recommended) >= 0.001}
                      <button
                        class="btn tiny ghost"
                        title={`把 ${spec.label} 设为 ${recommended}（当前切分器的标定推荐值）`}
                        onclick={() => setParam(engine, spec.key, recommended)}
                      >
                        采用
                      </button>
                    {:else}
                      <span class="calib-ok">已是推荐值</span>
                    {/if}
                  </div>
                {/if}
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
    /* 右栏被左栏挤窄时（1180 窗口 ≈ 370px），两列会把切分器下拉压到只剩
       「WhisperSeg（推荐」；按容器宽度退回单列，选择器永远完整可读。 */
    container-type: inline-size;
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
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-2) 18px;
  }

  /* 抽屉拉满时 1040px 宽，三列能把 18 个参数压到 8 行、不再需要额外滚动；
     窗口变窄时退回两列 / 单列，选择器与滑块始终完整可读。 */
  @container (max-width: 900px) {
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  /* 放在 .grid 之后：容器查询不提升优先级，写前面会被上面的列定义盖掉。 */
  @container (max-width: 620px) {
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .select-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    height: 26px;
    padding: 0 2px;
    min-width: 0;
  }
  /* 「WhisperSeg（推荐）」约 130px：卡片右栏单格 ~360px，给 200px 上限既放得下
     又不挤压左侧标签；旧值 110px 会把文案截成「WhisperSeg (:」。 */
  .select-row select {
    font: inherit;
    font-size: 12px;
    color: var(--text);
    background: var(--fill-strong);
    border: 0;
    border-radius: 5px;
    padding: 3px 6px;
    flex: 0 1 auto;
    min-width: 128px;
    max-width: 200px;
    width: 200px;
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
    min-width: 0;
  }

  .scope-tag {
    font-style: normal;
    font-size: 10.5px;
    color: var(--text-3);
    margin-left: var(--sp-1);
  }
  .scoped-out .label {
    color: var(--text-3);
  }
  .scoped-out .value {
    color: var(--text-3);
  }
  .scoped-out select,
  .scoped-out input,
  .scoped-out .switch {
    opacity: 0.45;
  }
  .scoped-out input {
    pointer-events: none;
  }

  .calib {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: wrap;
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-3);
    margin-top: 1px;
    text-wrap: pretty;
  }
  .calib-ok {
    color: var(--success);
  }
  .calib .btn.tiny {
    height: 18px;
    padding: 0 6px;
    font-size: 11px;
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
    min-width: 0;
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
  /* 滑块底槽是**下沉暗槽**（--well），不是一层 9% 白的提亮：
     暗色里往白里提会读成「浮起来的一条杠」，与 FCP 的凹槽正好相反。 */
  input[type='range']::-webkit-slider-runnable-track {
    height: 3px;
    border-radius: 2px;
    background: var(--well);
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
    background: var(--well-hover);
  }
  input[type='range']:active::-webkit-slider-thumb {
    background: var(--accent);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
  }
  input[type='range']:disabled::-webkit-slider-thumb {
    background: var(--text-3);
  }

  .empty {
    color: var(--text-3);
    font-size: 12px;
  }
</style>
