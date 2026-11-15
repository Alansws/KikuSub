<script lang="ts">
  /**
   * 朗读偏好：默认用哪一层声音（系统语音 / 克隆音色）、默认克隆音色、音色目录。
   *
   * macOS Inset 分组：左文右控，次要说明压在标题下一行。三行之外不放别的东西，
   * 参考音频的时长建议放在分组下方的脚注里。
   */
  import Icon from '../../Icon.svelte';
  import { tts } from '../../../lib/store.svelte';
  import {
    onTtsDefault,
    onTtsDefaultVoice,
    ttsDefaultVoice,
  } from '../../../lib/settings/ttsPrefs.svelte';
  import { openPath } from '../../../lib/settings/paths.svelte';

  const defaultVoice = $derived(ttsDefaultVoice());
  const hasCustom = $derived(tts.custom.length > 0);
</script>

<div class="set-group">
  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">默认朗读音色</span>
      <span class="set-row-desc">
        系统语音零显存、秒出；克隆音色按角色声线朗读，首次合成要加载模型。
      </span>
    </div>
    <div class="set-row-ctl">
      <div class="seg" role="group" aria-label="默认朗读音色">
        <button class:on={tts.defaultKind === 'system'} onclick={() => onTtsDefault('system')}>
          系统语音
        </button>
        <button
          class:on={tts.defaultKind === 'clone'}
          onclick={() => onTtsDefault('clone')}
          disabled={!hasCustom}
          title={hasCustom ? '' : '先在核对台上传参考音频，或选中一句「从当前句截取」'}
        >
          克隆音色
        </button>
      </div>
    </div>
  </div>

  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">默认克隆音色</span>
      <span class="set-row-desc">
        {#if hasCustom}
          {defaultVoice ? `当前默认：${defaultVoice.name}` : '未指定时使用最近保存的音色。'}
        {:else}
          还没有保存的克隆音色。去核对台「TTS 对照」上传参考音频，或选中一句「从当前句截取」。
        {/if}
      </span>
    </div>
    <div class="set-row-ctl">
      <span class="select-wrap">
        <select
          class="tts-select"
          value={tts.defaultVoiceId}
          onchange={onTtsDefaultVoice}
          disabled={!hasCustom}
          aria-label="默认克隆音色"
        >
          <option value="">最近保存的音色</option>
          {#each tts.custom as voice (voice.id)}
            <option value={voice.id}>{voice.name}</option>
          {/each}
        </select>
        <span class="select-chev"><Icon name="chevron-down" size={11} /></span>
      </span>
    </div>
  </div>

  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">音色目录</span>
      <span class="set-row-desc">参考音频与克隆资产都放在这里。</span>
    </div>
    <div class="set-row-ctl grow">
      <span class="set-path" title={tts.voicesDir}>{tts.voicesDir || '—'}</span>
      <button class="btn sm" onclick={() => openPath(tts.voicesDir)} disabled={!tts.voicesDir}>
        在访达中显示
      </button>
    </div>
  </div>
</div>

<p class="pref-footnote">参考音频建议 3–10 秒、单人干声、无背景音乐；会自动去首尾静音，超长只保留前 10 秒。</p>

<style>
  .tts-select {
    appearance: none;
    height: var(--ctl-h);
    max-width: 220px;
    padding: 0 24px 0 var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    font: inherit;
    font-size: var(--fs-label);
  }
  .tts-select:disabled {
    opacity: 0.5;
  }
  .select-wrap {
    position: relative;
    display: inline-flex;
    align-items: center;
  }
  .select-chev {
    position: absolute;
    right: 7px;
    display: grid;
    place-items: center;
    color: var(--text-3);
    pointer-events: none;
  }
  .pref-footnote {
    margin: var(--sp-2) 0 0;
    font-size: var(--fs-label);
    line-height: 1.6;
    color: var(--text-3);
  }
</style>
