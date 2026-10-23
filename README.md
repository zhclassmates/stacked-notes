# knowledge-converter

中文 PDF + MP3 → Markdown 批量转换工具。面向个人知识库、AI 检索与 Git 版本管理。

- **PDF**：PyMuPDF4LLM 提取文字版（保留标题/加粗/列表结构、逐页页码标记）；自动识别扫描版并切换 RapidOCR 逐页识别。
- **音频**：MLX Whisper（`large-v3-turbo`）在 Apple Silicon 本地转写，逐段保留时间戳，按停顿聚段，低置信度段落明确标记。
- **零上传**：全部本地运行，不调用付费 API，原始资料不离开本机。

## 环境要求

- macOS（Apple Silicon 最佳，Whisper 走 MLX 加速）
- Homebrew + FFmpeg（Whisper 解码音频用）
- 首次运行需联网下载 Whisper 模型（约 1.6GB，仅存本机 `~/.cache/huggingface`）
  - 国内网络如走代理，工具会自动读取 macOS 系统代理设置

## 安装

```bash
cd knowledge-converter
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pymupdf pymupdf4llm mlx-whisper rapidocr-onnxruntime pytest
```

## 使用

```bash
# 转换 scripts/sources.txt 里列出的所有资料目录
.venv/bin/python scripts/convert.py

# 或指定目录（可多次）
.venv/bin/python scripts/convert.py --source "/path/资料目录"

# 只转 PDF / 只转音频
.venv/bin/python scripts/convert.py --only pdf
.venv/bin/python scripts/convert.py --only audio

# 强制重转（忽略增量状态）
.venv/bin/python scripts/convert.py --force

# 更换 Whisper 模型
.venv/bin/python scripts/convert.py --model mlx-community/whisper-large-v3-turbo
```

再次执行会自动跳过"已成功且内容未变化"的文件（按 SHA-256 判断）；失败文件记录错误日志，重跑即重试。

## 输出结构

```text
output/
├── .manifest.json            # 增量状态（源文件哈希、产物、错误）
└── 吴军·财商训练40讲/
    ├── index.md              # 资料级索引（章节 → 正文/转写链接表）
    └── 01｜高财商：怎样系统性地创造财富优势？/
        ├── 正文.md           # PDF 提取（含目录、页码标记、来源注释）
        ├── 音频转写.md       # Whisper 逐字转写（含时间戳，不总结不改写）
        ├── 阅读笔记.md       # 个人批注模板（已存在则永不覆盖）
        └── metadata.json     # 章节级来源、哈希、转换参数与状态
```

约定：

- 页码以 HTML 注释 `<!-- 页码: 3 / 7 -->` 标记（源码可搜、渲染不可见）。
- 无法提取文字的图片页、OCR/转写低置信度内容均以 `⚠️` 明确标记，不编造。
- 正文与音频转写**分别成文**，章节同名即配对，差异保留，不做合并删改。

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

## 常见问题

- **模型下载失败**：国内网络需代理；工具会自动沿用 macOS 系统代理。也可手动 `export HTTPS_PROXY=http://127.0.0.1:端口`。
- **Xet CDN 报错**：代码已默认 `HF_HUB_DISABLE_XET=1`。
- **扫描版 PDF 识别差**：确认已安装 `rapidocr-onnxruntime`；OCR 对复杂排版（多栏、表格）只能按行输出纯文本。
