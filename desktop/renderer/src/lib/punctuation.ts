/**
 * 标点清理：把转写稿里多出来的句读收拾干净。
 *
 * 为什么需要它：Whisper / Qwen 这类模型很爱在每句末尾补一个 `、` `。` `…`，
 * 有时还补在句子中间。字幕的读法和正文不一样——一行字幕末尾的顿号只会让画面
 * 显得脏，句中多出来的逗号会把一句话切碎。这份规则只做「减法」，不改字、不改条数、
 * 不改时间轴，所以它永远是可逆的（整批替换在 KikuSub 里只压一步历史）。
 *
 * 四条设计约束：
 *
 * 1. **纯函数、零依赖**：`node --test` 要能直接 import 这个 `.ts`（Node 的类型擦除
 *    不支持带扩展名的相对 import 之外的解析），所以这里不许 import 任何东西。
 * 2. **只动标点**：除了删标点 / 落一个空格，任何字符都按原样保留——包括假名、汉字、
 *    英文大小写、数字写法。
 * 3. **保守到底**：拿不准就不动。数字与英文的 `.` `,`（`3.14` / `1,000` / `No.1` /
 *    `A.I.`）、问号感叹号、以及清完会变空的行，全部原样保留。
 * 4. **日语不补空格**：句中标记默认**直接删掉**，不落空格（`吐いて、もう一回` →
 *    `吐いてもう一回`）。只有紧邻英文 / 数字时才补一个半角空格——否则
 *    `Thank you、またね` 会粘成 `Thank youまたね`。想要「句中留缝」的旧口径，
 *    面板的「半角空格 / 全角空格」还在。
 *
 * 规则表见 `docs/contracts/review-console.md`「批量清理标点」。
 */

/**
 * 句中标记（`、，。．` 与半角 `,` `.`）怎么落地。
 * - `delete`：直接删掉（默认，日语字幕不补空格）；
 * - `half` / `full`：换成一个半角 / 全角空格（旧口径，仍可选）。
 */
export type MidStyle = 'delete' | 'half' | 'full';

/**
 * 省略号怎么办。
 * - `trailing`：只清**行尾**的（默认）——字幕条尾的 `…` 基本是断句产生的噪音；
 *   句中的 `…`（`あの…そう`）是语气，保留；
 * - `all`：连句中一起清；
 * - `keep`：全部保留。
 */
export type EllipsisMode = 'trailing' | 'all' | 'keep';

export interface CleanOptions {
  /** 句中标记怎么落地。默认 `delete`。 */
  mid?: MidStyle;
  /** 省略号怎么处理。默认 `trailing`（只清行尾）。 */
  ellipsis?: EllipsisMode;
}

export interface CleanedLine {
  text: string;
  /** 行首 / 行尾删掉的标点个数（含行尾省略号，统计用）。 */
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

/**
 * 会被当作「多余句读」处理的符号：全角 `、，。．` 加上半角异体 `｡､`
 * （U+FF61 / U+FF64，某些转写模型会吐这两个，宽度是半角但语义完全相同）。
 * `；` `：` 不在其中，它们带语义。
 */
const FULL_MARKS = '、，。．｡､';
const FULL_MARK_CLASS = `[${FULL_MARKS}]`;

/**
 * 省略号：`…` `……` `⋯` `‥`，以及半角三点 `...`。
 * 必须整体识别，否则 `...` 会被当成三个句点各处理一次。
 */
const ELLIPSIS_RUN = /(?:…+|⋯+|‥+|\.{3,})/gu;
const ELLIPSIS_AT = /^(?:…+|⋯+|‥+|\.{3,})/u;

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
 * 「后面只剩会被清掉的东西」——行尾省略号的判定：后面可以有空白、收尾括号，
 * 以及同样会被删掉的句读（`あ…。` 也算行尾）。句中的 `あの…そう` 不算。
 */
const TAIL_ONLY = /^[ \u3000]*(?:[」』）】》〉、，。．｡､,.…⋯‥])*[ \u3000]*$/u;

/** 紧邻英文 / 数字时不能硬删，否则两个词会粘成一个（`Thank youまたね`）。 */
const ALNUM = /[0-9A-Za-z]/;

/** 句中标记两侧可以顺手吃掉的空白：`吐いて、 もう一回` 不许留下孤零零的空格。 */
const SPACES = '[ \\u3000]*';

/** 匹配「一串空白 + 标记 + 一串空白」，两个空白组用来判断真正的左右邻居。 */
const MID_FULL = new RegExp(`([ \\u3000]*)(?:${FULL_MARK_CLASS})+([ \\u3000]*)`, 'g');
const MID_HALF = new RegExp(`([ \\u3000]*)[,.]([ \\u3000]*)`, 'g');

/**
 * 会被保护起来的半角 `,` `.`：两侧都是英文字母或数字。
 * 覆盖 `3.14`、`1,000`、`1,000.50`、`No.1`、`v2.0`、`A.I.`。
 */
const ALNUM_DOT = /(?<=[0-9A-Za-z])[,.]|[,.](?=[0-9A-Za-z])/g;

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
  const midStyle: MidStyle = opts.mid ?? 'delete';
  const ellMode: EllipsisMode = opts.ellipsis ?? 'trailing';
  const original = line;
  let end = 0;
  let mid = 0;

  if (!line.trim()) return { text: line, end: 0, mid: 0, reverted: false };

  let s = line;

  // 1. 省略号：行尾的清掉（默认口径），句中的摘成占位符留着。
  const kept: string[] = [];
  s = s.replace(ELLIPSIS_RUN, (m: string, offset: number, whole: string) => {
    const atTail = TAIL_ONLY.test(whole.slice(offset + m.length));
    if (ellMode === 'all' || (ellMode === 'trailing' && atTail)) {
      if (atTail) end += 1;
      else mid += 1;
      return '';
    }
    kept.push(m);
    return `${S_ELL}${kept.length - 1}${S_ELL_END}`;
  });

  // 2. 省略号紧贴的 、。 直接删：`の、…` → `の…`
  if (ellMode !== 'all') {
    s = s.replace(
      new RegExp(`(?:${FULL_MARK_CLASS})+${SPACES}(?=${S_ELL}\\d+${S_ELL_END})`, 'g'),
      (m: string) => {
        mid += countMarks(m);
        return '';
      },
    );
  }

  // 3. 行首 / 行尾：整段删掉，连同残留空白。
  const edge = `(?:${FULL_MARK_CLASS}|[,.]|${S_SPACE}|[ \\u3000])`;
  s = s.replace(new RegExp(`^(?:${edge})+`, 'g'), (m: string) => {
    end += countMarks(m);
    return '';
  });
  s = s.replace(new RegExp(`(?:${edge})+$`, 'g'), (m: string) => {
    end += countMarks(m);
    return '';
  });

  // 4. 收尾括号前的标点：删掉但不补空格。
  s = s.replace(
    new RegExp(`(?:${FULL_MARK_CLASS}|${S_SPACE})[ \\u3000]*(?=${CLOSER_CLASS})`, 'g'),
    (m: string) => {
      mid += countMarks(m);
      return '';
    },
  );

  // 5. 数字 / 英文上下文里的半角 . 和 , 先保护起来。
  s = s.replace(ALNUM_DOT, (m) => (m === '.' ? S_DOT : S_COMMA));

  // 6. 句中标记：`delete` 直接删掉（顺带吃掉两侧空白），否则落成一个待定宽度的空格。
  //    只有紧邻英文 / 数字时才补空格，避免 `Thank you` 和 `またね` 粘在一起。
  const dropOrJoin = (whole: string, offset: number, lead: number, marks: string, tail: number) => {
    mid += marks.length;
    if (midStyle !== 'delete') return S_SPACE;
    const before = whole[offset - 1] ?? '';
    const after = whole[offset + lead + marks.length + tail] ?? '';
    return ALNUM.test(before) || ALNUM.test(after) ? S_SPACE : '';
  };

  s = s.replace(MID_FULL, (m: string, lead: string, tail: string, offset: number, whole: string) =>
    dropOrJoin(whole, offset, lead.length, m.trim(), tail.length),
  );
  s = s.replace(MID_HALF, (m: string, lead: string, tail: string, offset: number, whole: string) =>
    dropOrJoin(whole, offset, lead.length, m.trim(), tail.length),
  );

  // 7. 空白归一：只合并、不换宽度。台词里原本的半角空格（`Thank you`）保持原样，
  //    全角空格也不会被压成半角——只有「本次替换出来的」那一段才用选定的宽度。
  const joinWith = midStyle === 'full' ? FULL : HALF;
  s = s.replace(new RegExp(`(?:${S_SPACE}|[ \\u3000])+`, 'g'), (run: string) =>
    run.includes(S_SPACE) ? joinWith : run.startsWith(FULL) ? FULL : HALF,
  );
  s = s.replace(new RegExp(`^[ \\u3000]+|[ \\u3000]+$`, 'g'), '');

  // 8. 还原占位符。
  s = s.replace(new RegExp(`${S_ELL}(\\d+)${S_ELL_END}`, 'g'), (_, i: string) => kept[Number(i)]);
  s = s.split(S_DOT).join('.').split(S_COMMA).join(',');

  // 9. 保底：清完是空的，说明这一行只有标点。保留原文，绝不产出空字幕。
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

/**
 * 面板「原文」行的着色：把**这次真要删掉**的字符标出来。
 *
 * 为什么放在这里：省略号要不要算命中，取决于 `ellipsis` 口径与它是否落在行尾
 * （`吸って…` 该标红，`あの…そう` 不该）。这是规则的一部分，不该在组件里再写一份
 * 正则——两处口径一分叉，预览就会和实际结果对不上。
 */
export function markedSpans(
  text: string,
  opts: CleanOptions = {},
): { text: string; hit: boolean }[] {
  const ellMode: EllipsisMode = opts.ellipsis ?? 'trailing';
  const out: { text: string; hit: boolean }[] = [];
  const push = (chunk: string, hit: boolean) => {
    if (!chunk) return;
    const last = out[out.length - 1];
    if (last && last.hit === hit) last.text += chunk;
    else out.push({ text: chunk, hit });
  };

  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);
    const ell = ELLIPSIS_AT.exec(rest);
    if (ell) {
      const atTail = TAIL_ONLY.test(text.slice(i + ell[0].length));
      push(ell[0], ellMode === 'all' || (ellMode === 'trailing' && atTail));
      i += ell[0].length;
      continue;
    }
    const ch = text[i];
    // `3.14` / `1,000` / `A.I.` 里的半角点被 ALNUM_DOT 保护，不该标成「要删」；
    // 例外是行尾那一个（`A.I.` → `A.I`），那里行尾优先。
    const protectedHalf =
      (ch === ',' || ch === '.') &&
      !/^[ \u3000]*$/.test(text.slice(i + 1)) &&
      (ALNUM.test(text[i - 1] ?? '') || ALNUM.test(text[i + 1] ?? ''));
    push(ch, !protectedHalf && (FULL_MARKS.includes(ch) || ch === ',' || ch === '.'));
    i += 1;
  }
  return out;
}
