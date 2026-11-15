/**
 * 引擎能力指标与磁盘占用的唯一计算处（设置页「引擎与模型」用）。
 *
 * 为什么要有这个文件：卡片上那三条「速度 / 时间轴 / 内存」不是评分类的虚构分数，
 * 全部来自仓库里已有的实测数字。这些数字只能有一份，否则模板里一处、说明里一处，
 * 改口径时必然对不上。
 *
 * 口径（2026-11-15 与用户确认）：
 *   - 速度用**正向倍数**（`15.4× 实时`），数字越大 = 条越长 = 越快；
 *     旧的 RTF（0.07×）对普通用户是反直觉的。条长按平方根压缩：46× 与 3.3×
 *     同屏时，线性条长会让慢的那个只剩 7%，读起来像「坏了」。
 *   - 时间轴：日语用起点误差 p90（秒，越小越好），中文用边界 F1（越大越好）；
 *     条长都在**同语种对内**归一，所以并排两张卡永远可比。
 *   - 内存：日语用实测峰值，中文用权重体积（口径不同，卡片上带「权重」后缀）；
 *     条越长 = 越费内存。
 *
 * 数据出处：
 *   docs/转录标定-Qwen-2026-11.md §2（830s 素材：Whisper 116s / 6.69GB / 起点 p90 1.35s；
 *   Qwen 54s / 5.07GB / 起点 p90 0.36s）
 *   docs/转录标定-中文-2026-11.md §1（345s 素材：SenseVoice 7–8s、FireRed 102–104s；
 *   边界 F1：SenseVoice 0.678、FireRed 0.545）
 * 耗时取文档所给区间的中值（7.5s / 103s），换素材重测时只改这张表。
 */

export type EngineKey = 'whisper' | 'qwen' | 'sensevoice' | 'firered';
export type EngineGroup = 'ja' | 'zh';
export type MetricTone = 'score' | 'cost';

export interface MetricRow {
  key: 'speed' | 'timeline' | 'memory';
  label: string;
  /** 直接展示的数值，例：`15.4× 实时` / `±0.36s` / `5.1 GB`。 */
  value: string;
  /** 0–100，条长。 */
  bar: number;
  tone: MetricTone;
  /** 悬浮/详情里的完整口径说明。 */
  detail: string;
}

interface TimelineStartP90 {
  kind: 'start-p90';
  seconds: number;
}

interface TimelineBoundaryF1 {
  kind: 'boundary-f1';
  f1: number;
}

interface MemoryPeak {
  kind: 'peak-gb';
  gb: number;
}

interface MemoryWeight {
  kind: 'weight-gb';
  gb: number;
}

interface Measurement {
  group: EngineGroup;
  mediaSeconds: number;
  elapsedSeconds: number;
  timeline: TimelineStartP90 | TimelineBoundaryF1;
  memory: MemoryPeak | MemoryWeight;
}

const MEASUREMENTS: Record<EngineKey, Measurement> = {
  whisper: {
    group: 'ja',
    mediaSeconds: 830,
    elapsedSeconds: 116,
    timeline: { kind: 'start-p90', seconds: 1.35 },
    memory: { kind: 'peak-gb', gb: 6.7 },
  },
  qwen: {
    group: 'ja',
    mediaSeconds: 830,
    elapsedSeconds: 54,
    timeline: { kind: 'start-p90', seconds: 0.36 },
    memory: { kind: 'peak-gb', gb: 5.1 },
  },
  sensevoice: {
    group: 'zh',
    mediaSeconds: 345,
    elapsedSeconds: 7.5,
    timeline: { kind: 'boundary-f1', f1: 0.678 },
    memory: { kind: 'weight-gb', gb: 0.23 },
  },
  firered: {
    group: 'zh',
    mediaSeconds: 345,
    elapsedSeconds: 103,
    timeline: { kind: 'boundary-f1', f1: 0.545 },
    memory: { kind: 'weight-gb', gb: 1.4 },
  },
};

export function isMeasuredEngine(key: string): key is EngineKey {
  return key in MEASUREMENTS;
}

export function engineGroupOf(key: string): EngineGroup | null {
  return isMeasuredEngine(key) ? MEASUREMENTS[key].group : null;
}

const round1 = (value: number) => Math.round(value * 10) / 10;
const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value));

/** 实时倍数：素材时长 / 转写耗时。 */
export function speedMultiplier(key: EngineKey): number {
  const item = MEASUREMENTS[key];
  if (item.elapsedSeconds <= 0) return 0;
  return item.mediaSeconds / item.elapsedSeconds;
}

/**
 * `7.2× 实时`：<20 倍保留一位（7.2 / 15.4 / 3.3），≥20 倍取整（46），
 * 避免 `46.0×` 这种看起来像精确值的写法。
 */
export function formatSpeed(multiple: number): string {
  if (!Number.isFinite(multiple) || multiple <= 0) return '—';
  const text = multiple >= 20 ? String(Math.round(multiple)) : round1(multiple).toFixed(1);
  return `${text}× 实时`;
}

export function formatTimeline(item: Measurement['timeline']): string {
  return item.kind === 'start-p90' ? `±${item.seconds.toFixed(2)}s` : `F1 ${item.f1.toFixed(2)}`;
}

export function formatMemory(item: Measurement['memory']): string {
  const gb = item.gb < 1 ? `${item.gb}` : round1(item.gb).toString();
  return item.kind === 'peak-gb' ? `${gb} GB` : `${gb} GB 权重`;
}

/** 同语种内最大值，用于归一。 */
function groupMax(group: EngineGroup) {
  const keys = (Object.keys(MEASUREMENTS) as EngineKey[]).filter(
    (key) => MEASUREMENTS[key].group === group,
  );
  return {
    speed: Math.max(...keys.map((key) => speedMultiplier(key))),
    timeline: Math.max(
      ...keys.map((key) => {
        const item = MEASUREMENTS[key].timeline;
        // 误差取倒数才是「越大越好」，这样两种口径可以共用一条归一化公式
        return item.kind === 'start-p90' ? 1 / item.seconds : item.f1;
      }),
    ),
    memory: Math.max(...keys.map((key) => MEASUREMENTS[key].memory.gb)),
  };
}

/**
 * 单张卡片的三条指标。
 *
 * 条长公式：
 *   speed    = sqrt(倍数 / 同语种最快倍数)      —— 跨数量级时仍然可读
 *   timeline = (1/误差 或 F1) / 同语种最好值
 *   memory   = 本引擎 / 同语种最费的那个
 */
export function engineMetrics(key: string): MetricRow[] {
  if (!isMeasuredEngine(key)) return [];
  const item = MEASUREMENTS[key];
  const max = groupMax(item.group);
  const multiple = speedMultiplier(key);
  const timelineScore =
    item.timeline.kind === 'start-p90' ? 1 / item.timeline.seconds : item.timeline.f1;

  const speedDetail =
    `${item.mediaSeconds} 秒素材实测 ${item.elapsedSeconds} 秒转完` +
    `（${formatSpeed(multiple)}）。条长按平方根压缩，越大越快。`;
  const timelineDetail =
    item.timeline.kind === 'start-p90'
      ? `起点误差 p90 ${item.timeline.seconds.toFixed(2)}s（越小越好）。`
      : `边界 F1 ±0.4s ${item.timeline.f1.toFixed(3)}（越大越好）。`;
  const memoryDetail =
    item.memory.kind === 'peak-gb'
      ? `实测转写峰值内存 ${item.memory.gb} GB（进程 RSS + MPS 显存）。`
      : `权重文件约 ${item.memory.gb} GB（中文引擎走 ONNX · CPU，不占显存）。`;

  return [
    {
      key: 'speed',
      label: '速度',
      value: formatSpeed(multiple),
      bar: clamp(Math.round(Math.sqrt(multiple / max.speed) * 100)),
      tone: 'score',
      detail: speedDetail,
    },
    {
      key: 'timeline',
      label: '时间轴',
      value: formatTimeline(item.timeline),
      bar: clamp(Math.round((timelineScore / max.timeline) * 100)),
      tone: 'score',
      detail: timelineDetail,
    },
    {
      key: 'memory',
      label: '内存',
      value: formatMemory(item.memory),
      bar: clamp(Math.round((item.memory.gb / max.memory) * 100)),
      tone: 'cost',
      detail: memoryDetail,
    },
  ];
}

/** 分区副标题里的实测口径说明。 */
export const GROUP_CAPTIONS: Record<EngineGroup, string> = {
  ja: '指标为本机实测（830 秒素材），内存条越短越省。',
  zh: '中文侧内存按权重体积计，条越短越省；时间轴为边界 F1。',
};

// ---------------------------------------------------------------------------
// 磁盘占用：按「日语 / 中文 / 音色克隆」三类分段
// ---------------------------------------------------------------------------

export interface UsageInput {
  key: string;
  installed: boolean;
  sizeBytes: number;
}

export interface UsageSegment {
  id: 'ja' | 'zh' | 'clone';
  label: string;
  bytes: number;
  installed: boolean;
  /** 已知字节数？音色克隆暂时拿不到（侧车状态没有 size_bytes），只标是否安装。 */
  known: boolean;
}

export interface UsageSummary {
  segments: UsageSegment[];
  /** 已计量的合计（不含未计量的音色克隆）。 */
  totalBytes: number;
  /** 音色克隆是否已安装（用于图例文案）。 */
  cloneInstalled: boolean;
}

/** 未计量那一类在条上占的视觉比例（不是真实体积，见下）。 */
export const UNKNOWN_SEGMENT_RATIO = 0.12;

export function usageSummary(engines: UsageInput[], cloneInstalled: boolean): UsageSummary {
  const sizeOf = (key: string) => {
    const engine = engines.find((item) => item.key === key);
    // 后端给的是字节整数；这里再 round 一次，避免测试/旧数据里的浮点 GB 漏进显示
    return engine?.installed ? Math.round(Math.max(0, engine.sizeBytes || 0)) : 0;
  };
  const installedOf = (key: string) =>
    Boolean(engines.find((item) => item.key === key)?.installed);

  const jaBytes = sizeOf('whisper') + sizeOf('qwen');
  const zhBytes = sizeOf('sensevoice') + sizeOf('firered');

  return {
    totalBytes: jaBytes + zhBytes,
    cloneInstalled,
    segments: [
      {
        id: 'ja',
        label: '日语',
        bytes: jaBytes,
        installed: installedOf('whisper') || installedOf('qwen'),
        known: true,
      },
      {
        id: 'zh',
        label: '中文',
        bytes: zhBytes,
        installed: installedOf('sensevoice') || installedOf('firered'),
        known: true,
      },
      {
        id: 'clone',
        label: '音色克隆',
        bytes: 0,
        installed: cloneInstalled,
        known: false,
      },
    ],
  };
}

/**
 * 条上的弹性权重。已知的按字节，未计量的固定占 12% 视觉位，
 * 这样「这一类还没装 / 装了但没计量」在条上永远有位置，不会凭空消失。
 */
export function segmentFlex(summary: UsageSummary): number[] {
  const placeholder = Math.max(Math.round(summary.totalBytes * UNKNOWN_SEGMENT_RATIO), 1);
  return summary.segments.map((segment) => {
    if (!segment.known) return placeholder;
    return Math.max(segment.bytes, 0);
  });
}

export function segmentLegend(segment: UsageSegment, formatBytes: (n: number) => string): string {
  if (segment.known) {
    return `${segment.label} ${segment.bytes > 0 ? formatBytes(segment.bytes) : '未安装'}`;
  }
  return `${segment.label} ${segment.installed ? '已安装（未计量）' : '未安装'}`;
}
