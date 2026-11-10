"""打包预验证探针（阶段 1 风险闸门）。

目的不是产出可用的 sidecar，而是回答一个问题：**torch / transformers /
torchaudio / silero_vad / soundfile 能不能被 PyInstaller onedir 打进产物里，
并且在冻结后的解释器里真的跑起来。**

如果这一步失败，整条 Electron 路线要重估（见改造规划 §8、§9 关键路径），
所以它必须最先做，不能留到阶段 5。

用法：
    pyinstaller --noconfirm --onedir tools/pack/sidecar_probe.py ...
    ./dist/sidecar_probe/sidecar_probe
"""

from __future__ import annotations

import json
import platform
import sys
import time

T0 = time.perf_counter()


def main() -> int:
    report: dict[str, object] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }

    import torch  # noqa: PLC0415

    report["torch"] = torch.__version__
    report["torch_mps_built"] = bool(torch.backends.mps.is_built())
    report["torch_mps_available"] = bool(torch.backends.mps.is_available())

    import torchaudio  # noqa: PLC0415

    report["torchaudio"] = torchaudio.__version__

    import transformers  # noqa: PLC0415

    report["transformers"] = transformers.__version__

    import soundfile  # noqa: PLC0415

    report["soundfile"] = soundfile.__version__

    # silero_vad 的 .jit 权重是数据文件，最容易被 PyInstaller 漏掉，单独确认能加载。
    from silero_vad import load_silero_vad  # noqa: PLC0415

    model = load_silero_vad()
    report["silero_vad_loaded"] = model is not None

    # 真正走一遍内核的公开路径：设备探测 + 字幕往返 + 一个最小张量前向。
    from core.transcribe import SubtitleCue, cues_to_srt, detect_device  # noqa: PLC0415

    report["detect_device"] = detect_device()
    srt = cues_to_srt([SubtitleCue(start=0.0, end=1.0, text="スモーク")])
    report["srt_roundtrip_ok"] = "スモーク" in srt
    report["tensor_sum"] = float(torch.ones(4).sum())

    # CTC 引擎模块依赖 torchaudio 的强制导入，冻结后最容易炸在这里。
    from core import qwen_ctc  # noqa: PLC0415

    report["qwen_ctc_imported"] = bool(qwen_ctc.QwenCtcConfig)

    report["elapsed_s"] = round(time.perf_counter() - T0, 2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
