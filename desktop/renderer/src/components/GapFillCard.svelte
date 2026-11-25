<script lang="ts">
  /**
   * 待译补译卡片（翻译页顶部；检查器的「补译 N 条」也跳到这个流程）。
   *
   * 它只做一件事：把「只补这几条」闭环——复制（只含待译）、粘回、只回填。
   * 所有判断都在 `lib/gapFill.svelte.ts` 与 `lib/gapBatch.ts`；这里只负责画。
   * 收起时是一条摘要（有译文轨且范围内有缺口才出现），展开后才占地方。
   */
  import Icon from './Icon.svelte';
  import { app, exporter } from '../lib/store.svelte';
  import {
    applyGapFill,
    closeGapFill,
    copyGapPrompt,
    gapCountsNow,
    gapFill,
    gapListNow,
    gapScopeLabel,
    openGapFill,
    parseGapReply,
    setGapIncludeStale,
    toggleGapAccepted,
    updateGapItem,
  } from '../lib/gapFill.svelte';

  const counts = $derived(gapCountsNow());
  const scopeLabel = $derived(gapScopeLabel());
  const hasTrack = $derived(Boolean(app.translations[app.trackLang]));
  const canShow = $derived(
    hasTrack && (gapFill.open || counts.pending + counts.stale > 0),
  );
  const wanted = $derived(gapListNow().length);
  const accepted = $derived(
    gapFill.items.filter((item) => item.accepted && item.after.trim()),
  );
  const untouched = $derived(Math.max(0, app.cues.length - accepted.length));
  const busy = $derived(Boolean(gapFill.stage));

  /**
   * 换了语种 / 处理范围 / 译文轨被删：上一批的条号与 `before` 已经不对应当前上下文，
   * 直接收起。留着它在界面上是「看着是这一章，点应用却写进上一章」的坑。
   */
  let seenContext = '';
  $effect(() => {
    const context = `${app.trackLang}|${exporter.clip.start}|${exporter.clip.end}|${exporter.clip.label}`;
    if (!seenContext) {
      seenContext = context;
      return;
    }
    if (context === seenContext) return;
    seenContext = context;
    if (gapFill.open) closeGapFill();
  });
</script>

{#if canShow}
  <section class="gap-card" class:open={gapFill.open} aria-label="补译待译">
    <div class="gap-head">
      <span class="gap-title">
        <Icon name="sparkle" size={12} />
        补译
      </span>
      <span class="gap-scope">{scopeLabel}</span>
      <span class="gap-stat">
        {#if counts.pending}<b class="todo">{counts.pending}</b> 条待译{/if}
        {#if counts.stale}
          {#if counts.pending}<span class="dot">·</span>{/if}
          <b class="warn">{counts.stale}</b> 条原文已改
        {/if}
        {#if !counts.pending && !counts.stale}<b class="ok">全部同步</b>{/if}
      </span>
      <span class="gap-meta">已译 {counts.translated} / {counts.total}</span>
      <div class="gap-actions">
        <button
          class="btn tiny primary"
          disabled={!wanted || busy}
          onclick={() => void copyGapPrompt()}
          title="只复制当前范围里还没有译文的条目；外部模型只翻这几条"
        >
          {gapFill.stage === 'copying' ? '准备中…' : `复制待译${wanted ? `（${wanted}）` : ''}`}
        </button>
        {#if gapFill.open}
          <button class="btn tiny" onclick={closeGapFill} title="收起补译卡片">收起</button>
        {:else}
          <button class="btn tiny" onclick={() => void openGapFill(false)}>展开</button>
        {/if}
      </div>
    </div>

    {#if gapFill.open}
      <div class="gap-body">
        <div class="gap-hint">
          复制出去的是按<b>全片条号</b>编号的这 {gapFill.indices.length || wanted} 条；回填时按条号落位，
          只写这些条目，其余 {counts.translated} 条已有译文原样保留。
        </div>

        <div class="gap-row">
          <label class="chk" class:off={!counts.stale}>
            <input
              type="checkbox"
              checked={gapFill.includeStale}
              disabled={!counts.stale}
              onchange={(e) => setGapIncludeStale(e.currentTarget.checked)}
            />
            同时补「原文已改」的 {counts.stale} 条（会覆盖这些条的现有译文）
          </label>
          <button class="link" onclick={() => void copyGapPrompt()} disabled={busy}>
            重新复制本批
          </button>
          <button
            class="link"
            onclick={() => (gapFill.pasteOpen = !gapFill.pasteOpen)}
            disabled={busy || !gapFill.indices.length}
            title={gapFill.indices.length ? '粘贴外部模型返回的 SRT' : '先点「复制待译」'}
          >
            {gapFill.pasteOpen ? '收起粘贴' : '粘贴补译…'}
          </button>
        </div>

        {#if gapFill.error}
          <div class="gap-note err"><Icon name="warn" size={11} /><span>{gapFill.error}</span></div>
        {/if}
        {#if gapFill.warnings.length}
          <div class="gap-note warn">
            <Icon name="warn" size={11} /><span>{gapFill.warnings.join('；')}</span>
          </div>
        {/if}

        {#if gapFill.pasteOpen}
          <div class="gap-paste">
            <textarea
              class="gap-box"
              bind:value={gapFill.pasteText}
              spellcheck="false"
              aria-label="粘贴外部模型返回的补译 SRT"
              placeholder={'2\n00:00:01,000 --> 00:00:02,000\n今天下雨了\n\n4\n…'}
            ></textarea>
            <div class="gap-paste-foot">
              <span class="gap-note-text">
                条数必须与复制出去的一致（{gapFill.indices.length} 条）；序号不同也能按顺序对位。
              </span>
              <button
                class="btn tiny primary"
                disabled={busy || !gapFill.pasteText.trim()}
                onclick={() => void parseGapReply()}
              >
                {gapFill.stage === 'parsing' ? '解析中…' : '解析并回填'}
              </button>
            </div>
          </div>
        {/if}

        {#if gapFill.items.length}
          <div class="gap-list" role="table" aria-label="补译条目">
            <div class="gap-list-head" role="row">
              <span></span>
              <span>条号</span>
              <span>原文（只读）</span>
              <span>新译文（可改）</span>
            </div>
            {#each gapFill.items as item (item.i)}
              <div class="gap-item" class:off={!item.accepted} role="row">
                <button
                  class="pin"
                  class:on={item.accepted}
                  aria-pressed={item.accepted}
                  aria-label={item.accepted ? '取消写入这一条' : '写入这一条'}
                  title={item.accepted ? '取消写入这一条' : '写入这一条'}
                  onclick={() => toggleGapAccepted(item.i)}
                >
                  <Icon name="check" size={10} />
                </button>
                <span class="gap-idx">#{item.i}</span>
                <span class="gap-before" title={item.before}>{item.before}</span>
                <input
                  class="gap-input"
                  value={item.after}
                  spellcheck="false"
                  oninput={(e) => updateGapItem(item.i, e.currentTarget.value)}
                />
              </div>
            {/each}
          </div>
          <div class="gap-apply">
            <span class="gap-note-text">
              将写入 <b>{accepted.length}</b> 条；其余 <b>{untouched}</b> 条（含本批未勾选的）
              一个字节都不动。⌘Z 一步撤回本批。
            </span>
            <button
              class="btn tiny primary"
              disabled={!accepted.length || busy}
              onclick={() => void applyGapFill()}
            >
              {gapFill.stage === 'applying' ? '应用中…' : `应用补译（${accepted.length} 条）`}
            </button>
          </div>
        {:else if !gapFill.pasteOpen}
          <div class="gap-empty">
            点「复制待译」把这几条拿去外部模型；回来点「粘贴补译…」把回复贴回来。
          </div>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  .gap-card {
    flex: 0 0 auto;
    border-bottom: 1px solid var(--separator);
    background: var(--bg-content);
    font-size: 12px;
    color: var(--text-2);
  }
  .gap-card.open {
    background: var(--fill);
  }
  .gap-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 6px 14px;
    min-width: 0;
  }
  .gap-title {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-weight: 500;
    color: var(--text);
    white-space: nowrap;
  }
  .gap-scope {
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 30%;
  }
  .gap-stat {
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .gap-stat b {
    font-weight: 600;
  }
  .todo {
    color: var(--accent);
  }
  .warn {
    color: var(--warn);
  }
  .ok {
    color: var(--text-3);
    font-weight: 400;
  }
  .dot {
    margin: 0 var(--sp-1);
    color: var(--text-3);
  }
  .gap-meta {
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .gap-actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .gap-body {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: 0 14px 10px;
    border-top: 1px solid var(--separator-soft);
  }
  .gap-hint,
  .gap-note-text {
    color: var(--text-2);
    line-height: 1.6;
  }
  .gap-hint b {
    color: var(--text);
    font-weight: 600;
  }
  .gap-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    cursor: default;
    user-select: none;
  }
  .chk.off {
    opacity: 0.45;
  }
  .link {
    appearance: none;
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--accent);
    font: inherit;
    cursor: default;
  }
  .link:disabled {
    color: var(--text-3);
  }
  .gap-note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: var(--sp-1) var(--sp-2);
    border-radius: 6px;
    line-height: 1.55;
  }
  .gap-note.err {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .gap-note.warn {
    background: var(--warn-soft);
    color: var(--warn);
  }
  .gap-paste {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .gap-box {
    width: 100%;
    min-height: 110px;
    max-height: 34vh;
    resize: vertical;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.5;
    padding: var(--sp-2) 10px;
    border-radius: var(--rad-card);
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
  }
  .gap-box:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .gap-paste-foot,
  .gap-apply {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .gap-paste-foot .gap-note-text,
  .gap-apply .gap-note-text {
    flex: 1;
    min-width: 0;
  }
  .gap-apply b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .gap-list {
    display: flex;
    flex-direction: column;
    max-height: 42vh;
    overflow: auto;
    border: 1px solid var(--separator);
    border-radius: 6px;
    background: var(--bg-content);
  }
  .gap-list-head,
  .gap-item {
    display: grid;
    grid-template-columns: 24px 54px minmax(0, 1fr) minmax(0, 1.2fr);
    gap: var(--sp-2);
    align-items: center;
    padding: var(--sp-1) var(--sp-2);
  }
  .gap-list-head {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--bg-inspector);
    color: var(--text-3);
    font-size: 11px;
    border-bottom: 1px solid var(--separator);
  }
  .gap-item {
    border-bottom: 1px solid var(--separator-soft);
  }
  .gap-item.off {
    opacity: 0.45;
  }
  .gap-idx {
    color: var(--text-3);
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }
  .gap-before {
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: var(--font-cue);
  }
  .gap-input {
    width: 100%;
    min-width: 0;
    font: inherit;
    font-family: var(--font-cue);
    padding: 3px 5px;
    border-radius: 4px;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text);
    outline: none;
  }
  .gap-input:hover {
    border-color: var(--separator);
  }
  .gap-input:focus {
    border-color: var(--accent);
    background: var(--bg-content);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .pin {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    cursor: default;
  }
  .pin.on {
    border-color: transparent;
    background: var(--accent);
    color: var(--on-accent);
  }
  .gap-empty {
    color: var(--text-3);
  }
</style>
