/**
 * 章节自动命名（纯函数）：中文序号、模板替换、按时间顺序算序号。
 *
 * 场景：14:06 只有个时刻点，回头补了起点变成区间章节——这时名字不该再是
 * 「时刻点 14:06」，应当按它在片中的位置叫「章节一 / 章节二」。
 *
 * 规则（与设置项 `chapter_name_template` 同口径，后端 `core/settings.py` 的
 * `normalize_chapter_template` 是同一套收敛规则）：
 * - 模板里 `{num}` = 中文数字，`{n}` = 阿拉伯数字；没有占位符就补 ` {num}`；
 * - 序号只数**区间章节**（时刻点不算），按 `start` 升序；
 * - 只给「自动标题」（时刻点 / 场景 HH:MM–HH:MM / 空）改名，用户自己起的名字不动。
 *
 * 零导入：`node --test` 直接加载 `.ts`。
 */

export const DEFAULT_CHAPTER_TEMPLATE = '章节{num}';
export const MAX_TEMPLATE_LENGTH = 40;

const DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
/** 自动生成的时刻点标题，例如「时刻点 14:06」。 */
const AUTO_POINT = /^时刻点 \d{1,2}:\d{2}(?::\d{2})?$/;
/** 自动生成的区间标题，例如「场景 00:10–14:06」。 */
const AUTO_SCENE = /^场景 \d{1,2}:\d{2}(?::\d{2})?[–-]\d{1,2}:\d{2}(?::\d{2})?$/;

/** 1 → 一、10 → 十、11 → 十一、20 → 二十、105 → 一百零五；超出 999 用阿拉伯数字。 */
export function chineseNumber(n: number): string {
  const v = Math.floor(Math.abs(n));
  if (!Number.isFinite(v) || v < 0) return String(n);
  if (v < 10) return DIGITS[v];
  if (v < 20) return v === 10 ? '十' : `十${DIGITS[v - 10]}`;
  if (v < 100) {
    const tens = Math.floor(v / 10);
    const ones = v % 10;
    return `${DIGITS[tens]}十${ones ? DIGITS[ones] : ''}`;
  }
  if (v < 1000) {
    const hundreds = Math.floor(v / 100);
    const rest = v % 100;
    if (!rest) return `${DIGITS[hundreds]}百`;
    if (rest < 10) return `${DIGITS[hundreds]}百零${DIGITS[rest]}`;
    // 一百一十 / 一百一十五：十位是 1 时要补「一」
    const middle = Math.floor(rest / 10) === 1 ? '一' : '';
    return `${DIGITS[hundreds]}百${middle}${chineseNumber(rest)}`;
  }
  return String(v);
}

/** 与后端同一套收敛：空 → 默认；没有占位符 → 补 ` {num}`；超长截前缀、占位符留末尾。 */
export function normalizeTemplate(raw: string | null | undefined): string {
  const text = (raw ?? '').trim();
  if (!text) return DEFAULT_CHAPTER_TEMPLATE;
  const placeholder = text.includes('{num}') ? '{num}' : text.includes('{n}') ? '{n}' : '{num}';
  const full = placeholder === '{num}' && !text.includes('{num}') ? `${text} {num}` : text;
  if (full.length <= MAX_TEMPLATE_LENGTH) return full;
  const room = Math.max(1, MAX_TEMPLATE_LENGTH - placeholder.length - 1);
  const prefix = full.replace(placeholder, '').trim().slice(0, room).trim();
  return prefix ? `${prefix} ${placeholder}` : DEFAULT_CHAPTER_TEMPLATE;
}

/** 把模板里的占位符换成这一章的序号。 */
export function formatChapterName(template: string | null | undefined, ordinal: number): string {
  const safe = normalizeTemplate(template);
  return safe
    .replaceAll('{num}', chineseNumber(ordinal))
    .replaceAll('{n}', String(Math.max(1, Math.floor(ordinal))));
}

/** 是不是系统自动起的名字（这种名字在升级成区间章节时可以被自动改掉）。 */
export function isAutoTitle(title: string | null | undefined): boolean {
  const text = (title ?? '').trim();
  return !text || AUTO_POINT.test(text) || AUTO_SCENE.test(text);
}

export interface NameableMark {
  id?: string;
  start: number;
  end: number | null;
  title?: string;
}

/**
 * 这一章按时间排在所有区间章节里的第几个（1-based）。
 *
 * 时刻点不算章节；同 `start` 的重复标记把候选排在被比较者之后。
 */
export function chapterOrdinal(marks: readonly NameableMark[], candidate: NameableMark): number {
  const before = marks.filter(
    (mark) =>
      mark.id !== candidate.id && mark.end !== null && mark.start <= candidate.start,
  ).length;
  return before + 1;
}

/**
 * 一步到位：候选章节按当前模板该叫什么。
 *
 * 位置决定序号，但**不与已有标题重名**：在中间插一章时，位置算出来的号可能已经
 * 被占用（例如先有「章节二」再补一个更早的），这时沿序号往后找第一个空号。
 * 既不做「按位置重新编号」（会静默改掉用户看到的名字），也不留重复项。
 */
export function autoChapterName(
  template: string | null | undefined,
  marks: readonly NameableMark[],
  candidate: NameableMark,
): string {
  const safe = normalizeTemplate(template);
  const taken = new Set(
    marks.filter((mark) => mark.id !== candidate.id).map((mark) => (mark.title ?? '').trim()),
  );
  let ordinal = chapterOrdinal(marks, candidate);
  let name = formatChapterName(safe, ordinal);
  while (taken.has(name) && ordinal < 999) {
    ordinal += 1;
    name = formatChapterName(safe, ordinal);
  }
  return name;
}
