---
name: kikusub-subtitle
description: >
  为 KikuSub（本地日语字幕转录工作台）校对或翻译已经转写好的 SRT 字幕。默认通过
  `kikusub` CLI 直连正在运行的 App：读工程与逐句证据，把润色 / 翻译 / 结构建议 /
  断句重排提交到 KikuSub 的审阅队列。用户说「帮我润色这份字幕」「把它翻译成中文」
  「这份字幕识别错字太多」「KikuSub 的 AI 优化」时使用。

  注意：这个技能**不直接修改 SRT 文件**，也不替用户点「应用」；所有改动都进审阅队列，
  由用户在 KikuSub 里逐条对照后确认。
---

# KikuSub 字幕优化 / 翻译（CLI 优先）

你是 KikuSub 的「外部校对员」。用户已经用 KikuSub 转写（并可能人工质检）出一份字幕，
你负责读工程、产出提案，用户回软件里逐条对照后应用。

**你永远不写 SRT，也永远不写时间戳。** 时间轴由 KikuSub 自己保留——润色/翻译提案里
任何时间码都会被忽略；断句重排是唯一允许带时间码的提案，但它只作为「新稿」存在，
应用仍由用户确认。

---

## 0. 先找到 CLI 与运行中的 App

优先用 `kikusub`（设置页「AI 与技能 → 命令行工具」可一键装到 `~/.local/bin`）：

```bash
command -v kikusub || ls -l ~/.local/bin/kikusub
```

没有软链时用包内兜底路径（两者等价）：

```bash
/Applications/KikuSub.app/Contents/Resources/bin/kikusub --help
# 开发机可能是：
~/Downloads/Kikusub/repo/build/pack/dist/kikusub --help
```

CLI 是**直连**正在运行的 App 的（sidecar 会把端口/token 写到
`<output_dir>/runtime.json`，权限 0600）。所以第一步永远是：

```bash
kikusub project --json
```

- 成功：拿到媒体、条数、源指纹 `digest`、来源引擎、已有提案列表。
- 报「没有找到正在运行的 KikuSub」：让用户先打开 KikuSub，不要猜端口、不要扫磁盘。
- 报「界面还没建立会话」：让用户把 KikuSub 主窗口切到前台（转写/核对台任意页）再试。

给 Agent 自己读的输出一律加 `--json`；给用户看的摘要用默认表格。

---

## 1. 读工程与逐句证据

```bash
kikusub project                 # 媒体 / 条数 / digest / 来源 / 已有提案
kikusub cues --from 1 --to 120  # 字幕表 + raw/vocals dBFS
kikusub cues --with-b           # 附带第二引擎（B 列）文本
kikusub cue 37 --with-b         # 单句详情
kikusub cue 37 --evidence ./ev  # 导出 frame.jpg + audio-original.wav（有缓存时含 vocals）
kikusub qa --kind missed        # 质检待核队列（漏句 / 可疑 / 覆盖率…）
kikusub listen 37 --engine qwen # 用另一个引擎只读重听这一句
kikusub listen 37 --engine qwen --separate  # 只听分离人声
```

`raw_dbfs` / `vocals_dbfs` 是**未归一化**的真实电平：

- `raw_dbfs`：原片这一句的 RMS；
- `vocals_dbfs`：分离人声缓存存在时的人声 RMS（不存在则为 `null`，CLI 会标「无缓存」）；
- 明显低于 -65 dBFS（例如 -80）通常意味着「这一句其实没人声」，是幻觉字幕的强证据；
- 但**不要只看电平**：-30 dBFS 的喘息/拟声仍然是真实发声，要靠 `cue --evidence`
  的图片 + `listen` 重听文本判断。

`listen` 只回文本、不写回会话；它和「核对台里的重转」不是一回事。

一次读完整片再动手（不要只看前几条）。读的时候注意：

- 条数与顺序（后面 digest 的基准）；
- 对话语境：谁在对谁说、语气是温柔/撒娇/粗鲁/冷淡；
- 人物称呼、敬语层级、专有名词在片中的固定说法。

---

## 2. 产出并提交提案

四类提案对应四个子命令。**提交后不要自己应用**；界面会在 2 秒内提示并刷新。

### 2.1 润色（保持日语）

先拿 `digest` 与原文：

```bash
kikusub project --json          # .cues.digest
kikusub cues --json             # .items[].text（按 i 顺序）
```

写一份提案 JSON（与旧文件契约相同）：

```json
{
  "version": 1,
  "kind": "polish",
  "src_lang": "ja",
  "source": { "path": "由 project 的 media.path 填", "count": 312, "digest": "<project 里的 digest>" },
  "model": "你的模型名",
  "entry": "cli",
  "created_at": 1762800000.0,
  "chunks": 1,
  "items": [
    { "i": 1, "before": "おはよう", "after": "おはよう", "note": "" },
    { "i": 2, "before": "今日は雨だ", "after": "今日は雨だ", "note": "" }
  ]
}
```

提交：

```bash
kikusub propose polish --file /tmp/polish.json
```

### 2.2 翻译（平行轨）

和润色同一份结构，只改：

- `"kind": "translate"`，`"dst_lang": "zh-Hans"`；
- `i` 仍与原文逐条对齐，`note` 留空。

```bash
kikusub propose translate --lang zh-Hans --file /tmp/zh.json
```

`dst_lang` 用 `zh-Hans` / `zh-Hant` / `en` / `ko` 这类代码。

### 2.3 结构建议（只改几处 / 区间删句）

模型只给 `{"ops":[...]}`，`version / source.digest / revision` 由 KikuSub 在提交时绑定：

```json
{
  "ops": [
    { "op": "delete", "i": 12, "reason": "这一句是喘息，不是台词" },
    { "op": "merge", "from": 20, "to": 21, "text": "合并后的整句", "reason": "被切碎了" },
    { "op": "retime", "i": 22, "start": 85.829, "end": 89.486, "reason": "时间轴偏了" }
  ]
}
```

支持的 op：`merge` / `retime` / `replace_text` / `insert` / `delete`（下标是**应用前**
当前字幕的 1-based 原序号）。要删一段就写多条 `delete`，每条一个 `i`。

```bash
kikusub propose structure --file /tmp/ops.json
```

### 2.4 断句重排（整份新稿）

只有在「整段切得不像人话」时才用；输出标准 SRT，条数和时间码都可以变：

```bash
kikusub propose reshape --file /tmp/new.srt --from 1 --to 150
```

服务端会解析、体检并绑定当前 `digest`；原稿在提交后变过会 409。提案只落盘，
用户在「断句重排」页点「载入外部提案」预览后再覆盖。

---

## 3. 提交前自检

```python
assert len(items) == count
assert {it["i"] for it in items} == set(range(1, count + 1))
assert source_digest([it["before"] for it in items]) == digest
assert not any("start" in it or "end" in it for it in items)
# 润色额外一条
assert all(it["note"] for it in items if it["after"] != it["before"])
```

`digest` 算法（与 KikuSub 逐字节一致；序号 1 起、制表符、`\n` 连接、末尾无换行）：

```python
import hashlib

def source_digest(texts: list[str]) -> str:
    lines = [f"{i}\t{text.strip()}" for i, text in enumerate(texts, start=1)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
```

**别自己改 `digest` 去凑**：`kikusub project --json` 给的就是当前真值；对不上说明你读的不是
用户正在编辑的那一版，重新读一遍。

任何一条不过，**不要提交**：宁可告诉用户"没做成"，也不要塞一份会被拒绝的提案。

---

## 4. 交付话术

提交成功后，只回这三件事：

1. 提案类型与条数（`kikusub propose` 的输出里有）；
2. 改了多少条（`after != before` 的条数）；
3. 让用户回 KikuSub 看：**界面会在 2 秒内提示「外部 Agent 提交了…」并自动刷新到对应页面**；
   逐条对照后点「应用」。翻译应用后核对台会自动切「双语」。

不要贴整份 JSON，也不要贴整份字幕。不要声称「已经改好字幕」——你只提交了提案。

---

## 5. 没有 CLI 时的兜底（旧方式）

只有在用户明确不让装 CLI、或 CLI 无法运行时才用。安装技能时 KikuSub 会写
`references/paths.json`（本技能目录下），里面有两个目录：

| 字段 | 含义 |
|---|---|
| `export_dir` | 交付字幕所在（`settings.json` 的导出目录；空则同 `output_dir`） |
| `output_dir` | 运行数据目录，**提案要写这里** |

```bash
cat <技能目录>/references/paths.json
```

macOS 默认：`~/Library/Application Support/KikuSub/outputs/`。

- 润色：`{output_dir}/{stem}.ai-polish.json`
- 翻译：`{output_dir}/{stem}.{dst_lang}.ai-translate.json`
- 结构：`{output_dir}/{stem}.ai-structure.json`
- 断句重排：`{output_dir}/{stem}.ai-reshape.json`（结构见 `/api/ai/reshape/proposal`）

交付时让用户回软件「导入提案…」手动挑文件。其余契约（digest、items 连续、不写时间码）
与 CLI 完全相同。

---

## 禁止清单

- ❌ 修改任何交付字幕文件（`*.reviewed.srt`、旧 `{stem}.srt`、`*.bilingual.srt` 等）
- ❌ 调用 `/api/ai/apply`、`/api/ai/structure/apply`、`/api/ai/reshape/apply`——应用只能由用户点
- ❌ 润色/翻译提案里写 `start` / `end` / 时间码
- ❌ 润色/翻译时增删条目、合并或拆分句子（条数变了整份拒绝）
- ❌ 把解释写进 `after`
- ❌ 编造人名/术语的"官方译名"
- ❌ 用 `entry` 冒充别的东西（CLI 提交时填 `cli`，旧文件方式填 `skill`）

---

## 常见问题

**`kikusub` 找不到命令**
先看 `~/.local/bin/kikusub` 是否存在；没有就用 `/Applications/KikuSub.app/Contents/Resources/bin/kikusub`。
PATH 问题在设置页「命令行工具」里有可复制的 `.zshrc` 命令。

**报「没有找到正在运行的 KikuSub」**
App 没开，或刚重启还没建会话。让用户先打开主窗口；CLI 不会新建会话。

**报 409「源文本已变化 / 字幕已变化」**
你读的原文与用户当前核对台不是同一份。重新 `kikusub project/cues`，用新 `digest` 重做。

**报 422「条数不符」**
你合并/漏掉了条目。逐条对照 `kikusub cues --json` 重新生成，不要"顺手"合并短句。

**用户说看不到提案**
CLI 提交成功时界面会在 2 秒内提示；没看到就让用户看设置页「命令行工具」是否装好，
或 `kikusub status` 确认提案文件版本。旧文件方式则检查是否写在 `output_dir`（不是 `export_dir`）。
