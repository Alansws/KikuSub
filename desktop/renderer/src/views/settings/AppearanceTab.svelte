<script lang="ts">
  /**
   * 「外观与朗读」页签：外观三选一 + 字幕字体 + 章节命名 + 朗读偏好。
   *
   * 2026-11-25 用户拍板把两件事拆开了（见 DESIGN.md）：
   * 1. **外观**默认跟随系统（HIG：不建议应用自己提供明暗开关），设置里保留
   *    「日间校样 / 夜间配音」的显式覆盖，方便夜间长时间工作；
   * 2. **明朝字幕字体**从主题配色里剥离，成为独立的「黑体 / 明朝」偏好。
   */
  import SettingsSection from '../../components/settings/SettingsSection.svelte';
  import AppearancePicker from '../../components/settings/appearance/AppearancePicker.svelte';
  import ChapterNaming from '../../components/settings/appearance/ChapterNaming.svelte';
  import CueFontPicker from '../../components/settings/appearance/CueFontPicker.svelte';
  import PalettePicker from '../../components/settings/appearance/PalettePicker.svelte';
  import TtsPrefList from '../../components/settings/appearance/TtsPrefList.svelte';
  import { app } from '../../lib/store.svelte';
  import {
    appearance,
    setAppearance,
    setCueFont,
    setPalette,
  } from '../../lib/appearanceState.svelte';
  import {
    APPEARANCE_SHOTS,
    CUE_FONTS,
    PALETTES,
    appearanceName,
    cueFontName,
    paletteName,
    type ThemeId,
  } from '../../lib/themes';

  const resolvedName = $derived(
    APPEARANCE_SHOTS.find((shot) => shot.id === (app.theme as ThemeId))?.name ?? app.theme,
  );
</script>

<div class="sections">
  <SettingsSection
    title="外观"
    caption="默认跟随系统：白天是日间校样，入夜自动切夜间配音间。需要在长时间夜间工作时锁定深色，才用下面的覆盖。"
    meta={`当前偏好：${appearanceName(appearance.preference)} → ${resolvedName}`}
  >
    <AppearancePicker
      current={appearance.preference}
      resolved={app.theme as ThemeId}
      systemDark={appearance.systemDark}
      palette={appearance.palette}
      onselect={(id) => setAppearance(id)}
    />
  </SettingsSection>

  <SettingsSection
    title="界面配色"
    caption="六套双模色板，与上面的明暗正交：上面决定日间 / 夜间，这里决定这一面用哪套颜色。点一下立即生效，只换界面基色，不动字体、字号与布局。"
    meta={`当前：${paletteName(appearance.palette)}（${PALETTES.length} 套 · 双模）`}
  >
    <PalettePicker
      current={appearance.palette}
      resolved={app.theme as ThemeId}
      onselect={(id) => setPalette(id)}
    />
  </SettingsSection>

  <SettingsSection
    title="字幕字体"
    caption="只换字幕（原文与译文）的字体，不改配色、字号与密度。黑体扫读更稳，明朝更接近成片观感。"
    meta={`当前：${cueFontName(appearance.cueFont)}（${CUE_FONTS.length} 种）`}
  >
    <CueFontPicker current={appearance.cueFont} onselect={(id) => setCueFont(id)} />
  </SettingsSection>

  <SettingsSection
    title="章节命名"
    caption="把时刻点补成区间、或框选一段设为章节时，按片中顺序自动起名。自己起过名字的章节不会被改。"
  >
    <ChapterNaming />
  </SettingsSection>

  <SettingsSection
    title="朗读"
    caption="决定核对台「朗读」默认用哪一层声音；切换后立即生效。"
  >
    <TtsPrefList />
  </SettingsSection>
</div>

<style>
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
  }
</style>
