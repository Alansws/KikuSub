"""FireRedPunc 标点恢复（中文 / 英文，ONNX Runtime / CPU）。

为什么需要它：FireRedASR2-AED 的原始输出**没有标点**。中文没有空格、也没有日语助词那种
可依赖的断句线索，于是一段「一口气说二三十个字」的识别结果只能按字数硬切——字可能都对，
但字幕会难看。FireRedASR2S 的「满血」组合就是 VAD + AED + FireRedPunc，这里补上最后一块。

为什么走 ONNX 而不是上游的 PyTorch 权重：

- 上游 `model.pth.tar`（406 MB）+ `chinese-lert-base`（412 MB），加载要 `torch.load`
  （pickle）；ONNX 版只有 162 MB，且不需要反序列化可执行对象；
- 推理只需要 onnxruntime + tokenizers，都是小依赖，PyInstaller 打包简单；
- 与上游 fp32 的逐 token 决策一致（转换仓库附带 parity 说明），差异只在量化。

实现上的两个关键点（都由测试看守）：

1. **按字符偏移插标点，而不是重建文本**。tokenizer 会把英文小写化；若用 token 拼回文本，
   `MONDAY` 会变成 `monday`。这里用 fast tokenizer 的 offsets 把标点插回原文，原大小写、
   空格、数字写法都不动。
2. **只在完全没有句读时补**。已经有标点的文本（SeedVoice ITN / Whisper / Qwen 的输出）
   再跑一遍只会多出奇怪符号。
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from .model_fetch import snapshot_download_files
from .paths import MODELS_DIR

log = logging.getLogger(__name__)

PUNC_REPO = "jiangzhuo9357/fireredpunc-onnx"
PUNC_DIR_NAME = "firered-punc"
# 真实权重随 FireRed 引擎下载到 `<引擎目录>/punc/`；这个常量只作为独立使用时的默认目录。

PUNC_ENV = "KIKUSUB_PUNC_MODEL"
PUNC_FILES = ("punc.q8w.onnx", "tokenizer.json", "out_dict")
# 与模型训练时的 5 类输出对齐；实际标签顺序从 out_dict 读，读不到才用这份兜底。
FALLBACK_LABELS: tuple[str, ...] = ("", "，", "。", "？", "！")
SENTENCE_MARKS = set("，。！？；：、,.!?;:")
MAX_TOKENS = 480
CHUNK_CHARS = 280

_LOAD_LOCK = threading.Lock()


class PunctuationError(RuntimeError):
    """标点模型缺失或推理失败。调用方应降级为「不补标点」，不要让转写失败。"""


def labels_from_out_dict(path: Path) -> tuple[str, ...]:
    """解析 ``<space> 0`` / ``， 1`` 这类映射，按 id 排成标签表。"""
    try:
        rows: list[tuple[int, str]] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            tag, raw_id = parts[0], parts[-1]
            try:
                index = int(raw_id)
            except ValueError:
                continue
            rows.append((index, "" if tag == "<space>" else tag))
        if not rows:
            return FALLBACK_LABELS
        rows.sort()
        labels = [""] * (max(index for index, _ in rows) + 1)
        for index, mark in rows:
            labels[index] = mark
        return tuple(labels)
    except OSError:
        return FALLBACK_LABELS


def needs_punctuation(text: str) -> bool:
    """文本里没有任何句读时才值得跑模型；有标点的文本再补会变脏。"""
    return bool(text) and not any(char in SENTENCE_MARKS for char in text)


def insert_marks(
    text: str,
    tokens: list[str],
    offsets: list[tuple[int, int]],
    preds: list[int],
    labels: tuple[str, ...],
) -> str:
    """把预测出的标点按字符偏移插回原文（保留原始大小写与空格）。"""
    if not text:
        return text
    pieces: list[str] = []
    last = 0
    for index, ((start, end), pred) in enumerate(zip(offsets, preds)):
        if end <= start:
            continue
        mark = labels[pred] if 0 <= pred < len(labels) else ""
        if not mark:
            continue
        # 词内子词不落标点：标点要落在整个英文单词之后。
        if tokens[index].startswith("##"):
            continue
        if index + 1 < len(tokens) and tokens[index + 1].startswith("##"):
            continue
        if end <= last:
            continue
        # 原文这里已经有句读（或紧跟着句读）时不重复插。
        if text[end - 1] in SENTENCE_MARKS:
            continue
        if end < len(text) and text[end] in SENTENCE_MARKS:
            continue
        pieces.append(text[last:end])
        pieces.append(mark)
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def _split_long_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """超长文本按就近的标点/空格切开，避免撞 BERT 的 512 token 上限。"""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = -1
            for mark in "，。！？,.!?；;、 ":
                found = text.rfind(mark, start, end)
                if found > cut:
                    cut = found
            if cut > start + max_chars // 2:
                end = cut + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _create_session(model_path: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return ort.InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _create_tokenizer(tokenizer_path: Path):
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(tokenizer_path))


class PunctuationModel:
    """进程内单例式的标点模型封装；加载失败不影响转写主链路。"""

    def __init__(self, model_dir: str | Path | None = None) -> None:
        env = str(model_dir or os.environ.get(PUNC_ENV) or "").strip()
        self.model_dir = Path(env).expanduser() if env else MODELS_DIR / PUNC_DIR_NAME
        self._session = None
        self._tokenizer = None
        self._labels: tuple[str, ...] = FALLBACK_LABELS
        self._cls_id = 101

    @property
    def ready(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    @property
    def model_available(self) -> bool:
        return all((self.model_dir / name).is_file() for name in PUNC_FILES)

    def ensure_model(self, progress_cb=None) -> None:
        if self.model_available:
            return
        snapshot_download_files(
            repo_id=PUNC_REPO,
            dest=self.model_dir,
            allow_patterns=[*PUNC_FILES, "LICENSE", "README.md", "SHA256SUMS.txt"],
            progress_cb=progress_cb,
            label="FireRedPunc 标点",
        )
        missing = [name for name in PUNC_FILES if not (self.model_dir / name).is_file()]
        if missing:
            raise PunctuationError(
                f"标点模型不完整，缺少：{', '.join(missing)}（目录 {self.model_dir}）"
            )

    def load(self, progress_cb=None) -> None:
        if self.ready:
            return
        with _LOAD_LOCK:
            if self.ready:
                return
            if not self.model_available:
                raise PunctuationError(
                    f"未找到 FireRedPunc 权重（{self.model_dir}）。"
                    "在设置页对 FireRedASR2 点「校验 / 补齐」即可下载。"
                )
            if progress_cb:
                progress_cb(0.02, "正在加载 FireRedPunc 标点模型（ONNX / CPU）…")
            tokenizer = _create_tokenizer(self.model_dir / "tokenizer.json")
            session = _create_session(self.model_dir / "punc.q8w.onnx")
            labels = labels_from_out_dict(self.model_dir / "out_dict")
            cls_id = tokenizer.token_to_id("[CLS]")
            self._tokenizer = tokenizer
            self._session = session
            self._labels = labels
            self._cls_id = 101 if cls_id is None else int(cls_id)
            log.info("标点模型已加载 | dir=%s | labels=%s", self.model_dir, self._labels)

    def restore(self, text: str) -> str:
        """给一段没有句读的文本补标点；失败抛 ``PunctuationError``。"""
        if not text or not needs_punctuation(text):
            return text
        self.load()
        result: list[str] = []
        for chunk in _split_long_text(text):
            result.append(self._restore_chunk(chunk))
        return "".join(result)

    def _restore_chunk(self, text: str) -> str:
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        if not encoding.ids:
            return text
        ids = [self._cls_id, *encoding.ids]
        logits = self._session.run(
            None,
            {
                "input_ids": [ids],
                "attention_mask": [[1] * len(ids)],
            },
        )[0][0]
        preds = logits.argmax(axis=-1).tolist()
        # 模型输出长度 = token 数（graph 内部去掉 CLS 那位）。
        preds = preds[: len(encoding.tokens)]
        return insert_marks(text, encoding.tokens, encoding.offsets, preds, self._labels)


