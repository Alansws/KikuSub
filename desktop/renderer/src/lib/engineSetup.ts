/**
 * 首启向导 / 设置页「配置本地模型」的纯展示逻辑（无 Svelte / 无网络）。
 *
 * 为什么单独抽：底部状态行出现过一次很别扭的文案——模型其实全装好了，
 * 只因为没有「待下载勾选」就显示「未选择任何要下载的模型」。这类判断只跟
 * items 与勾选数有关，做成纯函数就能用 node 测试直接守住，不必为一句文案
 * 起一次 Electron。
 */

export interface SetupModelState {
  installed: boolean;
  packageMissing?: boolean;
}

/**
 * 底部摘要。
 *
 * 顺序就是用户该先看到什么：
 * 1. 勾了新模型 → 报勾选数与体积；
 * 2. 全部都装好了 → 明确说「无需再下载」，不要再提「未选择」；
 * 3. 装了其中一些、这次没勾 → 说明本次不下载，已有项照常可用；
 * 4. 一个都没装 → 给出可执行的下一步（稍后可在设置里下载）。
 */
export function setupSummary(
  items: SetupModelState[],
  selectedCount: number,
  selectedSize: string,
): string {
  if (selectedCount > 0) return `已选 ${selectedCount} 项 · ${selectedSize}`;
  if (!items.length) return '正在读取模型状态…';

  const installed = items.filter((item) => item.installed).length;
  if (installed === items.length) return '全部模型都已安装，无需再下载';
  if (installed > 0) return `本次不下载新模型；已安装的 ${installed} 项照常可用`;
  if (items.every((item) => item.packageMissing)) {
    return '模型包缺失，请检查安装包或稍后重试';
  }
  return '还没有勾选模型；也可以稍后在「设置 → 引擎与模型」里下载';
}
