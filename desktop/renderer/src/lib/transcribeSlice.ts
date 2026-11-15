/**
 * 「同步到转写页」的一次性区间消息。
 *
 * 为什么必须消费而不是只靠 `nonce`：`App.svelte` 用 `{#key app.view}` 重建视图，
 * 转写页每次切走都会销毁重建；写在组件里的 `seenSlice` 会跟着归零，而 `app.slice`
 * 还留着上一次的选区。结果是「整片转完自动跳核对台 → 再回转写页」时旧区间又回来了，
 * 用户看到的输入框与真正提交的任务不一致（用户报障）。
 *
 * 消费式语义：谁读走谁置空；视图重建多少次都只生效一次。
 */

export interface SliceRequest {
  start: string;
  end: string;
  nonce: number;
}

export interface SliceHolder {
  slice: SliceRequest | null;
}

/** 读走待填区间并把 store 置空；没有待填区间返回 null。 */
export function takeSlice(holder: SliceHolder): SliceRequest | null {
  const request = holder.slice;
  if (!request) return null;
  holder.slice = null;
  return request;
}
