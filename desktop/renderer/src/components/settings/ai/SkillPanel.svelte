<script lang="ts">
  /**
   * Agent 技能：把随包 skill 装到 ~/.agents/skills/，让外部 agent 按技能说明
   * 读字幕、写建议文件。与 AI 接口是两条路（一个走 API、一个走文件），所以分成两组。
   */
  import Icon from '../../Icon.svelte';
  import { app } from '../../../lib/store.svelte';
  import {
    installSkill,
    loadSkill,
    skillState,
    skillStatusLabel,
    skillStatusOk,
  } from '../../../lib/settings/skill.svelte';

  const status = $derived(skillStatusLabel(skillState.info));
  const ok = $derived(skillStatusOk(skillState.info));

  function install() {
    void installSkill({
      output_dir: app.config?.output_dir || '',
      export_dir: app.config?.export_dir || '',
    });
  }
</script>

<div class="set-group">
  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">安装位置</span>
      <span class="set-row-desc">装到用户级技能根目录，DSH 等 agent 启动时自动扫描。</span>
    </div>
    <div class="set-row-ctl grow">
      <span class="set-path" title={skillState.info?.targetDir ?? ''}>
        {skillState.info?.targetDir || '—'}
      </span>
      <span class="skill-state" class:ok>{status}</span>
      <button class="btn sm" onclick={install} disabled={skillState.busy}>
        {skillState.busy ? '配置中…' : '一键配置'}
      </button>
      <button class="btn sm ghost" onclick={loadSkill} disabled={skillState.busy}>刷新</button>
    </div>
  </div>
</div>

<div class="note-box">
  <span class="note-icon"><Icon name="doc" size={13} /></span>
  <span>
    配置后，在 agent 里说「帮我把 KikuSub 这份字幕润色一遍 / 翻译成中文」，它会读字幕、写出建议；
    回到「润色 → 重新加载」逐条对照。<b>技能不直接改字幕</b>，也不写入任何密钥。
  </span>
</div>

<style>
  .skill-state {
    font-size: var(--fs-label);
    color: var(--warn);
    white-space: nowrap;
  }
  .skill-state.ok {
    color: var(--success);
  }
</style>
