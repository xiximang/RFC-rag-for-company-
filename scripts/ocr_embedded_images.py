"""独立脚本：对 PDF 中的嵌入图片做 OCR，将识别文字追加到 PostgreSQL 已有 chunk 中。

用法:
    python3 scripts/ocr_embedded_images.py <kb_id> <doc_id>

不会删除任何数据，只做 UPDATE 追加内容。
"""
import os, sys, logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────
PG_URL = os.environ.get("DATABASE_URL", "postgresql://rag_user:rag_password@localhost:5432/rag_kb")
OCR_ENABLED = os.environ.get("OCR_ENABLED", "true").lower() == "true"

if not OCR_ENABLED:
    log.error("OCR_ENABLED=false，退出")
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        log.error("用法: python3 scripts/ocr_embedded_images.py <kb_id> <doc_id>")
        sys.exit(1)

    kb_id = sys.argv[1]
    doc_id = sys.argv[2]

    # ── 1. 从数据库拿文档信息 ──
    import psycopg2

    conn = psycopg2.connect(PG_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(
        "SELECT storage_key, filename FROM documents WHERE id = %s AND kb_id = %s",
        (doc_id, kb_id),
    )
    row = cur.fetchone()
    if not row:
        log.error(f"文档 {doc_id} 在知识库 {kb_id} 中不存在")
        sys.exit(1)

    storage_key, filename = row
    log.info(f"文档: {filename}")
    log.info(f"storage_key: {storage_key}")

    # ── 2. 从 MinIO 下载 PDF 到临时文件 ──
    from minio import Minio

    MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "rag-documents")

    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    local_path = f"/tmp/ocr_{doc_id}.pdf"

    try:
        client.fget_object(MINIO_BUCKET, storage_key, local_path)
    except Exception as e:
        # 可能文件不存在（比如 storage_key 在旧版本 MinIO 或直连存储）
        log.warning(f"MinIO 下载失败 ({e})，检查本地 samples 目录...")
        local_path = f"/home/root1/tjy/RFC-rag-for-company-/samples_2/{filename}"
        if not Path(local_path).exists():
            log.error(f"本地文件也不存在: {local_path}")
            sys.exit(1)

    log.info(f"PDF 已就绪: {local_path}")

    # ── 3. 遍历每一页，找出有嵌入图片的页 ──
    import pdfplumber
    import pytesseract
    from pdf2image import convert_from_path

    pdf = pdfplumber.open(local_path)
    total_pages = len(pdf.pages)
    log.info(f"总页数: {total_pages}")

    conn.commit()  # 关闭当前事务，后续 UPDATE 用新事务

    updated_count = 0

    for page_idx in range(total_pages):
        page = pdf.pages[page_idx]
        images = page.images

        if not images:
            continue

        # 过滤：至少有一张 ≥50×50 的图片才处理
        valid_images = [img for img in images if img.get("width", 0) >= 50 and img.get("height", 0) >= 50]
        if not valid_images:
            continue

        log.info(f"第 {page_idx + 1} 页: {len(valid_images)} 张图片")

        # 渲染页面
        try:
            page_img = convert_from_path(local_path, first_page=page_idx + 1, last_page=page_idx + 1, dpi=100)[0]
        except Exception as e:
            log.warning(f"  渲染失败: {e}")
            continue

        ocr_parts = []
        for img_idx, img in enumerate(valid_images):
            try:
                bbox = (int(img["x0"]), int(img["top"]), int(img["x1"]), int(img["bottom"]))
                cropped = page_img.crop(bbox)
                text = pytesseract.image_to_string(cropped, lang="chi_sim+eng")
                if text and text.strip():
                    ocr_parts.append(f"[IMG_P{page_idx + 1}_{img_idx + 1}]\n{text.strip()}\n[/IMG]")
                    log.info(f"  图片 {img_idx + 1}: OCR 成功 ({len(text.strip())} 字符)")
            except Exception as e:
                log.warning(f"  图片 {img_idx + 1} OCR 失败: {e}")

        if not ocr_parts:
            continue

        ocr_text = "\n".join(ocr_parts)

        # ── 4. 找到该页对应的 chunk，追加 OCR 文字 ──
        # 用 chunk_index 近似定位（页面内容通常对应接近的 chunk_index）
        # 先找 chunk_index 附近且 content 中有该页特征的 chunk
        cur = conn.cursor()

        # 尝试1：找 content 中包含该页页码标记的 chunk
        page_marker = f"第 {page_idx + 1} 页"
        cur.execute(
            """SELECT id, chunk_index, length(content) as clen
               FROM chunks c JOIN documents d ON c.doc_id = d.id
               WHERE d.id = %s AND d.kb_id = %s
               AND c.content LIKE %s
               ORDER BY c.chunk_index LIMIT 1""",
            (doc_id, kb_id, f"%{page_marker}%"),
        )
        row = cur.fetchone()

        if not row:
            # 尝试2：取最接近 page_idx 的 chunk_index
            cur.execute(
                """SELECT id, chunk_index, length(content) as clen
                   FROM chunks c JOIN documents d ON c.doc_id = d.id
                   WHERE d.id = %s AND d.kb_id = %s
                   ORDER BY abs(c.chunk_index - %s) LIMIT 1""",
                (doc_id, kb_id, page_idx),
            )
            row = cur.fetchone()

        if row:
            chunk_id, chunk_idx, clen = row
            cur.execute(
                "UPDATE chunks SET content = content || %s || %s WHERE id = %s",
                ("\n\n", ocr_text, chunk_id),
            )
            conn.commit()
            updated_count += 1
            log.info(f"  → 更新 chunk {chunk_idx} (id={chunk_id[:12]}...) 成功")
        else:
            log.warning(f"  → 未找到对应 chunk，跳过")

    pdf.close()
    conn.close()

    log.info(f"\n完成: {updated_count} 个 chunk 已更新 OCR 文字")
    log.info(f"注意: 已追加到 content 字段，但 content_tsv 全文索引未更新")
    log.info(f"      需要运行: UPDATE chunks SET content_tsv = to_tsvector('chinese', content) WHERE id IN (...)")


if __name__ == "__main__":
    main()
