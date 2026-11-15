/**
 * 视图内滚动位置记忆。
 *
 * `App.svelte` 用 `{#key app.view}` 重建整个视图，所以从核对台回到双引擎复核 /
 * 润色页时，长列表默认会跳回第 0 行——几百条的片子里，用户刚点的那一句就在
 * 眼前消失，得重新翻很久。这里只存数字，不碰 DOM：调用方在挂载后把值写回
 * 自己的滚动容器即可。
 *
 * 只存在内存里：切片 / 重启不继承，避免把上一部片的位置套到新片上。key 由
 * 调用方拼（含媒体 id、第二版时间戳、当前分段 / 过滤状态），换对象自然就
 * 找不到旧值。
 */
const offsets = new Map<string, number>();

/** 记下某个列表的滚动位置（负值 / 小数一律归零取整）。 */
export function rememberScroll(key: string, top: number): void {
  const value = Number(top);
  offsets.set(key, Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0);
}

/** 取回滚动位置；没记过时是 0（列表本来就应该从头开始）。 */
export function recallScroll(key: string): number {
  return offsets.get(key) ?? 0;
}

/** 丢掉一批 key（按前缀）。换片 / 丢弃第二版这类「对象没了」的时候用。 */
export function forgetScroll(prefix: string): void {
  for (const key of [...offsets.keys()]) {
    if (key.startsWith(prefix)) offsets.delete(key);
  }
}
