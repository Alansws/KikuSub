/**
 * 转写提交参数的纯逻辑（无 Svelte / 无网络）。
 *
 * 之前这些类型与「主副引擎能不能配对」的判断塞在 `store.svelte.ts` 里，
 * 让那个大文件继续变长；抽出来后 store 只负责 toast 与请求。
 */

export interface TranscribeOptions {
  engine: string;
  outputFormat: string;
  startText: string;
  endText: string;
  absoluteTimeline: boolean;
  /** 结果如何进入核对台；档位与文案见 `lib/applyMode.ts`。区间默认 `replace_range`。 */
  apply?: 'replace' | 'append' | 'replace_range';
  /** 整片且核对台非空时：true = 写进双引擎复核第二列，不覆盖核对台。 */
  altReview?: boolean;
  /** 双引擎顺序协同的副引擎；设置后本次任务 kind=dual。 */
  dualEngine?: string;
}

/** 双引擎角色校验；返回空串表示可以提交。 */
export function dualSelectionError(
  primary: string,
  secondary: string,
  enabled: (key: string) => boolean,
): string {
  if (!secondary) return '';
  if (secondary === primary) return '主引擎与副引擎不能是同一个';
  if (!enabled(secondary)) return '副引擎已停用：到「设置 → 引擎与模型」里重新启用';
  return '';
}
