/**
 * 标点清理：把转写稿里多出来的句读收拾干净。
 *
 * 为什么需要它：Whisper / Qwen 这类模型很爱在每句末尾补一个 `、` `。` `…`，
 * 有时还补在句子中间。字幕的读法和正文不一样——一行字幕末尾的顿号只会让画面
 * 显得脏，句中多出来的逗号会把一句话切碎。这份规则只做「减法」，不改字、不改条数、
 * 不改时间轴，所以它永远是可逆的（整批替换在 KikuSub 里只压一步历史）。
 *
 * 三条设计约束：
 *
 * 1. **纯函数、零依赖**：`node --test` 要能直接 import 这个 `.ts`（Node 的类型擦除
 *    不支持带扩展名的相对 import 之外的解析），所以这里不许 import 任何东西。
 * 2. **只动标点**：除了把标点换成空格，任何字符都按原样保留——包括假名、汉字、
 *    英文大小写、数字写法。
 * 3. **保守到底**：拿不准就不动。数字与英文的 `.` `,`（`3.14` / `1,000` / `No.1` /
 *    `A.I.`）、问号感叹号、以及清完会变空的行，全部原样保留。
 *
 * 规则表见 `docs/contracts/review-console.md`「批量清理标点」。
 */

/** 句中替换出来的空格用哪种宽度。 */
export type PunctSpace = 'half' | 'full';

export interface CleanOptions {
  /** 句中那一个空格用半角还是全角。默认半角。 */
  space?: PunctSpace;
  /** 连 `…` / `...` 一起清掉（默认关：省略号是语气，不是脏东西）。 */
  stripEllipsis?: boolean;
}

export interface CleanedLine {
  text: string;
  /** 行首 / 行尾删掉的标点个数（统计用）。 */
  end: number;
  /** 句中处理掉的标点个数（统计用）。 */
  mid: number;
  /** 清完会变空，已回退成原文。 */
  reverted: boolean;
}

export interface CleanPlan {
  /** 与入参等长、逐条对齐的新文本。 */
  texts: string[];
  /** 有变化的条目下标（0 基）。 */
  changed: number[];
  /** 清完会变空、被回退成原文的条目下标（0 基）。 */
  skipped: number[];
  /** 行首 / 行尾一共删掉多少处（面板上的「行尾 N 处」）。 */
  endMarks: number;
  /** 句中去掉 / 换成空格多少处（面板上的「句中 N 处」）。 */
  midMarks: number;
}

const HALF = ' ';
const FULL = '\u3000';

/** 会被当作「多余句读」处理的全角符号。`；` `：` 不在其中，它们带语义。 */
const FULL_MARKS = '、，。．';
const FULL_MARK_CLASS = `[${FULL_MARKS}]`;

/**
 * 省略号：`…` `……` `⋯` `‥`，以及半角三点 `...`。
 * 必须整体识别，否则 `...` 会被当成三个句点各换一个空格。
 */
const ELLIPSIS = /(?:…+|⋯+|‥+|\.{3,})/gu;

/**
 * 内部占位符（Unicode 私用区）。先把「不许动的」和「要变成空格的」都换成单个
 * 字符再跑正则，就不会出现「保护规则和替换规则互相踩」的问题。
 */
const S_ELL = '\uE000'; // 省略号 + 序号 + S_ELL_END
const S_ELL_END = '\uE001';
const S_DOT = '\uE002'; // 受保护的点：数字 / 英文上下文里的 `.`
const S_COMMA = '\uE003'; // 受保护的逗号：`1,000` 里的 `,`
const S_SPACE = '\uE004'; // 待落成空格的标点

/** 收尾符号：标点落在它们前面时直接删，不补空格（否则会出现 `「…␣」`）。 */
const CLOSERS = '」』）】》〉】';
const CLOSER_CLASS = `[${CLOSERS}]`;

/**
 * 会被保护起来的半角 `,` `.`：两侧都是英文字母或数字。
 * 覆盖 `3.14`、`1,000`、`1,000.50`、`No.1`、`v2.0`、`A.I.`。
 */
const ALNUM_DOT = /(?<=[0-9A-Za-z])[,.]|[,.](?=[0-9A-Za-z])/g;

function spaceOf(opts: CleanOptions): string {
  return opts.space === 'full' ? FULL : HALF;
}

/** 数一段文本里「算被删掉的标点」有几个：全角标记、半角 `,` `.`、以及待落空格。 */
function countMarks(chunk: string): number {
  let n = 0;
  for (const ch of chunk) {
    if (FULL_MARKS.includes(ch) || ch === ',' || ch === '.' || ch === S_SPACE) n += 1;
  }
  return n;
}

/**
 * 清理一行。
 *
 * 顺序不是随便排的：省略号先摘出来（否则被当成句点拆散），再处理首尾，
 * 然后是括号前的、受数字保护的、剩下的句中标记，最后才统一收空白。
 */
export function cleanLine(line: string, opts: CleanOptions = {}): CleanedLine {
  const space = spaceOf(opts);
  const stripEllipsis = Boolean(opts.stripEllipsis);
  const original = line;
  let end = 0;
  let mid = 0;

  if (!line.trim()) return { text: line, end: 0, mid: 0, reverted: false };

  let s = line;

  // 1. 省略号：默认保留（摘出来当占位符），开了开关就当普通标点处理。
  const ellipses: string[] = [];
  s = s.replace(ELLIPSIS, (m) => {
    if (stripEllipsis) {
      mid += 1;
      return S_SPACE;
    }
    ellipses.push(m);
    return `${S_ELL}${ellipses.length - 1}${S_ELL_END}`;
  });

  // 2. 省略号紧贴的 、。 直接删：`の、…` → `の…`
  if (!stripEllipsis) {
    s = s.replace(
      new RegExp(`${FULL_MARK_CLASS}[ \\u3000]*(?=${S_ELL}\\d+${S_ELL_END})`, 'g'),
      () => {
        mid += 1;
        return '';
      },
    );
  }

  // 3. 行首 / 行尾：整段删掉，连同残留空白。
  const edge = `(?:${FULL_MARK_CLASS}|[,.]|${S_SPACE}|[ \\u3000])`;
  s = s.replace(new RegExp(`^(?:${edge})+`, 'g'), (m) => {
    end += countMarks(m);
    return '';
  });
  s = s.replace(new RegExp(`(?:${edge})+$`, 'g'), (m) => {
    end += countMarks(m);
    return '';
  });

  // 4. 收尾括号前的标点：删掉但不补空格。
  s = s.replace(
    new RegExp(`(?:${FULL_MARK_CLASS}|${S_SPACE})[ \\u3000]*(?=${CLOSER_CLASS})`, 'g'),
    (m) => {
      mid += countMarks(m);
      return '';
    },
  );

  // 5. 数字 / 英文上下文里的半角 . 和 , 先保护起来。
  s = s.replace(ALNUM_DOT, (m) => (m === '.' ? S_DOT : S_COMMA));

  // 6. 剩下的半角 , . 当作句读。
  s = s.replace(/[,.]/g, () => {
    mid += 1;
    return S_SPACE;
  });

  // 7. 全角句读 → 待落空格。连续几个只落一个空格。
  s = s.replace(new RegExp(`${FULL_MARK_CLASS}+`, 'g'), (m) => {
    mid += m.length;
    return S_SPACE;
  });

  // 8. 空白归一：只合并、不换宽度。中文台词自带的半角空格（`Thank you`）保持原样，
  //    全角空格也不会被压成半角——只有「本次替换出来的」那一段才用选定的宽度。
  s = s.replace(new RegExp(`(?:${S_SPACE}|[ \\u3000])+`, 'g'), (run) =>
    run.includes(S_SPACE) ? space : run.startsWith(FULL) ? FULL : HALF,
  );
  s = s.replace(new RegExp(`^[ \\u3000]+|[ \\u3000]+$`, 'g'), '');

  // 9. 还原占位符。
  s = s.replace(new RegExp(`${S_ELL}(\\d+)${S_ELL_END}`, 'g'), (_, i: string) => ellipses[Number(i)]);
  s = s.split(S_DOT).join('.').split(S_COMMA).join(',');

  // 10. 保底：清完是空的，说明这一行只有标点。保留原文，绝不产出空字幕。
  if (!s.trim()) {
    return { text: original, end: 0, mid: 0, reverted: true };
  }
  return { text: s, end, mid, reverted: false };
}

/** 清理一条字幕（可能有多行，逐行处理并保留原有 `\n`）。 */
export function cleanCueText(text: string, opts: CleanOptions = {}): CleanedLine {
  if (!text.includes('\n')) return cleanLine(text, opts);
  const parts = text.split('\n');
  const out: string[] = [];
  let end = 0;
  let mid = 0;
  let reverted = false;
  for (const part of parts) {
    const one = cleanLine(part, opts);
    out.push(one.text);
    end += one.end;
    mid += one.mid;
    if (one.reverted) reverted = true;
  }
  return { text: out.join('\n'), end, mid, reverted };
}

/**
 * 整轨预演：算好每一条会变成什么，以及统计数字。
 *
 * 面板要靠它在**动手之前**报出「影响 278 条 / 行尾 84 处 · 句中 256 处」，
 * 所以这里只做纯计算，不碰网络、不碰状态。
 */
export function planClean(texts: string[], opts: CleanOptions = {}): CleanPlan {
  const out: string[] = [];
  const changed: number[] = [];
  const skipped: number[] = [];
  let endMarks = 0;
  let midMarks = 0;

  texts.forEach((text, index) => {
    const one = cleanCueText(text, opts);
    out.push(one.text);
    endMarks += one.end;
    midMarks += one.mid;
    if (one.reverted) skipped.push(index);
    else if (one.text !== text) changed.push(index);
  });

  return { texts: out, changed, skipped, endMarks, midMarks };
}
