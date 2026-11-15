<script lang="ts">
  /**
   * 「AI 与技能」页签：AI 接口配置 + Agent 技能。
   *
   * 两组是同一个心智模型（把字幕交给外部模型），但一条走 API、一条走 agent 写文件，
   * 所以分成两个分区，各自的「已配置」状态分开显示。
   */
  import SettingsSection from '../../components/settings/SettingsSection.svelte';
  import AiPanel from '../../components/settings/ai/AiPanel.svelte';
  import SkillPanel from '../../components/settings/ai/SkillPanel.svelte';
  import { aiState } from '../../lib/settings/aiConfig.svelte';
  import { skillState, skillStatusLabel } from '../../lib/settings/skill.svelte';

  const keyState = $derived(aiState.hasKey ? '已配置 Key' : '未配置 Key');
  const skillMeta = $derived(skillStatusLabel(skillState.info));
</script>

<div class="sections">
  <SettingsSection
    title="AI 优化"
    caption="用你自己的模型按全片语境修正识别错误。结果只生成建议，在润色 / 翻译页里逐条对照，确认后才写进核对台。"
    meta={keyState}
  >
    <AiPanel />
  </SettingsSection>

  <SettingsSection
    title="Agent 技能"
    caption="让外部 agent（DeepSeek Harness 等）按技能说明读字幕、产出建议文件。"
    meta={skillMeta}
  >
    <SkillPanel />
  </SettingsSection>
</div>

<style>
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
  }
</style>
