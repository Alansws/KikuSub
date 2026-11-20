/**
 * 「人声分离（强 BGM / 歌曲）」的全局开关。
 *
 * 默认 `vad_only`：Demucs 分离出的人声只给 VAD 切分用，ASR 仍听原声。
 * 原因是分离会削掉日语清辅音（す/そ/え 的 s 音），拿分离人声送识别会带来
 * 新的错字；干净人声正好只该解决「BGM 里哪里有人声」。
 *
 * `to_asr` 是高级档（旧行为）：人声被纯歌声 / 极重混响彻底盖死、原声里根本
 * 听不出词时才用，代价是清辅音细节可能被一起削掉。
 *
 * 分离结果缓存在 audio_cache，换第二个引擎重转不会重复分离。
 * 单独一个模块是为了不碰 `store.svelte.ts` 的行数预算。
 */
export type SeparateMode = 'vad_only' | 'to_asr';

export const vocalSeparation = $state({
  enabled: false,
  mode: 'vad_only' as SeparateMode,
});
