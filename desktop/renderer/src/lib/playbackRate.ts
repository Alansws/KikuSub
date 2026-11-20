/**
 * 核对台倍速档位的纯逻辑。
 *
 * 用户拍板的档位固定为 `0.5× / 1× / 1.5× / 2×`；`1` / `3` 各降 / 升一档，
 * `2` 暂停并保留倍速，`⇧2` 归 1×。HTML5 `<video>` 不支持负播放速率，
 * 所以这里只做“倍速”，不做真正的倒放穿梭。
 */

export const SPEEDS = [0.5, 1, 1.5, 2] as const;
export type PlaybackRate = (typeof SPEEDS)[number];

function indexOfRate(rate: number): number {
  const exact = SPEEDS.findIndex((item) => Math.abs(item - rate) < 1e-9);
  if (exact >= 0) return exact;
  // 外部（例如 DevTools）设了 1.25×：按最接近的档位参与升降。
  let best = 0;
  let gap = Number.POSITIVE_INFINITY;
  SPEEDS.forEach((item, index) => {
    const delta = Math.abs(item - rate);
    if (delta < gap) {
      best = index;
      gap = delta;
    }
  });
  return best;
}

/** 升降一档；到头就停在端点，不循环。 */
export function nextSpeed(rate: number, direction: -1 | 1): PlaybackRate {
  const index = indexOfRate(rate);
  const next = Math.max(0, Math.min(SPEEDS.length - 1, index + direction));
  return SPEEDS[next];
}

/** 倍速标签，例如 `1.5×`。 */
export function speedLabel(rate: number): string {
  return `${rate}×`;
}
