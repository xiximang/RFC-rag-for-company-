import logging
import os
from typing import List, Dict, Any, Tuple
from uuid import UUID
from app.pipelines.base import BaseIngestPipeline

logger = logging.getLogger(__name__)


class AudioIngestPipeline(BaseIngestPipeline):
    """处理音频文件（mp3/wav/m4a/ogg 等），返回语音识别转录文本。"""

    @property
    def supported_types(self) -> List[str]:
        return [
            "audio",
            "mp3", "wav", "m4a", "ogg",
            "flac", "aac", "wma",
        ]

    def process(
        self,
        file_path: str,
        doc_id: UUID,
        metadata: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        metadata = metadata or {}
        transcript, audio_metadata = self._transcribe(file_path)

        merged_meta = {**metadata, **audio_metadata}

        return [{
            "content": transcript or "[音频转录失败]",
            "modality": "audio",
            "chunk_index": 0,
            "position_info": {
                "type": "audio",
                "file_name": os.path.basename(file_path),
                "original_path": file_path,
            },
            "metadata": merged_meta,
        }]

    def _transcribe(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """优先使用 Whisper 转录，回退到 speech_recognition，开关关闭或依赖缺失时返回占位提示。"""
        ext = os.path.splitext(file_path)[1].lower()
        audio_metadata = {
            "format": ext.lstrip("."),
            "duration_seconds": self._get_duration(file_path),
        }

        if os.getenv("AUDIO_TRANSCRIPTION_ENABLED", "true").lower() != "true":
            logger.warning(
                "Audio transcription is disabled by AUDIO_TRANSCRIPTION_ENABLED=false for %s",
                file_path,
            )
            return "[audio transcription disabled]", audio_metadata

        # TODO: 本地私有化部署时建议优先使用 faster-whisper / whisper.cpp 以降低资源占用。
        try:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(file_path)
            audio_metadata["duration_seconds"] = result.get(
                "duration", audio_metadata["duration_seconds"]
            )
            return result.get("text", ""), audio_metadata
        except Exception as exc:
            # Whisper 未安装或加载失败，继续回退。
            logger.debug("Whisper transcription failed for %s: %s", file_path, exc)

        # speech_recognition 仅原生支持 WAV；其他格式需配合 pydub 转换。
        if ext == ".wav":
            try:
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                with sr.AudioFile(file_path) as source:
                    audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data, language="zh-CN")
                return text, audio_metadata
            except Exception as exc:
                logger.debug("speech_recognition fallback failed for %s: %s", file_path, exc)

        logger.warning(
            "Audio transcription dependencies missing or failed for %s", file_path
        )
        return "[audio transcription disabled]", audio_metadata

    def _get_duration(self, file_path: str) -> Any:
        """使用 mutagen 获取音频时长，未安装时返回 None。"""
        try:
            from mutagen import File
            audio = File(file_path)
            if audio and audio.info:
                return audio.info.length
        except Exception:
            pass
        return None
