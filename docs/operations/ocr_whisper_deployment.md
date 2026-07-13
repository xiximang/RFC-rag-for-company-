# OCR / 音频解析私有化部署与回退策略

本文档说明如何在企业级私有化 RAG 系统中启用或关闭 OCR（图片 / 扫描型 PDF 文字识别）与音频转录功能，并给出验证方法与常见错误排查。

---

## 1. 功能开关

| 环境变量 | 说明 | 默认值（全量版） | 默认值（轻量版） |
|---|---|---|---|
| `OCR_ENABLED` | 是否启用图片 OCR 与扫描型 PDF 的 OCR 回退 | `true` | `false` |
| `AUDIO_TRANSCRIPTION_ENABLED` | 是否启用音频文件语音识别转录 | `true` | `false` |
| `TESSDATA_PREFIX` | Tesseract 语言数据目录 | `/usr/share/tesseract-ocr/4.00/tessdata` | `/usr/share/tesseract-ocr/4.00/tessdata` |

> 轻量版默认关闭 OCR 与音频转录，以降低内存占用；PDF/Office/Excel/纯文本解析仍然可用。

---

## 2. 全量版与轻量版差异

### 2.1 全量版 `docker-compose.yml`

- `app-backend`、`ingest-worker`、`embed-worker` 均已安装系统依赖：`tesseract-ocr`、`tesseract-ocr-chi-sim`、`poppler-utils`、`ffmpeg`、`libsndfile1`。
- 默认 `OCR_ENABLED=true`、`AUDIO_TRANSCRIPTION_ENABLED=true`。
- `TESSDATA_PREFIX` 指向容器内 Tesseract 语言包路径。
- 扫描型 PDF 在 `pdfplumber` 提取不到文本时，会自动调用 `pdf2image + pytesseract` 做 OCR 回退。

### 2.2 轻量版 `docker-compose.lightweight.yml`

- 默认 `OCR_ENABLED=false`、`AUDIO_TRANSCRIPTION_ENABLED=false`。
- 上传图片或扫描型 PDF 时，系统会记录 warning 并返回占位文本 `[OCR disabled]`，不会崩溃。
- 上传音频文件时，系统会返回占位文本 `[audio transcription disabled]`。
- 如需在轻量版开启，可在 `.env` 中设置：

```bash
OCR_ENABLED=true
AUDIO_TRANSCRIPTION_ENABLED=true
```

> 注意：开启后会显著增加内存与 CPU 占用，建议仅在有充足资源（≥2G 内存）时使用。

---

## 3. 私有化模型路径挂载

### 3.1 Tesseract 语言包

默认镜像已安装 `tesseract-ocr-chi-sim` 与 `tesseract-ocr-eng`，中文场景使用 `lang="chi_sim+eng"`。若需挂载自定义训练数据：

```yaml
services:
  ingest-worker:
    volumes:
      - ./models/tessdata:/usr/share/tesseract-ocr/4.00/tessdata:ro
    environment:
      TESSDATA_PREFIX: /usr/share/tesseract-ocr/4.00/tessdata
```

自定义路径示例：

```yaml
    environment:
      TESSDATA_PREFIX: /app/models/tessdata
    volumes:
      - ./models/tessdata:/app/models/tessdata:ro
```

### 3.2 Whisper 模型

当前音频 pipeline 优先使用 `openai-whisper`，默认加载 `base` 模型。首次运行时会自动下载到缓存目录：

- Linux 容器内：`~/.cache/whisper/`
- 如需离线使用，可预先将模型文件挂载到该目录：

```yaml
services:
  ingest-worker:
    volumes:
      - ./models/whisper:/root/.cache/whisper:ro
```

生产环境建议替换为 `faster-whisper` 或 `whisper.cpp` 以降低资源占用；修改 `audio_pipeline.py` 中 `_transcribe` 方法的模型加载逻辑即可。

---

## 4. 如何验证 OCR / 音频解析生效

### 4.1 本地单元测试（无需 tesseract/ffmpeg）

```bash
cd backend
.venv/Scripts/python -m pytest tests/test_pipelines.py -v
```

预期结果：

- `test_image_pipeline_without_ocr` 通过，内容包含 `test image`，OCR 占位为 `[OCR disabled]`。
- `test_audio_pipeline_placeholder` 通过，内容包含 `[audio transcription disabled]`。
- 所有测试均不崩溃。

### 4.2 容器内验证 OCR

```bash
# 进入运行中的 ingest-worker
docker exec -it rag-ingest-worker bash

# 检查 tesseract 与语言包
tesseract --version
tesseract --list-langs | grep chi_sim

# 测试单张图片
echo "test" > /tmp/test.png  # 或使用真实图片
tesseract /tmp/test.png stdout -l chi_sim+eng
```

### 4.3 容器内验证音频依赖

```bash
docker exec -it rag-ingest-worker bash

# 检查 ffmpeg
ffmpeg -version | head -1

# 检查 Python 音频包（可选）
python -c "import whisper; print('whisper ok')"
python -c "import speech_recognition; print('speech_recognition ok')"
```

### 4.4 端到端验证

上传一张带文字的图片或一个扫描型 PDF，查看解析后的 chunk 内容：

- 若 `OCR_ENABLED=true` 且依赖正常，应出现 `[OCR_TEXT]...[/OCR_TEXT]` 或 `[OCR_PAGE N]...[/OCR_PAGE]` 包裹的真实文本。
- 若 `OCR_ENABLED=false`，应出现 `[OCR disabled]` 占位文本。

---

## 5. 常见报错排查

### 5.1 `TesseractNotFoundError: tesseract is not installed or it's not in your PATH`

- 确认镜像中已安装 `tesseract-ocr`。
- 确认 `Dockerfile` / `Dockerfile.worker` / `Dockerfile.ingest` 的 `apt-get` 步骤未跳过。
- 重新构建镜像：`docker build -t rag-backend-ocr -f backend/Dockerfile backend`。

### 5.2 `RuntimeError: Failed to execute command 'tesseract'` 且语言为中文

- 检查中文语言包是否存在：

```bash
tesseract --list-langs
```

- 确认 `tesseract-ocr-chi-sim` 已安装。
- 确认 `TESSDATA_PREFIX` 指向的目录包含 `chi_sim.traineddata`。

### 5.3 PDF 转图片失败 `pdfinfo` / `pdftoppm` not found

- 安装 `poppler-utils`：

```bash
apt-get install -y poppler-utils
```

- 在 `Dockerfile.ingest` 与 `Dockerfile.worker` 中已包含该包。

### 5.4 音频转录报错 `ffmpeg` not found

- 安装 `ffmpeg`：

```bash
apt-get install -y ffmpeg libsndfile1
```

- Whisper 加载模型需要额外内存，若容器 OOM，请增加 `deploy.resources.limits.memory` 或切换至 `faster-whisper`。

### 5.5 轻量版上传图片后没有 OCR 结果

- 轻量版默认 `OCR_ENABLED=false`，这是预期行为。
- 如需开启，在 `.env` 中设置 `OCR_ENABLED=true` 后重新启动容器。

### 5.6 日志中出现 `[OCR disabled]` 或 `[audio transcription disabled]`

- 这是优雅回退，不是崩溃。
- 检查对应环境变量是否为 `true`。
- 检查系统依赖与语言包/模型是否就绪。

---

## 6. 相关文件

- `backend/Dockerfile`
- `backend/Dockerfile.worker`
- `backend/Dockerfile.ingest`
- `docker-compose.yml`
- `docker-compose.lightweight.yml`
- `backend/app/pipelines/document_pipeline.py`
- `backend/app/pipelines/image_pipeline.py`
- `backend/app/pipelines/audio_pipeline.py`
- `backend/tests/test_pipelines.py`
