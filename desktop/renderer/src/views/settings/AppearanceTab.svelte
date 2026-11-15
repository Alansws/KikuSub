<script lang="ts">
  /**
   * 「外观与朗读」页签：三张主题缩略图 + 朗读偏好。
   *
   * 「明暗」不再是独立控件：青空浅 / 青空深本身就是两张卡，明朝墨固定浅色。
   * 这样选主题只需要点一次，也不必先理解皮肤与明暗两层概念。
   */
  import SettingsSection from '../../components/settings/SettingsSection.svelte';
  import ThemePicker from '../../components/settings/appearance/ThemePicker.svelte';
  import TtsPrefList from '../../components/settings/appearance/TtsPrefList.svelte';
  import { app, setTheme } from '../../lib/store.svelte';
  import { THEME_PREVIEWS } from '../../lib/themes';

  const currentName = $derived(
    THEME_PREVIEWS.find((preview) => preview.id === app.theme)?.name ?? app.theme,
  );
</script>

<div class="sections">
  <SettingsSection
    title="外观主题"
    caption="点缩略图直接切换，立即生效。明朝墨是单色主题，固定浅色；另外两套是青空的明暗两档。"
    meta={`当前：${currentName}`}
  >
    <ThemePicker current={app.theme} onselect={(id) => setTheme(id)} />
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
