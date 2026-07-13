import logging
import os
from typing import List, Dict, Any
from uuid import UUID
from app.pipelines.base import BaseIngestPipeline

logger = logging.getLogger(__name__)


class ImageIngestPipeline(BaseIngestPipeline):
    """处理图片：OCR 提取文本并抽取 EXIF 元数据。"""

    @property
    def supported_types(self) -> List[str]:
        return [
            "image",
            "jpg", "jpeg", "png", "gif",
            "webp", "bmp", "tiff", "tif",
        ]

    def process(
        self,
        file_path: str,
        doc_id: UUID,
        metadata: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        metadata = metadata or {}
        image_description = metadata.get("description") or "图片内容"

        ocr_text = self._extract_ocr(file_path)
        exif_metadata = self._extract_exif(file_path)

        content_parts = [image_description]
        if ocr_text and ocr_text != "[OCR disabled]":
            content_parts.extend(["[OCR_TEXT]", ocr_text, "[/OCR_TEXT]"])
        content = "\n".join(content_parts)

        merged_meta = {**metadata, **exif_metadata}

        return [{
            "content": content,
            "modality": "image",
            "chunk_index": 0,
            "position_info": {
                "type": "image",
                "file_name": os.path.basename(file_path),
                "original_path": file_path,
            },
            "metadata": merged_meta,
        }]

    def _extract_ocr(self, file_path: str) -> str:
        """使用 pytesseract 进行 OCR；开关关闭或依赖缺失时返回占位提示。"""
        if os.getenv("OCR_ENABLED", "true").lower() != "true":
            logger.warning("OCR is disabled by OCR_ENABLED=false for %s", file_path)
            return "[OCR disabled]"

        try:
            from PIL import Image
            import pytesseract

            image = Image.open(file_path)
            return pytesseract.image_to_string(image, lang="chi_sim+eng")
        except Exception as exc:
            logger.warning(
                "OCR dependencies missing or failed for %s: %s", file_path, exc
            )
            return "[OCR disabled]"

    def _extract_exif(self, file_path: str) -> Dict[str, Any]:
        """抽取图片 EXIF 元数据。"""
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS

            image = Image.open(file_path)
            exif = image._getexif()
            if not exif:
                return {}
            return {
                TAGS.get(tag_id, tag_id): str(value)
                for tag_id, value in exif.items()
            }
        except Exception:
            return {}
