/**
 * 视图的「名字与位置」唯一来源。
 *
 * 侧栏、标题栏的面包屑、主进程菜单、快捷键面板必须说同一件事：
 * 同一个视图叫什么、在第几段、按什么键。2026-11-25 的重塑里，
 * 「润色 → 锁轴润色」「断句重排 → 重排润色」「翻译 → 双语翻译」改的是
 * **用户可见的名字**，而不是路由 key（key 变了会牵动缓存、快捷键与测试）。
 *
 * 所以：View 联合类型里的 key 不动，这里只维护展示名与分组。
 * 加视图 = 这里加一条 + App.svelte 加一个分支（菜单与侧栏都读这里）。
 */
import type { View } from './store.svelte';

export interface NavItem {
  view: View;
  icon: string;
  label: string;
  /** 与快捷键表一致的提示；空串表示没有全局键。 */
  key: string;
  /**
   * 段内顺序提示（已停用，2026-11-26）。
   *
   * 曾经用 `①` / `②` 在侧栏给「锁轴润色 → 重排润色」标先后，但带圈数字和左侧
   * 线性图标挤在同一行里，读起来像两个图标叠在一起（用户原话：「非常不协调」）。
   * 先后关系改由**页内**说明承担（AI 工具条那句「断句本身错了？去重排润色 →」），
   * 侧栏回到统一的「干净图标 + 纯净标题」。
   */
  ordinal?: never;
}

export interface NavGroup {
  /** 段号：四段是任务阶段，不是装饰（01 准备 → 02 核对 → 03 原文 → 04 交付）。 */
  stage: string;
  /** 段名。 */
  label: string;
  items: NavItem[];
}

/**
 * 四段导航。
 *
 * **段内顺序必须保持不变**：`⌘1..⌘8` 与这张表一一对应（见 lib/shortcuts.svelte.ts），
 * 主进程「显示」菜单也是这个顺序；调顺序等于把快捷键和菜单一起打乱。
 * 「锁轴」在「重排」前面，正好是用户的自然顺序（先改字，必要时才动轴）。
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    stage: '01',
    label: '准备',
    items: [
      { view: 'import', icon: 'tray', label: '导入', key: '⌘1' },
      { view: 'transcribe', icon: 'wave', label: '转写', key: '⌘2' },
    ],
  },
  {
    stage: '02',
    label: '核对',
    items: [
      { view: 'review', icon: 'listcheck', label: '核对台', key: '⌘3' },
      { view: 'dual', icon: 'rows', label: '双引擎复核', key: '⌘4' },
    ],
  },
  {
    stage: '03',
    label: '原文',
    items: [
      { view: 'polish', icon: 'pencil', label: '锁轴润色', key: '⌘5' },
      { view: 'reshape', icon: 'split', label: '重排润色', key: '⌘6' },
    ],
  },
  {
    stage: '04',
    label: '交付',
    items: [
      { view: 'translate', icon: 'quote', label: '双语翻译', key: '⌘7' },
      { view: 'export', icon: 'export', label: '导出', key: '⌘8' },
    ],
  },
];

/** 不属于四段的辅助页：放在侧栏底部或标题栏里，不占段号。 */
export const UTILITY_ITEMS: NavItem[] = [
  { view: 'prompts', icon: 'quote', label: '提示词库', key: '' },
  { view: 'settings', icon: 'gear', label: '设置', key: '⌘,' },
];

const LABELS: Record<View, string> = {
  import: '导入',
  transcribe: '转写',
  review: '核对台',
  dual: '双引擎复核',
  polish: '锁轴润色',
  reshape: '重排润色',
  translate: '双语翻译',
  export: '导出',
  prompts: '提示词库',
  report: '任务详报',
  settings: '设置',
};

/** 页面的展示名（标题栏面包屑、空态文案、无障碍名都读它）。 */
export function viewLabel(view: View): string {
  return LABELS[view];
}

/**
 * 面包屑的「第几段 / 本页名」。
 *
 * 辅助页不装作是四段里的一步：它们的段号是空串，标题栏只显示页名。
 */
export function stageOf(view: View): { stage: string; label: string } {
  for (const group of NAV_GROUPS) {
    if (group.items.some((item) => item.view === view)) {
      return { stage: group.stage, label: viewLabel(view) };
    }
  }
  return { stage: '', label: viewLabel(view) };
}
