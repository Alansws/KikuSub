<script lang="ts">
  /**
   * 清理标点浮层（核对台顶栏）。
   *
   * 形态取舍：不做模态确认框。这个应用里只有快捷键面板和退出确认是模态的，一个
   * 批量小操作每次弹窗会让熟练用户烦；但整表改写又需要「看得见影响范围」。所以
   * 走「按钮 → 同款下拉浮层（带统计与三条前后对比）→ 主按钮」，与「⋯ 更多」菜单
   * 同一套手感，比纯模态轻、比即点即改稳。
   *
   * 规则与提交都在 lib 里，这个组件只负责画和键盘；`app.cues` 一变（应用、⌘Z、
   * 历史跳转）统计与预览会自动跟着重算。
   */
  import Icon from './Icon.svelte';
  import {
    applyPunctClean,
    closePunctPanel,
    currentPunctPlan,
    punctPanel,
    setPunctSpace,
    togglePunctEllipsis,
  } from '../lib/punctuationPanel.svelte';
  import { app } from '../lib/store.svelte';

  /** 会被删掉 / 换掉的那些字符（预览里加删除线）。半角 `...` 也拆成点显示。 */
  const OLD_MARKS = '、，。．,…';
  const PREVIEW_LINES = 3;

  let panelEl: HTMLDivElement | undefined = $state();

  const plan = $derived(currentPunctPlan());
  const count = $derived(plan.changed.length);
  const preview = $derived(
    plan.changed.slice(0, PREVIEW_LINES).map((index) => ({
      index,
      before: app.cues[index]?.text ?? '',
      after: plan.texts[index] ?? '',
    })),
  );

  /** 把一行文本切成「普通 / 命中」的片段，供 `{#each}` 上色。 */
  function segments(text: string, hit: (ch: string) => boolean) {
    const out: { text: string; hit: boolean }[] = [];
    for (const ch of text) {
      const isHit = hit(ch);
      const last = out[out.length - 1];
      if (last && last.hit === isHit) last.text += ch;
      else out.push({ text: ch, hit: isHit });
    }
    return out;
  }

  /**
   * 「原文」行：只给**这次真要删掉**的字符上色。
   * 省略号默认是保留的，若按固定字符集染色会误标成「要删」（`。…` 里的 `。` 删、`…` 留），
   * 所以这里先把省略号整体跳过去。开关打开时才把它算作要删。
   */
  function oldSegments(text: string) {
    const out: { text: string; hit: boolean }[] = [];
    const push = (chunk: string, hit: boolean) => {
      const last = out[out.length - 1];
      if (last && last.hit === hit) last.text += chunk;
      else out.push({ text: chunk, hit });
    };
    let i = 0;
    while (i < text.length) {
      if (!punctPanel.stripEllipsis) {
        const rest = text.slice(i);
        const ell = /^(?:…+|⋯+|‥+|\.{3,})/.exec(rest);
        if (ell) {
          push(ell[0], false);
          i += ell[0].length;
          continue;
        }
      }
      push(text[i], OLD_MARKS.includes(text[i]));
      i += 1;
    }
    return out;
  }
  const newSegments = (text: string) => segments(text, (ch) => ch === ' ' || ch === '\u3000');

  // 浮层打开期间：点空白处关闭、Esc 关闭、Enter 直接应用（不落到「删除当前字幕」上）。
  // 用捕获阶段拦住，否则 App 的全局 Enter = 删除当前句会抢先跑掉。
  $effect(() => {
    if (!punctPanel.open) return;

    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (panelEl?.contains(target)) return;
      // 触发器自己会 toggle，别在这里先关一次再被它打开
      if (target.closest('[data-punct-trigger]')) return;
      closePunctPanel();
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        closePunctPanel();
        return;
      }
      if (e.key !== 'Enter' || e.metaKey || e.ctrlKey || e.altKey) return;
      // 焦点在浮层里就交给按钮 / 复选框自己处理
      const target = e.target as HTMLElement | null;
      if (target && panelEl?.contains(target)) return;
      e.preventDefault();
      e.stopPropagation();
      void applyPunctClean();
    };

    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    };
  });
</script>

{#if punctPanel.open}
  <div class="punct-panel" role="dialog" aria-label="清理标点" bind:this={panelEl}>
    <div class="pp-head">
      <span>清理标点</span>
      <button class="pp-x" onclick={closePunctPanel} title="关闭（Esc）" aria-label="关闭">
        <Icon name="close" size={10} />
      </button>
    </div>

    <div class="pp-row">
      <span class="pp-label">句中</span>
      <div class="pp-seg" role="group" aria-label="句中空格宽度">
        <button
          class:on={punctPanel.space === 'half'}
          aria-pressed={punctPanel.space === 'half'}
          onclick={() => setPunctSpace('half')}
        >
          半角空格
        </button>
        <button
          class:on={punctPanel.space === 'full'}
          aria-pressed={punctPanel.space === 'full'}
          onclick={() => setPunctSpace('full')}
        >
          全角空格
        </button>
      </div>
    </div>

    <label class="pp-check">
      <input type="checkbox" checked={punctPanel.stripEllipsis} onchange={togglePunctEllipsis} />
      连 … / ... 一并清掉
    </label>

    <div class="pp-stat">
      <span><b>{count}</b> 条 / {app.cues.length} 条会改</span>
      <span class="pp-sub">行尾 {plan.endMarks} 处 · 句中 {plan.midMarks} 处</span>
    </div>

    {#if count}
      <div class="pp-preview">
        {#each preview as item (item.index)}
          <div class="pp-line">
            <div class="pp-old">
              {#each oldSegments(item.before) as seg}<span class:del={seg.hit}>{seg.text}</span>{/each}
            </div>
            <div class="pp-new">
              {#each newSegments(item.after) as seg}<span class:sp={seg.hit}>{seg.text}</span>{/each}
            </div>
          </div>
        {/each}
        {#if count > preview.length}
          <div class="pp-more">…另 {count - preview.length} 条</div>
        {/if}
        {#if plan.skipped.length}
          <div class="pp-more">{plan.skipped.length} 条只有标点，已跳过</div>
        {/if}
      </div>
    {:else}
      <div class="pp-empty">这一轨没有需要清理的标点</div>
    {/if}

    <div class="pp-foot">
      <span class="pp-hint">⌘Z 可一步撤回</span>
      <button class="btn tiny" onclick={closePunctPanel}>取消</button>
      <button
        class="btn tiny primary"
        disabled={!count || punctPanel.busy}
        onclick={() => void applyPunctClean()}
      >
        {punctPanel.busy ? '清理中…' : `清理 ${count} 条`}
      </button>
    </div>
  </div>
{/if}

<style>
  .punct-panel {
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 340px;
    max-height: min(560px, calc(100vh - 90px));
    overflow-y: auto;
    padding: var(--sp-3);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: var(--shadow-pop);
    -webkit-app-region: no-drag;
    animation: ppIn 140ms var(--ease);
  }
  @keyframes ppIn {
    from {
      opacity: 0;
      transform: translateY(-3px);
    }
  }
  .pp-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 12px;
    font-weight: 500;
    color: var(--text);
  }
  .pp-x {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    border-radius: 4px;
    cursor: default;
  }
  .pp-x:hover {
    background: var(--fill);
    color: var(--text);
  }
  .pp-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .pp-label {
    font-size: 12px;
    color: var(--text-2);
    flex: 0 0 auto;
  }
  .pp-seg {
    display: flex;
    flex: 1;
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    overflow: hidden;
  }
  .pp-seg button {
    appearance: none;
    flex: 1;
    height: 24px;
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 12px;
    cursor: default;
  }
  .pp-seg button + button {
    border-left: 1px solid var(--line);
  }
  .pp-seg button.on {
    background: var(--control-on);
    color: var(--on-accent);
  }
  .pp-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-2);
    cursor: default;
  }
  .pp-check input {
    margin: 0;
    accent-color: var(--control-on);
  }
  .pp-stat {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 12px;
    color: var(--text-2);
    padding-top: var(--sp-1);
    border-top: 1px solid var(--line-2);
  }
  .pp-stat b {
    font-size: 14px;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .pp-sub {
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .pp-preview {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border-radius: 6px;
    background: var(--fill);
  }
  .pp-line {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  /* 字幕文本按全角排：预览用字幕字体，空格的位置才看得出来 */
  .pp-old,
  .pp-new {
    font-family: var(--font-cue);
    font-size: 13px;
    line-height: 18px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .pp-old {
    color: var(--text-3);
  }
  .pp-new {
    color: var(--text);
  }
  /* 要删掉的标点：染色 + 浅底。不加删除线——`、` `。` 这类全角标点本身就有斜笔，
     叠一条删除线会变成一坨看不懂的划痕。 */
  .del {
    color: var(--warn);
    background: var(--warn-soft);
    border-radius: 2px;
  }
  /* 换出来的那个空格：浅底标出来，否则一空格宽几乎看不见 */
  .sp {
    background: var(--accent-soft);
    border-radius: 2px;
  }
  .pp-new::before {
    content: '→';
    color: var(--text-3);
    margin-right: var(--sp-1);
  }
  .pp-more {
    font-size: 11px;
    color: var(--text-3);
  }
  .pp-empty {
    font-size: 12px;
    color: var(--text-3);
    padding: var(--sp-2) 0;
  }
  .pp-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: var(--sp-1);
    border-top: 1px solid var(--line-2);
  }
  .pp-hint {
    flex: 1;
    font-size: 11px;
    color: var(--text-3);
  }
  .tiny {
    height: 22px;
    font-size: 12px;
    padding: 0 7px;
    background: var(--raise);
  }
  .btn.primary.tiny {
    background: var(--btn-primary-bg);
    color: var(--on-accent);
  }
</style>
