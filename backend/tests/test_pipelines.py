import os
import tempfile
import pytest
from uuid import uuid4
from app.pipelines.factory import PipelineFactory
from app.pipelines.document_pipeline import DocumentIngestPipeline
from app.pipelines.excel_pipeline import ExcelIngestPipeline
from app.pipelines.image_pipeline import ImageIngestPipeline
from app.pipelines.audio_pipeline import AudioIngestPipeline
from app.pipelines.video_pipeline import VideoIngestPipeline
from app.pipelines.link_pipeline import LinkIngestPipeline


def test_pipeline_factory_document():
    pipeline = PipelineFactory.get_pipeline("pdf")
    assert isinstance(pipeline, DocumentIngestPipeline)


def test_pipeline_factory_document_by_extension():
    for ext in ["docx", "doc", "txt", "md", "html", "pptx", "json"]:
        pipeline = PipelineFactory.get_pipeline(ext)
        assert isinstance(pipeline, DocumentIngestPipeline), f"failed for {ext}"


def test_pipeline_factory_excel():
    pipeline = PipelineFactory.get_pipeline("excel")
    assert isinstance(pipeline, ExcelIngestPipeline)


def test_pipeline_factory_image():
    pipeline = PipelineFactory.get_pipeline("png")
    assert isinstance(pipeline, ImageIngestPipeline)


def test_pipeline_factory_audio():
    for ext in ["audio", "mp3", "wav", "m4a", "ogg"]:
        pipeline = PipelineFactory.get_pipeline(ext)
        assert isinstance(pipeline, AudioIngestPipeline), f"failed for {ext}"


def test_pipeline_factory_video():
    pipeline = PipelineFactory.get_pipeline("mp4")
    assert isinstance(pipeline, VideoIngestPipeline)


def test_pipeline_factory_link():
    pipeline = PipelineFactory.get_pipeline("link")
    assert isinstance(pipeline, LinkIngestPipeline)


def test_pipeline_factory_unknown():
    assert PipelineFactory.get_pipeline("unknown_ext") is None


def test_document_pipeline_chunking():
    pipeline = DocumentIngestPipeline()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello world. " * 100)
        path = f.name

    chunks = pipeline.process(path, uuid4())
    assert len(chunks) > 0
    assert "content" in chunks[0]
    assert chunks[0]["modality"] == "text"
    # Metadata should be populated for text files
    assert "language" in chunks[0]["metadata"]
    os.unlink(path)


def test_document_pipeline_json():
    pipeline = DocumentIngestPipeline()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"key": "value", "list": [1, 2, 3]}')
        path = f.name

    chunks = pipeline.process(path, uuid4())
    assert len(chunks) > 0
    assert '"key": "value"' in chunks[0]["content"]
    os.unlink(path)


def test_document_pipeline_html():
    pipeline = DocumentIngestPipeline()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write("<html><head><title>Test</title></head><body>Hello</body></html>")
        path = f.name

    chunks = pipeline.process(path, uuid4())
    assert len(chunks) > 0
    assert "Hello" in chunks[0]["content"]
    assert chunks[0]["metadata"].get("title") == "Test"
    os.unlink(path)


def test_image_pipeline_without_ocr(monkeypatch):
    """When OCR dependencies are absent or disabled, image pipeline still returns a valid chunk."""
    pipeline = ImageIngestPipeline()

    # Create a tiny valid PNG (1x1 pixel)
    import base64
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_data)
        path = f.name

    chunks = pipeline.process(path, uuid4(), metadata={"description": "test image"})
    assert len(chunks) == 1
    assert chunks[0]["modality"] == "image"
    assert "test image" in chunks[0]["content"]
    os.unlink(path)


def test_audio_pipeline_placeholder():
    """When transcription dependencies are absent or disabled, audio pipeline returns a placeholder."""
    pipeline = AudioIngestPipeline()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"fake audio data")
        path = f.name

    chunks = pipeline.process(path, uuid4())
    assert len(chunks) == 1
    assert chunks[0]["modality"] == "audio"
    assert "[audio transcription disabled]" in chunks[0]["content"]
    assert chunks[0]["metadata"].get("format") == "mp3"
    os.unlink(path)
