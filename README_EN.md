# KoeSub Studio

A local, browser-based workbench for transcribing Japanese video and audio into subtitles, then fixing the timing by hand.

You upload a file, the app segments speech with Silero VAD, transcribes each segment with one of two engines, and gives you a video-plus-waveform editor to review the result line by line, patch missed lines, and export SRT / VTT / TXT. Apart from the one-time model download, all inference runs on your machine — media never leaves it.

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="License: MIT"></a>
  <a href="https://github.com/Alansws/KoeSub-Studio/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Alansws/KoeSub-Studio/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10 | 3.11">
  <img src="https://img.shields.io/badge/Gradio-4.25%2B-FF7C00?style=flat-square" alt="Gradio 4.25+">
  <img src="https://img.shields.io/badge/PyTorch-2.1%2B-EE4C2C?style=flat-square&logo=pytorch&logoColor=white" alt="PyTorch 2.1+">
  <a href="README.md"><img src="https://img.shields.io/badge/Docs-简体中文-blue?style=flat-square" alt="Chinese"></a>
</p>

![Main workbench: transcription settings, video monitor, waveform timeline and cue editor](docs/screenshot-workbench.jpg)

![Review timeline table and full transcription result](docs/screenshot-timeline.jpg)

---

## Features

**Transcription**

- Two switchable Japanese ASR engines (comparison below)
- Silero VAD segmentation by pause; adjustable threshold, minimum speech length, silence threshold, merge gap and maximum segment length
- Optional FFmpeg `dynaudnorm` loudness normalisation on the mono downmix, to lift quiet dialogue and tame background music
- Transcribe a time range only (`00:05:00` or `300`), optionally keeping absolute timeline positions
- Interrupt a running job at any point; completed lines are written to `*.part_cancelled.srt`
- Strip punctuation-only and ellipsis-only cues into a separate `*.clean.srt`

**Review**

- Video preview and waveform timeline on one screen, playhead synced to playback
- Waveform pan and zoom via trackpad or wheel, up to 50× (smallest visible window around 0.4 s)
- Select a region to preview it, transcribe it straight into the timeline, or push its start/end times to the transcription form
- Edit, delete and insert single cues; save whole-table edits; copy the current line
- Undo / redo for the last 50 review operations, covering delete, update, insert, clear, import and append
- Autosave and resume: `*.autosave_draft.srt` plus `*.progress.json`; re-importing jumps back to the line you last edited
- Import an external SRT as a baseline, then merge results either by replacing the baseline or by appending only new cues

**Other**

- Parameter presets: six built in, plus save / overwrite / delete
- Run report with engine, elapsed time, cue and character counts, and every effective parameter; one-click copy
- Binds to `127.0.0.1:7860` only; upload limit 10 GB

## The two engines

| | Anime Whisper | Qwen3-ASR + CTC |
| --- | --- | --- |
| Weights | [`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper) | [`jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf`](https://huggingface.co/jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf) |
| Within-cue timing | VAD segment boundaries; split inside a segment by character count | Per-character CTC forced alignment, 40 ms frame granularity |
| Cue splitting | Punctuation regex plus duration / length caps | Punctuation, pauses, particles, unbreakable-pair rules, dynamic programming |
| Repetition control | `no_repeat_ngram_size` and `repetition_penalty` | Handled by the model, plus a cue-level merge pass |
| Speed | Faster | Slower — one extra CTC forward pass per segment |
| Best for | First-pass drafts, long dialogue, conversational flow | Fine-tuning, timing-sensitive work |

Two points worth stating plainly:

1. CTC alignment resolution is set by the acoustic frame, not by the millisecond field in the output. The encoder frame here is 80 ms and the head upsamples by 2, so per-character timestamps land on a **40 ms** grid. The three-digit milliseconds in the subtitle file are formatting, not measured precision.
2. On the Anime Whisper path, within-cue timing is an **approximation**: cue boundaries come from VAD, and multiple cues inside one segment are split proportionally by character count. Use the Qwen3 engine when you need per-character start and end frames.

## Pipeline

```text
media file
   │
   ├─ ffmpeg → 16 kHz mono (optional dynaudnorm)
   │
   ├─ Silero VAD → speech regions → merge and split by pause / max length
   │
   ├─ Engine A: Anime Whisper          ─→ text → punctuation/length split → proportional timing
   └─ Engine B: Qwen3-ASR + CTC head   ─→ text → forced alignment → per-char frames → DP splitting
   │
   ├─ write SRT / VTT / TXT (outputs/ or next to the media)
   │
   └─ review workspace: video + waveform → fix / patch / undo → export *.reviewed.srt
```

## Requirements

- Python 3.10 or 3.11
- `ffmpeg` and `ffprobe` on your PATH
- `transformers >= 5.13.0` — native Qwen3-ASR support starts there; 4.x fails at import
- Disk: roughly 7 GB for both sets of weights (check the Hugging Face pages for exact sizes), plus room for output
- Memory: 16 GB or more recommended. The Qwen3-ASR weights are about 4 GB, loaded in bf16 on CUDA and Apple Silicon, fp32 on CPU
- Device selection is automatic: Apple Silicon (MPS) → NVIDIA (CUDA) → CPU

## Installation

### Install scripts

Linux / macOS:

```bash
git clone https://github.com/Alansws/KoeSub-Studio.git
cd KoeSub-Studio
chmod +x install.sh
./install.sh
source .venv/bin/activate && python app.py
```

Windows (the script creates the environment and launches the app):

```cmd
git clone https://github.com/Alansws/KoeSub-Studio.git
cd KoeSub-Studio
install.bat
```

Both scripts check for `ffmpeg`, create `.venv` and install `requirements.txt`. PyTorch is installed from the default index; use the manual steps below if you need a specific CUDA build.

### Manual setup

```bash
# 1. Environment
conda create -n koesub python=3.10 -y
conda activate koesub

# 2. PyTorch (pick one)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121   # NVIDIA CUDA 12.1
pip install torch torchaudio                                                     # Apple Silicon / CPU

# 3. Dependencies
pip install -r requirements.txt

# 4. Launch
python app.py
```

Then open <http://127.0.0.1:7860> (the app opens it for you).

## Model weights

Weights are not part of the repository (`.gitignore` excludes `models/`). The first time you use an engine, its weights are downloaded into `models/`.

### Automatic download

The app sets `HF_ENDPOINT` to `https://hf-mirror.com` and fetches with `snapshot_download`, which resumes interrupted transfers. To use the official Hugging Face endpoint instead, edit this line near the top of `app.py`:

```python
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
```

### Manual download

If the mirror is blocked or the download keeps failing:

```bash
pip install -U huggingface_hub

# Anime Whisper
huggingface-cli download litagin/anime-whisper \
  --local-dir models/anime-whisper

# Qwen3-ASR + CTC alignment head
huggingface-cli download jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf \
  --local-dir models/qwen3-asr-ja-anime
```

### Expected layout

```text
models/
├── anime-whisper/
│   ├── config.json
│   ├── generation_config.json
│   ├── model.safetensors
│   ├── preprocessor_config.json
│   ├── tokenizer.json
│   └── vocab.json
└── qwen3-asr-ja-anime/
    ├── config.json
    ├── model.safetensors
    ├── tokenizer_config.json
    ├── vocab.json
    └── ctc_aligner_jav_vocalisation_v3.pt   # CTC alignment head
```

Readiness checks: Anime Whisper looks for `model.safetensors`; Qwen3 looks for `config.json` and the alignment head above.

### Custom paths

If the weights already live elsewhere, point the app at them instead of copying:

```bash
export ANIME_WHISPER_MODEL=/data/models/anime-whisper
export QWEN3_ASR_MODEL=/data/models/qwen3-asr-ja-anime
```

## Usage

1. **Upload media.** Supported: `.mp4 .mkv .mov .webm .avi .m4v .ts` and `.wav .mp3 .m4a .flac .ogg .aac`.
2. **Pick an engine.** Anime Whisper for dialogue-heavy first drafts; Qwen3-ASR when per-character timing matters.
3. **Tune if needed.** Open "声学分段与 VAD 参数精细调优" or load a preset. Each slider states what happens when you raise or lower it.
4. **Limit the range if needed.** Fill in start and end times, or select a region on the waveform and click "同步时间到顶部". Keeping "时间轴与原片全局对齐" checked makes timestamps match the original timeline.
5. **Transcribe.** Progress and status update live. "中途打断" stops the job and keeps what has been completed.
6. **Review and patch.** Select a region on the waveform and click "识别并直接入轨", or edit a single line on the right and click "更新此行". Every change is undoable.
7. **Export.** "导出最终已核对 SRT" in the review panel; the raw transcription can also be downloaded or saved next to the media.

The interface is currently Chinese-only; the labels above are the ones you will see.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Space` | Play / pause |
| `←` / `→` | Step one frame (assumes 24 fps, about 42 ms) |
| `Shift + ←` / `→` | Step five frames |
| `Cmd/Ctrl + Z` | Undo |
| `Cmd/Ctrl + Shift + Z`, `Ctrl + Y` | Redo |

Frame stepping always uses 24 fps as a fixed step size, regardless of the source frame rate.

### Waveform controls

- Trackpad two-finger horizontal: pan; vertical or pinch: continuous zoom
- Zoom slider 1×–50×; "100% 全景" fits the whole file, "聚焦" centres and zooms on the playhead
- Dragging a selection reveals a toolbar: preview, transcribe into the timeline, or copy the times to the form

## Parameters and presets

Presets live in `presets.json` at the repository root (`版本: 1`, split into `whisper` and `qwen` key groups). Writes are atomic; missing fields in older files fall back to defaults.

### Anime Whisper

| Parameter | Default | Effect |
| --- | --- | --- |
| VAD threshold | 0.20 | Lower is more sensitive, higher rejects more noise |
| Speech padding | 200 ms | Extends segment edges to avoid clipped onsets |
| Silence for pause | 150 ms | Lower splits more, higher keeps longer phrases |
| Minimum speech | 120 ms | Filters clicks, keeps short interjections |
| Merge gap | 0.30 s | Maximum gap for merging adjacent segments |
| Max segment length | 12 s | Shorter is faster and hallucinates less |
| No-repeat n-gram | 5 | 0 disables |
| Repetition penalty | 1.15 | 1.10–1.20 recommended |
| Loudness normalisation | off | Turn on for quiet sources |

### Qwen3-ASR

| Parameter | Default | Effect |
| --- | --- | --- |
| VAD threshold | 0.28 | As above |
| Speech padding | 150 ms | Protects initial consonants and trailing vowels |
| Merge gap | 0.5 s | Merges adjacent speech regions |
| Pause for split | 0.12 s | Shorter pauses are not used as break points |
| Target cue duration | 4.3 s | Longer cues incur a splitting cost |
| Max characters per cue | 21 | Exceeding it triggers a grammar-aware break |
| Audio window | 16 s | 12–18 s works best |
| CTC alignment | on | Turning it off falls back to proportional splitting |

## Output files

| File | When |
| --- | --- |
| `{name}.srt` / `.vtt` / `.txt` | Transcription finished |
| `{name}.qwen.*` | Engine suffix added when using Qwen3 |
| `{name}_{00m05s-00m08s}.*` | Range suffix when a time range was set |
| `{name}.part_cancelled.*` | Job interrupted, partial result kept |
| `{name}.clean.*` | After removing punctuation-only cues |
| `{name}.autosave_draft.srt` | Written after every review edit |
| `{name}.progress.json` | Last reviewed line, timestamps and text |
| `{name}.reviewed.srt` | Exported from the review workspace |
| `outputs/web_proxies/{name}_{size}_preview.mp4` | 480p preview proxy, generated on demand |

Files go to `outputs/` by default, or next to the media when "保存至媒体同级目录" is checked.

## Project layout

```text
KoeSub-Studio/
├── app.py                    # Gradio UI, job orchestration, review workspace, waveform front end
├── transcribe.py             # Data structures, format conversion, FFmpeg extraction, VAD, Anime Whisper
├── qwen_ctc.py               # Qwen3-ASR inference, CTC head, Japanese cue splitting, cue healing
├── presets.py                # presets.json validation, backward-compatible loading, atomic writes
├── presets.json              # Built-in presets
├── requirements.txt
├── ruff.toml                 # Lint rule configuration
├── install.sh / install.bat  # Setup scripts
├── .github/workflows/ci.yml  # Ruff check, syntax compile, preset validation
├── README.md / README_EN.md
├── CONTRIBUTING.md
├── LICENSE
├── docs/                     # README screenshots
├── models/                   # Weights, not committed
└── outputs/                  # Subtitles and proxies, not committed
```

## Troubleshooting

**`ffmpeg: command not found`**
Install FFmpeg and put it on PATH: macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg`, Windows `winget install Gyan.FFmpeg`.

**Model download stalls or fails**
Downloads go through `hf-mirror.com` by default. If that mirror is unreachable, change `HF_ENDPOINT` in `app.py`, or download manually with `huggingface-cli` as shown above.

**`ImportError: cannot import name 'AutoModelForMultimodalLM'`**
`transformers` is too old. Native Qwen3-ASR support starts at 5.13.0: `pip install -U "transformers>=5.13.0"`.

**Output repeats the same phrase**
Raise the no-repeat n-gram size or the repetition penalty, and lower the maximum segment length to 8–12 s.

**Whole lines are missed, or quiet speech is skipped**
Lower the VAD threshold below 0.20, increase speech padding, and enable loudness normalisation. Anything still missing can be transcribed directly from a waveform selection.

**Video is black or stutters**
Browsers handle MKV containers and some HEVC encodes poorly. Use "压制 M4 硬件加速监看代理 (480p)": VideoToolbox on macOS, libx264 elsewhere.

**Errors on some ops under Apple Silicon**
`PYTORCH_ENABLE_MPS_FALLBACK=1` is already set, so those ops fall back to CPU — slower, but it runs.

**Out of memory**
Start with Anime Whisper, or reduce the audio window. Loading both engines keeps two sets of weights resident.

## Limitations

- One file at a time; there is no batch queue
- Japanese only — no translation, no subtitle rendering or muxing
- UI text is Chinese, with no i18n layer
- Frame stepping assumes 24 fps and does not read the source frame rate
- `outputs/` and `models/` are never cleaned up; manage disk usage yourself
- Model weights carry their own licences, independent of this project's MIT licence

## Acknowledgements

Recognition is built entirely on other people's work:

- [litagin/anime-whisper](https://huggingface.co/litagin/anime-whisper) — Whisper fine-tuned on Japanese anime speech
- [jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf](https://huggingface.co/jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf) — Japanese-tuned Qwen3-ASR weights and CTC alignment head
- [silero-vad](https://github.com/snakers4/silero-vad) — voice activity detection
- [Gradio](https://www.gradio.app/) — web UI
- [FFmpeg](https://ffmpeg.org/) — audio extraction and transcoding

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, code conventions, and what to include in a bug report.

## License

The code in this repository (`app.py`, `transcribe.py`, `qwen_ctc.py`, `presets.py` and the front-end scripts) is released under the [MIT License](LICENSE).

Model weights downloaded at runtime are not covered by that licence. Check the respective Hugging Face repositories before redistributing or using them commercially.
