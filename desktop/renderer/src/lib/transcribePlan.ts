/**
 * 转写页「这一趟要做什么」的唯一决策层（2026-11-25 重做）。
 *
 * ## 为什么要重做
 *
 * 旧界面把一趟任务拆成了四个控件：识别引擎、三个场景开关（其中一个是
 * 「双引擎顺序协同」）、起止时间、结果处理 + 去向。最要命的是「去向」被条件
 * 隐藏：`canChooseDest` 要求 `fullCover`，也就是只有整片转写时才允许把结果
 * 放进第二列。用户逐章转录（先 Whisper 进核对台，再换 Qwen 跑同一段进双引擎
 * 复核）时，那个入口恰好消失——而服务端的 `set_alt_review(replace_range=…)`
 * 早就会按区间合并第二版，只是单引擎路径没接线。
 *
 * ## 现在的模型
 *
 * 一个轴：**产出**
 * - `primary`：写核对台（主稿）。档位仍是 applyMode.ts 的三档；
 * - `alt`：只写第二版（双引擎复核的 B），核对台零改动；整片替换整列，区间只
 *   替换该区间；
 * - `both`：顺序跑两个引擎，主稿进核对台、副稿进第二版（旧的「双引擎顺序协同」）。
 *
 * 「范围」与「引擎」是另外两个独立轴，不再参与「能不能写第二列」的判断。
 *
 * ## 约束
 *
 * - **零运行时相对导入**：`desktop/test/transcribePlan.test.mjs` 用 `node --test`
 *   直接加载本文件（Node 的类型剥离不会给无扩展名路径补 `.ts`，tsconfig 也没开
 *   `allowImportingTsExtensions`）。applyMode 的那几个纯函数由调用方以 `kernel`
 *   注入——这也是核对台 `clampStart` 用的同一种做法，避免复制第二份档位实现。
 * - 文案必须写清「删掉什么 / 不动什么」，不出现「自动」这类黑箱说法；
 * - 第二版是只读对照：任何目标都不许改核对台。
 */

import type { ApplyChoice, ApplyContext, ApplyMode } from './applyMode';

export type OutputTarget = 'primary' | 'alt' | 'both';

/** applyMode.ts 的纯函数集合；只在运行时由调用方注入。 */
export interface ApplyKernel {
  applyChoices: (ctx: ApplyContext) => ApplyChoice[];
  dualChoices: (ctx: ApplyContext) => ApplyChoice[];
  resolveApplyChoice: (mode: ApplyMode, ctx: ApplyContext) => ApplyMode;
  resolveDualApply: (mode: ApplyMode, ctx: ApplyContext) => ApplyMode;
  applyHint: (mode: ApplyMode, ctx: ApplyContext) => string;
  isDestructiveChoice: (mode: ApplyMode, ctx: ApplyContext) => boolean;
  rangeSpan: (start: string, end: string) => string;
}

export interface PlanInput {
  target: OutputTarget;
  ctx: ApplyContext;
  /** 用户上次选的档位；只对 primary / both 有意义。 */
  apply: ApplyMode;
  /** 核对台里有没有主稿。第二版是对照稿，没有主稿无处对照。 */
  hasCues: boolean;
  engineLabel: string;
  /** 主稿已知的引擎名；逐章转录时可能为空。 */
  primaryEngineLabel: string;
  secondary: string;
  secondaryLabel: string;
  /** 可配对的日语副引擎 key。 */
  candidates: string[];
  alt: { exists: boolean; count: number; engineLabel: string };
}

export interface TranscribePlan {
  target: OutputTarget;
  /** 实际发给服务端的 `apply`。第二版只用它表达整片 / 区间语义。 */
  apply: ApplyMode;
  /** 这次结果写进第二列（核对台零改动）。 */
  altReview: boolean;
  /** 第二版只替换该区间，保留 B 的其它区间。 */
  altRange: boolean;
  /** `target='both'` 时的副引擎 key；其余为空串。 */
  dualEngine: string;
  /** 主区要显示的档位（第二版为空数组：没有可选的档位）。 */
  choices: ApplyChoice[];
  /** 一句话写清「点下去会发生什么」。 */
  hint: string;
  /** 主按钮文案：按钮自己说明这一趟干什么。 */
  button: string;
  /** 非空 = 当前组合不可执行，原因直接给用户看。 */
  blocked: string;
  /** 会删掉核对台区间外字幕的档位；界面据此弹二次确认。 */
  destructive: boolean;
  /** 不阻塞但必须提醒的风险（例如把两个引擎混进同一份 B）。 */
  warning: string;
}

/** 引擎从 A 切到 B 时默认产出：已有一稿就默认写第二版，避免手一滑把主稿覆盖。 */
export function defaultTarget(input: {
  hasCues: boolean;
  engine: string;
  primaryEngine: string;
}): OutputTarget {
  if (!input.hasCues) return 'primary';
  if (input.primaryEngine && input.engine && input.primaryEngine !== input.engine) return 'alt';
  return 'primary';
}

/** 产出在界面上的短名（底栏与右栏共用）。 */
export function targetLabel(target: OutputTarget): string {
  if (target === 'alt') return '第二版（对照）';
  if (target === 'both') return '两版一起（A + B）';
  return '主稿（核对台）';
}

function mixingWarning(input: PlanInput, incomingEngineLabel: string): string {
  if (!input.alt.exists) return '';
  const existing = input.alt.engineLabel;
  if (!existing || !incomingEngineLabel || existing === incomingEngineLabel) return '';
  return `现有第二版来自 ${existing}；这次用 ${incomingEngineLabel} 写进同一份 B，B 的引擎名会变成后者。想干净重来就先丢弃第二版。`;
}

export function resolvePlan(input: PlanInput, kernel: ApplyKernel): TranscribePlan {
  const { ctx } = input;
  const span = kernel.rangeSpan(ctx.start, ctx.end);

  if (input.target === 'alt') {
    const altRange = !ctx.fullCover;
    const existing = input.alt.exists
      ? `（现有第二版 ${input.alt.engineLabel || '未知引擎'} · ${input.alt.count} 条会被替换）`
      : '';
    return {
      target: 'alt',
      apply: altRange ? 'replace_range' : 'replace',
      altReview: true,
      altRange,
      dualEngine: '',
      choices: [],
      hint: altRange
        ? `只把 ${span} 的第二版换成这次结果；B 的其它区间和核对台都不动`
        : `用 ${input.engineLabel} 整片重转，第二版整列换成这次结果；核对台一个字不动${existing}`,
      button: '生成第二版',
      blocked: input.hasCues ? '' : '还没有主稿。第二版是对照稿，先转一版主稿再来。',
      destructive: false,
      warning: mixingWarning(input, input.engineLabel),
    };
  }

  if (input.target === 'both') {
    const apply = kernel.resolveDualApply(input.apply, ctx);
    const blocked = !input.candidates.length
      ? '需要再启用一个日语引擎，才能两版一起跑。'
      : !input.secondary
        ? '请选择副引擎。'
        : '';
    return {
      target: 'both',
      apply,
      altReview: false,
      altRange: !ctx.fullCover,
      dualEngine: blocked ? '' : input.secondary,
      choices: kernel.dualChoices(ctx),
      hint: `${ctx.fullCover ? '整片' : span}：${input.engineLabel} 先按上面的档位写主稿，${input.secondaryLabel || '副引擎'} 再写第二版；两遍顺序跑，需 12GB 以上内存`,
      button: '两版一起跑',
      blocked,
      destructive: kernel.isDestructiveChoice(apply, ctx),
      warning: input.secondary ? mixingWarning(input, input.secondaryLabel) : '',
    };
  }

  const apply = kernel.resolveApplyChoice(input.apply, ctx);
  return {
    target: 'primary',
    apply,
    altReview: false,
    altRange: false,
    dualEngine: '',
    choices: kernel.applyChoices(ctx),
    hint: `写进核对台：${kernel.applyHint(apply, ctx)}`,
    button: '开始转写',
    blocked: '',
    destructive: kernel.isDestructiveChoice(apply, ctx),
    warning: '',
  };
}
