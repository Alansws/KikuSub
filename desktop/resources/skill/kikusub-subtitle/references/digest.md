# 源指纹 digest 算法

KikuSub 用这个值确认「提案是针对哪一版字幕生成的」。算法必须逐字节可复现，
否则提案会在应用时被 409 拒绝。

## 算法

```python
import hashlib

def source_digest(texts: list[str]) -> str:
    lines = [f"{i}\t{text.strip()}" for i, text in enumerate(texts, start=1)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
```

规则：

- 序号从 **1** 开始，十进制、不补零；
- 每行是 `序号` + **一个制表符** + `该条原文去掉首尾空白`；
- 行间用 `\n` 连接，**末尾不加换行**；
- 整体按 UTF-8 编码后取 sha256，小写十六进制。

## 自测向量

输入：

```
texts = ["おはよう", "またね"]
```

参与哈希的字符串（`\t` 表示制表符，`\n` 表示换行）：

```
1\tおはよう\n2\tまたね
```

期望结果：

```
f8d325855653a38f0700e3e83825e1263bc913edbc3c4874328595aec08d7982
```

算出别的值，说明你的拼接方式不对（最常见：用了 `json.dumps`、多了末尾换行、
或者序号从 0 开始）。

## 为什么要这个

`preferences` 之外没有任何东西能把"提案"和"某一版字幕"绑在一起。digest 就是那条绳子：
用户在核对台改了几条字、或者重新转写过区间，digest 就变了，旧提案自然失效——
这比"应用了才发现错位"要安全得多。
