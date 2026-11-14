/**
 * 「人声分离（强 BGM / 歌曲）」的全局开关。
 *
 * 只对填写了起止时间的区间转写生效：服务端先对区间做 Demucs htdemucs，
 * 分离出的 vocals 缓存在 audio_cache，换第二个引擎重转不会重复分离。
 * 单独一个模块是为了不碰 `store.svelte.ts` 的行数预算。
 */
export const vocalSeparation = $state({ enabled: false });
