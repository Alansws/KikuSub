# 静默截图矩阵

改样式/布局时的验收工具：一次截下关键界面，再和基线做像素比对。**编译通过 ≠ 没改坏。**

底层用的是主进程自带的 `--screenshot`（`show:false` + `capturePage` + `app.exit`），
不抢焦点、可以后台跑，也不参与启动失败计数（见 `desktop/main/launchguard.cjs`）。

## 用法

```bash
# 1) 生成一套截图（默认到 docs/images/shots/current）
bash tools/shots/capture_matrix.sh

# 2) 换视口 / 指定状态 / 输出目录
bash tools/shots/capture_matrix.sh --out /tmp/shots --size 1440x960 --states "review settings"

# 3) 和基线比（PSNR；inf 或 >80dB 视为一致，<35dB 基本可判定改坏了）
bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline
```

状态名：`transcribe` `review` `settings` `export` `ai` `prompts`。`review` 用
`tools/shots/seed.json` 造 12 条字幕（不需要真跑转写）；其余状态靠 `KIKUSUB_DEV_EVAL`
点侧栏切换，所以截图里显示的是真实页面而不是空壳。

## 基线

`docs/images/shots/baseline/` 是 2026-11-13 的三屏基线（`transcribe` / `review` / `settings`，
1360×838）。**改动有意的视觉调整时**：先跑一遍 `--compare baseline` 确认差异只落在预期区域，
再把新的 `current` 覆盖回 `baseline`，并在提交信息里写清改了什么。

## 已知的非确定性

`settings` 页有少量运行时文本（模型目录、日志尾巴），PSNR 会落在 85–99dB 之间波动，
不是回归。`transcribe` / `review` 在同样 seed 下是逐像素一致的（inf）。
