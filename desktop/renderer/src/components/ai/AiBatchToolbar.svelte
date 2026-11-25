<script lang="ts">
  /**
   * 「翻译 / 润色 / 断句重排」共用的顶部工作条。
   *
   * 只保留两行 + 一条**可选**的紧凑分段轨（长片 / 局部范围才会出现）：
   *
   *   第 1 行「处理什么」：标题 + 页内模式（做法 / 底稿来源 / 语种）+ 模板 + 处理范围 + 右侧状态；
   *   第 2 行「怎么跑」：执行通道二选一（自动 API / 外部手动）+ 该通道的动作链 + 本次批次。
   *
   * 为什么不是「通道 A 一组按钮 + 通道 B 一组按钮」并排：那会同时亮着两个入口，
   * 用户分不清哪个才是这次要用的。通道是一选一的分段开关，切换后只显示那一条链。
   *
   * 范围 / 批次 / 模板的下拉框都复用既有组件，状态仍由调用方持有（润色 / 翻译在
   * `aiWorkspace`，断句重排在 `reshape`），这个组件只排版与派发事件。
   */
  import type { Snippet } from 'svelte';
  import Icon from '../Icon.svelte';
  import ClipScopePicker from '../ClipScopePicker.svelte';
  import BatchRangeBar from './BatchRangeBar.svelte';
  import TemplatePicker from './TemplatePicker.svelte';
  import type { AiChannel } from '../../lib/aiWorkspace.svelte';

  /** 与 `BatchRangeBar` 同名的字段；调用方按自己的状态模块填。 */
  interface BatchConfig {
    from: number;
    to: number;
    spanFrom: number;
    spanTo: number;
    count: number;
    total: number;
    size: number;
    manual: boolean;
    disabled: boolean;
    onApply: (from: number, to: number) => void;
    onStep: (direction: 1 | -1) => void;
    onSize: (size: number) => void;
    onReset: () => void;
  }

  interface TemplateConfig {
    items: { id: string; name: string }[];
    value: string;
    title?: string;
    onchange: (id: string) => void;
  }

  let {
    title,
    channel = 'manual',
    channels = ['api', 'manual'],
    apiAvailable = true,
    apiNote = '本机 API 暂不可用',
    onChannel,
    templates = null,
    rangeVisible = true,
    actionsVisible = true,
    busy = false,
    batch = null,
    progress = null,
    modeConfig,
    laneApi,
    laneManual,
    statusExtra,
    railExtra,
    note,
  }: {
    title: string;
    /** 当前通道；由调用方持有，切换时通过 `onChannel` 回写。 */
    channel?: AiChannel;
    /** 这个页面真正可用的通道。断句重排只有外部手动。 */
    channels?: AiChannel[];
    apiAvailable?: boolean;
    /** 「自动 API」不可用时，分段开关与行内的说明。 */
    apiNote?: string;
    onChannel?: (next: AiChannel) => void;
    templates?: TemplateConfig | null;
    rangeVisible?: boolean;
    /** 空态时把动作链收进中心引导卡，避免同一动作出现两遍。 */
    actionsVisible?: boolean;
    busy?: boolean;
    batch?: BatchConfig | null;
    /** 0–100；非 null 时在头下补一条 2px 进度线（不另占一行）。 */
    progress?: number | null;
    /** 第 1 行里的页内模式（断句重排的做法 / 翻译的语种）。 */
    modeConfig?: Snippet;
    /** 自动 API 通道的动作链。 */
    laneApi?: Snippet;
    /** 外部手动通道的动作链。 */
    laneManual?: Snippet;
    /** 第 1 行右侧：提案来源、计数、更多操作。 */
    statusExtra?: Snippet;
    /** 可选的分段轨（只在多段 / 需要时渲染）。 */
    railExtra?: Snippet;
    /**
     * 标题下一行的一句话（Step 4.3）：写清「这一页动不动时间轴」并给同组下一页的入口。
     * 锁轴 / 重排 / 翻译三页共用，位置固定在标题与命令条之间，切页时不跳。
     */
    note?: Snippet;
  } = $props();
</script>

<header class="aiw-head">
  <div class="aiw-title-row">
    <h1 class="aiw-title">{title}</h1>
    {@render modeConfig?.()}
    {#if templates && templates.items.length}
      <TemplatePicker
        items={templates.items}
        value={templates.value}
        title={templates.title ?? '提示词模板'}
        onchange={templates.onchange}
      />
    {/if}
    {#if rangeVisible}
      <ClipScopePicker compact label="处理范围" disabled={busy} />
    {/if}
    <div class="aiw-spacer"></div>
    {@render statusExtra?.()}
  </div>

  {#if note}
    <div class="aiw-note">{@render note()}</div>
  {/if}

  <div class="aiw-cmd-row">
    <div class="aiw-lane" role="group" aria-label="执行通道">
      {#if channels.includes('api')}
        <button
          aria-pressed={channel === 'api'}
          class:on={channel === 'api'}
          disabled={!apiAvailable}
          title={apiAvailable
            ? '在本机调用已配置的模型生成建议（不修改字幕）'
            : apiNote}
          onclick={() => onChannel?.('api')}
        >
          <Icon name="sparkle" size={11} />自动 API
        </button>
      {/if}
      {#if channels.includes('manual')}
        <button
          aria-pressed={channel === 'manual'}
          class:on={channel === 'manual'}
          title="复制提示词到网页版 / 任意聊天模型，再把回复粘回来"
          onclick={() => onChannel?.('manual')}
        >
          <Icon name="paste" size={11} />外部手动
        </button>
      {/if}
    </div>

    {#if actionsVisible}
      <div class="aiw-lane-actions">
        {#if channel === 'api'}{@render laneApi?.()}{:else}{@render laneManual?.()}{/if}
      </div>
    {/if}

    <div class="aiw-spacer"></div>

    {#if batch}
      <div class="aiw-batch">
        <BatchRangeBar {...batch} />
      </div>
    {/if}
  </div>

  {#if progress !== null}
    <div class="aiw-progress" aria-hidden="true"><i style={`width:${progress}%`}></i></div>
  {/if}

  {@render railExtra?.()}
</header>
