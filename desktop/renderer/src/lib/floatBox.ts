/**
 * 浮窗几何的纯函数（拖动 / 缩放 / 归位）。
 *
 * 与 `QaPanel` 的浮窗同口径：默认落在不遮挡右侧检查器的位置，拖动与缩放都
 * 被视口夹住；组件只负责把结果存进 `$state` 并写 localStorage。
 */

export interface FloatBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Viewport {
  w: number;
  h: number;
}

export interface FloatBoxOptions {
  margin?: number;
  minW?: number;
  minH?: number;
  preferredW?: number;
  preferredH?: number;
  preferredX?: number;
  preferredY?: number;
  /** 右侧检查器宽度：默认落点尽量不压住「试听原声」与 TTS 按钮。 */
  reservedRight?: number;
}

const DEFAULTS = {
  margin: 8,
  minW: 360,
  minH: 300,
  preferredW: 480,
  preferredH: 560,
  preferredX: 268,
  preferredY: 84,
  reservedRight: 400,
};

function merged(options: FloatBoxOptions = {}) {
  return { ...DEFAULTS, ...options };
}

export function clampFloatBox(box: FloatBox, viewport: Viewport, options: FloatBoxOptions = {}): FloatBox {
  const { margin, minW, minH } = merged(options);
  const maxW = Math.max(minW, viewport.w - margin * 2);
  const maxH = Math.max(minH, viewport.h - margin * 2);
  const w = Math.min(Math.max(box.w, minW), maxW);
  const h = Math.min(Math.max(box.h, minH), maxH);
  return {
    w,
    h,
    x: Math.min(Math.max(box.x, margin), Math.max(margin, viewport.w - w - margin)),
    y: Math.min(Math.max(box.y, margin), Math.max(margin, viewport.h - h - margin)),
  };
}

/** 默认落在内容区左侧（避开 236px 侧栏与右侧检查器），不挡「试听原声」按钮。 */
export function defaultFloatBox(viewport: Viewport, options: FloatBoxOptions = {}): FloatBox {
  const { preferredW, preferredH, preferredX, preferredY, minW, minH, margin, reservedRight } =
    merged(options);
  // 窄窗口里把默认落点往左推，尽量别压住右侧检查器的「试听原声」。
  const x = Math.min(preferredX, Math.max(margin, viewport.w - preferredW - reservedRight));
  return clampFloatBox(
    {
      x,
      y: preferredY,
      w: Math.min(preferredW, Math.max(minW, viewport.w - 32)),
      h: Math.min(preferredH, Math.max(minH, viewport.h - 120)),
    },
    viewport,
    { ...options, margin },
  );
}

export function parseFloatBox(
  raw: string | null,
  viewport: Viewport,
  options: FloatBoxOptions = {},
): FloatBox | null {
  try {
    const parsed = JSON.parse(raw || 'null');
    if (
      parsed &&
      Number.isFinite(parsed.x) &&
      Number.isFinite(parsed.y) &&
      Number.isFinite(parsed.w) &&
      Number.isFinite(parsed.h)
    ) {
      return clampFloatBox({ x: parsed.x, y: parsed.y, w: parsed.w, h: parsed.h }, viewport, options);
    }
  } catch {
    /* 手改坏：回默认位置 */
  }
  return null;
}
