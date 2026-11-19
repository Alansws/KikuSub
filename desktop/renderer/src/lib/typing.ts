/**
 * 焦点是否落在会吞掉字符的输入控件里。
 *
 * 核对台的「播放头同步当前行」不能在用户打字时改选中行，否则会把草稿换掉。
 * 从 `ReviewView.svelte` 抽出来：那是 3800 行文件（行数预算只许变短），
 * 而这段判断与界面状态无关，`node --test` 也能直接覆盖。
 *
 * 缩放滑杆 / 复选框 / 单选 / 按钮不算：它们失焦后不该继续拦住自动同步。
 */
const TEXT_INPUT_TYPES = new Set(['range', 'checkbox', 'radio', 'button', 'submit', 'file']);

export function isTypingTarget(): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  if (el.tagName === 'TEXTAREA' || el.isContentEditable) return true;
  if (el.tagName === 'INPUT') return !TEXT_INPUT_TYPES.has((el as HTMLInputElement).type);
  return false;
}
