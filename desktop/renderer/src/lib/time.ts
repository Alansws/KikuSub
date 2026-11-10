/** 时间格式化与解析。时间码一律等宽 + tabular-nums，避免逐帧跳动。 */

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

export function tc(sec: number, withMs = true): string {
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const whole = Math.floor(s % 60);
  const base = `${pad(h)}:${pad(m)}:${pad(whole)}`;
  return withMs ? `${base}.${pad(Math.round((s - Math.floor(s)) * 1000), 3)}` : base;
}

/** 表格里的紧凑时间码：MM:SS.mmm */
export function tcShort(sec: number): string {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return `${pad(m)}:${pad(Math.floor(rest))}.${pad(Math.round((rest % 1) * 1000), 3)}`;
}

/** SRT 风格：00:00:01,250 */
export function tcSrt(sec: number): string {
  return tc(sec, true).replace('.', ',');
}

export function formatBytes(n: number): string {
  if (!n) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function formatDuration(sec: number): string {
  if (!sec) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}:${pad(s)}` : `${s}s`;
}

/**
 * 解析用户输入的时间：`01:23`、`1:23.5`、`83.5`、`00:01:23` 都接受。
 * 返回 null 表示「留空」——留空即不限制，不是错误。
 */
export function parseTimeInput(raw: string): number | null {
  const text = (raw || '').trim();
  if (!text) return null;
  const parts = text.split(':');
  if (parts.length > 3) return null;
  let sec = 0;
  for (const part of parts) {
    const v = Number(part.replace(',', '.'));
    if (!Number.isFinite(v) || v < 0) return null;
    sec = sec * 60 + v;
  }
  return Number.isFinite(sec) ? sec : null;
}
