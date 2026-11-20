/**
 * 逐字 diff（「另一引擎复核」的上下两版对照用）。
 *
 * 与 `core/dual_review.char_ops` 同口径：`eq` 相同 / `del` 只在 A / `ins` 只在 B，
 * 替换拆成一段 del + 一段 ins。用户要的是「一眼看出这两句差在哪」——两个模型
 * 往往只差一两个助词，上下对照不标出来等于让人逐字肉眼比对。
 *
 * 为什么在前端算：单句复核的接口只回文本（`kind="compare"` 不落盘、不带对齐），
 * 这里只需要两句字幕、几十个字，O(n·m) 的 LCS 足够快，也不必为此多一次往返。
 */

export interface DiffOp {
  op: 'eq' | 'del' | 'ins';
  text: string;
}

export interface DiffResult {
  ops: DiffOp[];
  /** 连续不同片段的个数（「3 处不同」里的 3）。 */
  hunks: number;
  equal: boolean;
}

/** 两句字幕的字符量远小于这个上限；超长时退化成整段替换，避免卡住渲染。 */
const MAX_CELLS = 200_000;

/**
 * 逐字比对两段文本。
 *
 * 用「后缀 LCS」而不是 Myers：文本短、实现简单，结果稳定；顺序上不保证
 * 「先 del 后 ins」，但左右两侧各自只渲染自己的 op，所以文本顺序不受影响。
 */
export function charDiff(a: string, b: string): DiffResult {
  const left = Array.from(String(a ?? ''));
  const right = Array.from(String(b ?? ''));
  if (left.length === 0 && right.length === 0) {
    return { ops: [], hunks: 0, equal: true };
  }
  if (left.length * right.length > MAX_CELLS) {
    const ops: DiffOp[] = [];
    if (left.length) ops.push({ op: 'del', text: left.join('') });
    if (right.length) ops.push({ op: 'ins', text: right.join('') });
    return { ops, hunks: 1, equal: false };
  }

  // dp[i][j] = left[i:] 与 right[j:] 的 LCS 长度；倒着填，回溯时从 0 开始。
  const width = right.length + 1;
  const dp = new Int32Array((left.length + 1) * width);
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      const at = i * width + j;
      if (left[i] === right[j]) {
        dp[at] = dp[(i + 1) * width + (j + 1)] + 1;
      } else {
        dp[at] = Math.max(dp[(i + 1) * width + j], dp[i * width + (j + 1)]);
      }
    }
  }

  const ops: DiffOp[] = [];
  let hunks = 0;
  let inDiff = false;
  let current: DiffOp | null = null;
  const push = (op: DiffOp['op'], char: string) => {
    if (op !== 'eq' && !inDiff) {
      hunks += 1;
      inDiff = true;
    } else if (op === 'eq') {
      inDiff = false;
    }
    if (current && current.op === op) {
      current.text += char;
      return;
    }
    current = { op, text: char };
    ops.push(current);
  };

  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) {
      push('eq', left[i]);
      i += 1;
      j += 1;
      continue;
    }
    // 优先丢掉 A 里的字（del），只有 B 侧更长时才先补 B（ins）。
    if (dp[(i + 1) * width + j] >= dp[i * width + (j + 1)]) {
      push('del', left[i]);
      i += 1;
    } else {
      push('ins', right[j]);
      j += 1;
    }
  }
  while (i < left.length) {
    push('del', left[i]);
    i += 1;
  }
  while (j < right.length) {
    push('ins', right[j]);
    j += 1;
  }

  return { ops, hunks, equal: left.join('') === right.join('') };
}
