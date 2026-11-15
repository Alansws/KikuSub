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

# 4) 一次跑三套主题：文件名带 -light / -dark / -mincho 后缀
bash tools/shots/capture_matrix.sh --theme dark --states "polish reshape dual"
```

沙箱或 CI 里 Electron 起不来时，用 `KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox` 追加启动参数；
脚本会为每张图使用独立的临时 `--user-data-dir`，不会落到用户的 Application Support。

状态名：`transcribe` `review` `dual` `polish` `translate` `export` `settings` `prompts`。`review` 用
`tools/shots/seed.json` 造 12 条字幕（不需要真跑转写）；其余状态靠 `KIKUSUB_DEV_EVAL`
点侧栏切换，所以截图里显示的是真实页面而不是空壳。

## 设置页专用矩阵

设置页的取证要「先切主题、再切页签」（主题卡只在外观页里），所以单独一个脚本：

```bash
bash tools/shots/capture_settings_matrix.sh --out /tmp/kikusub-settings-shots
# 只跑其中几张：
bash tools/shots/capture_settings_matrix.sh --only light-engines,dark-env
```

产出 3 主题 × 4 页签 + 4 张展开态/窄视口，共 16 张 PNG。仓库里提交的是转成 WebP 的同一批
（体积约 1/3），转换命令与当次结论见
`docs/sprints/2026-11-settings-redesign/落地记录.md`。

## 基线

`docs/images/shots/baseline/` 是 2026-11-13 的三屏基线（`transcribe` / `review` / `settings`，
1360×838）。**改动有意的视觉调整时**：先跑一遍 `--compare baseline` 确认差异只落在预期区域，
再把新的 `current` 覆盖回 `baseline`，并在提交信息里写清改了什么。

## 已知的非确定性

`settings` 页有少量运行时文本（模型目录、日志尾巴），PSNR 会落在 85–99dB 之间波动，
不是回归。`transcribe` / `review` 在同样 seed 下是逐像素一致的（inf）。
