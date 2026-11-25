<script lang="ts">
  /**
   * 「以此句音频新建音色」浮层。
   *
   * 从 `ReviewView.svelte` 原样搬出（Step 4.1 纯结构拆分）：命名、参考文本、
   * 提取请求与焦点管理都在这里；浮层挂在 body 下，避免切页动画的 transform
   * 把 `position: fixed` 带偏（见 lib/portal.ts）。
   */
  import { tick } from 'svelte';
  import { app, extractTtsVoiceFromCue, toast, tts } from '../../lib/store.svelte';
  import { portal } from '../../lib/portal';
  import { tcShort } from '../../lib/time';

  interface VoiceDialogState {
    index: number;
    name: string;
    refText: string;
  }

  let { dialog = $bindable(null) }: { dialog?: VoiceDialogState | null } = $props();

  let busy = $state(false);
  let nameEl = $state<HTMLInputElement | null>(null);

  // 浮层打开后把焦点放进名字输入框（比 autofocus 更可控，也不会触发 Svelte 的无障碍告警）
  $effect(() => {
    if (!dialog) return;
    void tick().then(() => {
      nameEl?.focus();
      nameEl?.select();
    });
  });

  async function createVoiceFromCue() {
    if (!dialog) return;
    const name = dialog.name.trim();
    if (!name) {
      toast('先给这个音色起个名字', 'warn');
      return;
    }
    busy = true;
    try {
      await extractTtsVoiceFromCue(dialog.index, name, dialog.refText);
      dialog = null;
    } catch (err) {
      toast(`提取音色失败：${(err as Error).message}`, 'error');
    } finally {
      busy = false;
    }
  }
</script>

{#if dialog}
  {@const vc = app.cues[dialog.index]}
  <button
    class="vd-backdrop"
    use:portal
    aria-label="关闭新建音色"
    onclick={() => {
      if (!busy) dialog = null;
    }}
  ></button>
  <div class="vd" use:portal role="dialog" aria-modal="true" aria-label="新建克隆音色">
    <div class="vd-head">以此句音频新建音色</div>
    <div class="vd-sub">
      {#if vc}
        第 {dialog.index + 1} 句 · {tcShort(vc.start)}–{tcShort(vc.end)}
        <span class="vd-dur">{(vc.end - vc.start).toFixed(1)}s</span>
      {/if}
    </div>
    <label class="vd-field">
      <span>音色名</span>
      <input
        bind:this={nameEl}
        bind:value={dialog.name}
        maxlength="40"
        placeholder="角色名，例如「女主角」"
        onkeydown={(e) => {
          if (e.key === 'Enter' && !busy) {
            e.preventDefault();
            void createVoiceFromCue();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            dialog = null;
          }
        }}
      />
    </label>
    <label class="vd-field">
      <span>参考文本（这句的日文，用于对齐声线）</span>
      <textarea bind:value={dialog.refText} rows="2"></textarea>
    </label>
    <p class="vd-note">
      后端会用 ffmpeg 从当前视频精确切出这句的人声（前后各留 0.2 秒），
      3–10 秒最稳。{tts.engine && !tts.engine.installed
        ? '提取不需要模型；朗读前再到右侧点「下载克隆模型」。'
        : ''}
    </p>
    <div class="vd-actions">
      <button class="btn mini" onclick={() => (dialog = null)} disabled={busy}>取消</button>
      <span class="vd-spacer"></span>
      <button class="btn mini primary" onclick={createVoiceFromCue} disabled={busy}>
        {busy ? '提取中…' : '提取并保存'}
      </button>
    </div>
  </div>
{/if}

<style>
  .vd-backdrop {
    position: fixed;
    inset: 0;
    z-index: 80;
    border: 0;
    padding: 0;
    margin: 0;
    background: var(--scrim-soft);
    backdrop-filter: blur(2px);
    -webkit-backdrop-filter: blur(2px);
    cursor: default;
  }
  /* 一张小表：10px 圆角、纸白、1px 发丝线、popover 阴影。
     标题 15/600（Heading 档），说明 11.5 第二级灰；动作用 28px 的 ·
     取消在左、主操作在右（macOS 的确认表都是这个顺序）。 */
  .vd {
    position: fixed;
    z-index: 81;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(360px, calc(100vw - 48px));
    padding: var(--sp-4) var(--sp-4) var(--sp-3);
    border-radius: var(--rad-panel);
    background: var(--raise);
    border: 1px solid var(--line);
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .vd-head {
    font-size: var(--fs-heading);
    line-height: var(--lh-heading);
    font-weight: 600;
    color: var(--ink);
    letter-spacing: -0.005em;
  }
  .vd-sub {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: -6px;
    font-family: var(--font-mono);
    font-size: var(--fs-mono);
    line-height: 16px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }
  .vd-dur {
    padding: 0 var(--sp-1);
    border-radius: 3px;
    background: var(--fill);
  }
  .vd-field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    font-size: var(--fs-label);
    letter-spacing: 0.04em;
    color: var(--ink-3);
  }
  .vd-field input,
  .vd-field textarea {
    width: 100%;
    box-sizing: border-box;
    min-height: var(--ctl-h-lg);
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--ink);
    font: inherit;
    font-family: var(--font-cue);
    font-size: 13px;
    line-height: 19px;
    padding: 5px var(--sp-2);
    resize: vertical;
  }
  .vd-field input {
    font-family: var(--font-sans);
  }
  .vd-field input:focus,
  .vd-field textarea:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .vd-note {
    margin: 0;
    font-size: 11.5px;
    line-height: 17px;
    color: var(--ink-3);
  }
  .vd-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: 2px;
  }
  .vd-spacer {
    flex: 1;
  }
</style>
