---
name: kikusub-subtitle
description: >
  为 KikuSub（本地日语字幕转录工作台）校对或翻译已经转写好的 SRT 字幕，产出一份
  「提案 JSON」交给 KikuSub 应用。用户说「帮我润色这份字幕」「把它翻译成中文」
  「这份字幕识别错字太多」「KikuSub 的 AI 优化」时使用。

  注意：这个技能**不直接修改 SRT 文件**，只写提案；应用由用户在 KikuSub 里点一下完成。
---

# KikuSub 字幕优化 / 翻译

你是 KikuSub 的「外部提案生成器」。用户已经用 KikuSub 转写（并可能人工质检）出一份
SRT，你负责读它、产出提案，用户回软件里逐条对照后应用。

**你永远不写 SRT，也永远不写时间戳。** 时间轴由 KikuSub 自己保留——提案里任何时间码
都会被忽略，写错了只会误导用户。

---

## 0. 先确认是哪一份字幕

安装本技能时 KikuSub 会写一个 `references/paths.json`——**就在本技能目录下**，先读它。
加载技能时宿主会给出技能目录（`Base directory for this skill: …`），优先用那个绝对路径：

```bash
cat <技能目录>/references/paths.json
```

不确定装在哪时，按顺序取第一个存在的（两处内容一样，任一命中即可）：

```bash
for f in ~/.agents/skills/kikusub-subtitle/references/paths.json \
         ~/.dsh/skills/kikusub-subtitle/references/paths.json; do
  [ -f "$f" ] && { cat "$f"; break; }
done
```

里面有两个关键目录：

| 字段 | 含义 |
|---|---|
| `export_dir` | 交付字幕所在（`settings.json` 的导出目录；空则同 `output_dir`） |
| `output_dir` | 运行数据目录，**提案要写这里** |

字幕文件名是 `{stem}.srt`，`stem` 由媒体文件名派生。找不到就问用户要路径，
**不要猜**、也不要在整个磁盘上瞎搜。

如果 `paths.json` 不存在（用户手动拷过来的技能），按平台默认值：

- macOS：`~/Library/Application Support/KikuSub/outputs/`
- Windows：`%APPDATA%\KikuSub\outputs\`

---

## 1. 读字幕

一次读完整片再动手（不要只看前几条）。读的时候注意：

- 条数与顺序（这是后面自检的基准）；
- 对话的语境：谁在对谁说、语气是温柔/撒娇/粗鲁/冷淡；
- 人物的称呼、敬语层级、专有名词在片中的固定说法。

**不要修改这个 SRT 文件。** 需要中间产物就写到 `/tmp`。

---

## 2. 算源指纹 digest

把「按顺序的每一条原文」拼起来算 sha256。规则必须逐字节复现：

```python
import hashlib

def source_digest(texts: list[str]) -> str:
    lines = [f"{i}\t{text.strip()}" for i, text in enumerate(texts, start=1)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
```

- 序号从 **1** 开始，十进制、不补零；
- 每行 `序号 + 制表符 + 该条原文（去首尾空白）`；
- 行与行之间 `\n`，**末尾不加换行**；
- UTF-8 编码。

自测向量（算出来必须一致，用来确认你没理解错）：

```
texts = ["おはよう", "またね"]
digest = 见 references/digest.md 里的固定值
```

`digest` 写进提案的 `source.digest`。KikuSub 会用同一算法复核；不一致就整份拒绝
（说明你读的文件和用户当前打开的不是同一份，或者你改动了原文）。

---

## 3. 产出提案

### 选哪个文件

| 任务 | `kind` | 写到 |
|---|---|---|
| 校对/润色（保持日语） | `polish` | `{output_dir}/{stem}.ai-polish.json` |
| 翻译成其他语种 | `translate` | `{output_dir}/{stem}.{dst_lang}.ai-translate.json` |

`dst_lang` 用 `zh-Hans` / `zh-Hant` / `en` / `ko` 这类代码。

### 结构

```json
{
  "version": 1,
  "kind": "translate",
  "src_lang": "ja",
  "dst_lang": "zh-Hans",
  "source": { "path": "/…/film.srt", "count": 312, "digest": "<sha256>" },
  "model": "你的模型名",
  "entry": "skill",
  "created_at": 1762800000.0,
  "chunks": 1,
  "items": [
    { "i": 1, "before": "おはよう", "after": "早上好", "note": "" }
  ]
}
```

硬性要求：

1. **`items` 必须列满 `source.count` 条**，`i` 从 1 连续到 n，不许缺、不许重、不许乱序；
2. **不写任何时间戳**（`start`/`end` 都不要出现）；
3. `before` = 该条原文（能让你自己核对对齐），`after` = 你的结果；
4. **不能拆句、不能合句**——条数变了整份提案会被拒绝；
5. 润色时：`after` 与 `before` 不同的条目，`note` 必须写 4–6 个字说明理由（如「同音误识」
   「助词错误」「人名统一」）。翻译时 `note` 留空即可。

### 润色的尺度（重要）

只改**明显的识别错误**：同音/近音误识、助词与活用错误、断词错误、人名与专有名词不一致、
标点与全角半角。

以下都算越界：改写风格、把话说得更"自然"、增删句子、翻译、加括号解释。
**改动率超过 40% 说明你在重写而不是校对**——KikuSub 会弹二次确认，用户会不信任这份结果。

### 翻译的尺度

- 对照全片语气定调（温柔撒娇 / 粗俗轻视 / 冷淡），不要逐句直译；
- 一条原文对一条译文，译文要能单行显示（中文 ≤ 18 个全角字），太长就压缩措辞，**绝不拆条**；
- 人名/称呼第一次出现就定下来，之后全片统一；敬语层级保留（さん/ちゃん 的处理方式要一致）；
- 不加解释、不加括号补充、不音译外来语原文。

---

## 4. 写完必须自检

```python
assert len(items) == count
assert {it["i"] for it in items} == set(range(1, count + 1))
assert source_digest([it["before"] for it in items]) == digest
assert not any("start" in it or "end" in it for it in items)
# 润色额外一条
assert all(it["note"] for it in items if it["after"] != it["before"])
```

任何一条不过，**不要交付**：宁可告诉用户"没做成"，也不要给一份会被拒绝的提案。

---

## 5. 交付话术

写完文件后，只回这三件事：

1. 文件路径；
2. 改了多少条（`after != before` 的条数）；
3. 让用户回软件：**核对 → 工具栏「AI 优化」→ 重新加载 → 逐条看 → 应用**。
   翻译则说明：应用后核对台会自动切「双语」，画面字幕也是两行。

不要贴整份 JSON，也不要贴整份字幕。

---

## 禁止清单

- ❌ 修改 `{stem}.srt` 或任何交付文件
- ❌ 在提案里写 `start` / `end` / 时间码
- ❌ 增删条目、合并或拆分句子
- ❌ 把解释写进 `after`
- ❌ 编造人名/术语的"官方译名"
- ❌ 用 `entry` 冒充别的东西（这个字段应填 `skill`）

---

## 常见问题

**KikuSub 报 409「源文本已变化」**
你读的 SRT 与用户当前核对台不是同一份。让用户在核对台「导出」一次，再重新读新文件。

**报 422「条数不符」**
你合并/漏掉了条目。逐条对照原 SRT 重新生成，不要"顺手"合并短句。

**用户说看不到提案**
文件要写在 `output_dir`（不是 `export_dir`）。写错目录时，用户在 AI 优化台点
「导入提案…」手动挑文件也能用。
