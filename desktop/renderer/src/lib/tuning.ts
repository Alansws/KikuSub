/**
 * 调参取值的「默认 + 本地改动」合并与落盘口径。
 *
 * 为什么单独一个文件：`store.svelte.ts` 有体积预算（只许变短），而且这块是纯函数，
 * 与 Svelte 状态无关，放这里能被单测直接覆盖。
 *
 * 关键约定：**本地只存与默认值不同的键**。曾经的实现把整份取值快照写进 localStorage，
 * 于是内置默认值一改，老用户界面上永远是旧默认（2026-11-13 踩到）。
 */

export type ParamValues = Record<string, number | boolean>;

export type EngineParamSchema = { key: string; defaults: ParamValues };

/** 读本地增量；坏数据/隐私模式一律退化成空对象。 */
export function readSavedTuning(storageKey: string): Record<string, ParamValues> {
  try {
    const raw = globalThis.localStorage?.getItem(storageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, ParamValues>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

/** 以默认值打底，叠用户的改动；规格表里已删掉的键自然被丢掉。 */
export function mergeParamValues(
  engines: readonly EngineParamSchema[],
  saved: Record<string, ParamValues>,
): Record<string, ParamValues> {
  const values: Record<string, ParamValues> = {};
  for (const engine of engines) {
    values[engine.key] = { ...engine.defaults, ...(saved[engine.key] ?? {}) };
  }
  return values;
}

/** 只留下与默认值不同的键，作为落盘内容。 */
export function changedParamValues(
  values: Record<string, ParamValues>,
  engines: readonly EngineParamSchema[],
): Record<string, ParamValues> {
  const changed: Record<string, ParamValues> = {};
  for (const [engine, current] of Object.entries(values)) {
    const defaults = engines.find((entry) => entry.key === engine)?.defaults ?? {};
    const diff: ParamValues = {};
    for (const [key, value] of Object.entries(current)) {
      if (defaults[key] !== value) diff[key] = value;
    }
    if (Object.keys(diff).length) changed[engine] = diff;
  }
  return changed;
}
