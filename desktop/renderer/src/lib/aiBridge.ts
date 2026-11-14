/**
 * store → AI 工作区的单向桥。
 *
 * `store.svelte.ts` 在应用快照 / 导出设置 checkpoint 时需要读写 AI diff 草稿，
 * 但 AI 状态住在 `aiWorkspace.svelte.ts`，后者又依赖 store。直接互相 import 会
 * 形成运行时循环，所以这里留一个只有函数指针的零依赖桥：AI 模块加载时把自己的
 * 实现挂上来；没打开过润色页时桥是空操作（那本来也没有草稿）。
 */
export const aiBridge = {
  applyDraft: (_raw: Record<string, any> | null | undefined): void => {},
  currentDraft: (): Record<string, any> => ({}),
};
