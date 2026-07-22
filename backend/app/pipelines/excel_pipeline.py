"""通用 Excel 解析器

所有 Sheet 走同一套逻辑，不依赖 Sheet 名、不依赖具体列名。
自动处理：
- 合并单元格（openpyxl 前向填充）
- 合并标题行（如 SOP 文件）
- 稀疏型 Sheet（封面/修订记录 → 全文一个 chunk）
- 表格型 Sheet（规整表格 → 每行 "列名: 值"）
"""

import os
import re
from typing import List, Dict, Any, Tuple
from uuid import UUID
import pandas as pd
from app.pipelines.base import BaseIngestPipeline


class ExcelIngestPipeline(BaseIngestPipeline):
    """通用 Excel Pipeline：自适应任意结构的 Excel"""

    def __init__(self):
        super().__init__()
        # 内存缓存：path → (openpyxl.Workbook, mtime)
        # 同一个文件的所有 sheet 共享一个 Workbook 对象，避免反复 load_workbook
        # mtime 用于检测文件是否被覆盖更新，主动失效缓存
        self._wb_cache: Dict[str, Tuple["openpyxl.Workbook", float]] = {}

    @property
    def supported_types(self) -> List[str]:
        return ["excel", "xlsx", "xls", "csv"]

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def process(
        self,
        file_path: str,
        doc_id: UUID,
        metadata: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".csv":
            df = pd.read_csv(file_path, header=None).astype(object)
            df = self._normalize_dataframe(df)
            if not df.empty:
                strategy = self._classify_sheet(df)
                chunks = self._generate_chunks(df, strategy)
                for c in chunks:
                    c["metadata"]["sheet"] = "Sheet1"
                    c["metadata"]["strategy"] = strategy
            else:
                chunks = []
        else:
            excel_file = pd.ExcelFile(file_path)
            all_chunks = []
            try:
                for sheet_name in excel_file.sheet_names:
                    try:
                        df = self._normalize_sheet(file_path, sheet_name)
                        if df.empty:
                            continue
                        strategy = self._classify_sheet(df)
                        if strategy == "tabular":
                            merge_map = self._get_merge_map_in_clean_coords(file_path, sheet_name, df)
                            df = self._forward_fill_merges(df, merge_map)
                            df = self._normalize_dataframe(df)
                            if df.empty:
                                continue
                        chunks = self._generate_chunks(df, strategy)
                        for c in chunks:
                            c["metadata"]["sheet"] = sheet_name
                            c["metadata"]["strategy"] = strategy
                        all_chunks.extend(chunks)
                    except Exception as e:
                        # 单个 sheet 解析失败不影响其他 sheet
                        continue
            finally:
                self._close_wb_cache(file_path)
            chunks = all_chunks

        # 全局清洗 + 统一编号
        chunks = self._global_clean_chunks(chunks)
        # 统一 chunk_index：跨 sheet 全局递增，适配 chunk 级评测标注
        for seq, c in enumerate(chunks):
            c["chunk_index"] = seq
            if "chunk_index" in c.get("position_info", {}):
                c["position_info"]["chunk_index"] = seq
        merged_meta = {**(metadata or {}), "title": os.path.basename(file_path)}
        for c in chunks:
            c["metadata"] = {**c.get("metadata", {}), **merged_meta}
        return chunks

    # ------------------------------------------------------------------
    # Step 1: 归一化
    # ------------------------------------------------------------------

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """通用 DataFrame 归一化：去空行列 → 检测表头 → 提取列名。"""
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if df.empty:
            return df

        header_row_idx = self._detect_header_row(df)
        headers = df.iloc[header_row_idx].tolist()
        df.columns = [
            str(c).strip() if pd.notna(c) and str(c).strip() else f"Col_{i}"
            for i, c in enumerate(headers)
        ]
        df = df.iloc[header_row_idx + 1:].reset_index(drop=True)

        # 列名过长或含换行 → 回退到 Col_N
        for i in range(len(df.columns)):
            col = str(df.columns[i])
            if len(col) > 50 or '\n' in col:
                df.columns.values[i] = f"Col_{i}"

        # 全部是 Col_N 降级名 → 统一简化
        meaningful = [c for c in df.columns if not re.match(r'^Col_\d+$', c)]
        if not meaningful:
            for i in range(len(df.columns)):
                df.columns.values[i] = f"Col_{i}"

        df = df.fillna("")
        return df

    def _normalize_sheet(self, file_path: str, sheet_name: str) -> pd.DataFrame:
        """Excel sheet 归一化：读取 → 去空 → 标准归一化（不含 forward-fill）。"""
        df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        df = df.astype(object)
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if df.empty:
            return df
        df = self._normalize_dataframe(df)
        return df

    # ------------------------------------------------------------------
    # Workbook 缓存（复用 openpyxl 对象，减少磁盘 I/O）
    # ------------------------------------------------------------------

    def _load_wb_cache(self, file_path: str) -> "openpyxl.Workbook":
        """缓存版 load_workbook：同一文件只加载一次。

        每次调用前校验文件的修改时间（mtime），如果文件被覆盖更新，
        则主动关闭旧缓存并重新加载，确保不返回过期数据。
        """
        from openpyxl import load_workbook

        current_mtime = os.path.getmtime(file_path)
        cached = self._wb_cache.get(file_path)

        # 缓存命中且 mtime 未变 → 直接复用
        if cached is not None and cached[1] == current_mtime:
            return cached[0]

        # 缓存失效（未命中 / mtime 变了）→ 关闭旧的，重新加载
        if cached is not None:
            cached[0].close()

        wb = load_workbook(file_path, data_only=True)
        self._wb_cache[file_path] = (wb, current_mtime)
        return wb

    def _close_wb_cache(self, file_path: str) -> None:
        """弹出并关闭 Workbook，释放文件句柄和内存。

        在 process() 的 finally 块中调用，保证每个 process 调用
        最多持有 1 个文件缓存，不会随着调用次数累积。
        """
        cached = self._wb_cache.pop(file_path, None)
        if cached is not None:
            cached[0].close()

    # ------------------------------------------------------------------
    # 合并单元格处理
    # ------------------------------------------------------------------

    def _get_merge_map_in_clean_coords(
        self, file_path: str, sheet_name: str, clean_df: pd.DataFrame
    ) -> Dict[str, str]:
        """在 dropna 后的 DataFrame 上重建合并单元格映射。

        dropna 移除了全空行列，原始 openpyxl 坐标（1-indexed）与裁剪后
        的 DataFrame 坐标（0-indexed）不再对应。本方法只保留那些在
        clean_df 中仍存在的单元格，并映射到新的行列位置。
        """
        # clean_df 的 index/columns 保留了原始位置号（如 [1,2,4,...]）
        kept_rows = set(clean_df.index)
        kept_cols = set(clean_df.columns)
        row_pos = {orig: idx for idx, orig in enumerate(clean_df.index)}
        col_pos = {orig: idx for idx, orig in enumerate(clean_df.columns)}

        merge_map = {}
        try:
            wb = self._load_wb_cache(file_path)
            if sheet_name not in wb.sheetnames:
                return merge_map
            ws = wb[sheet_name]

            for merged_range in ws.merged_cells.ranges:
                top_left_val = ws.cell(merged_range.min_row, merged_range.min_col).value
                if top_left_val is None or (isinstance(top_left_val, str) and not top_left_val.strip()):
                    continue
                val = str(top_left_val).strip()
                if len(val) < 2:
                    continue
                # openpyxl 坐标转 0-indexed
                for r in range(merged_range.min_row, merged_range.max_row + 1):
                    orig_r = r - 1  # 转为 0-indexed（匹配 df 的原始行号）
                    if orig_r not in kept_rows:
                        continue
                    new_r = row_pos[orig_r]
                    for c in range(merged_range.min_col, merged_range.max_col + 1):
                        orig_c = c - 1
                        if orig_c not in kept_cols:
                            continue
                        new_c = col_pos[orig_c]
                        if orig_r == merged_range.min_row - 1 and orig_c == merged_range.min_col - 1:
                            continue  # 跳过左上角
                        merge_map[f"{new_r},{new_c}"] = val
        except Exception:
            pass
        return merge_map

    def _forward_fill_merges(self, df: pd.DataFrame, merge_map: Dict[str, str]) -> pd.DataFrame:
        """仅对合并区域内的空值做前向填充"""
        for r in range(len(df)):
            for c in range(len(df.columns)):
                key = f"{r},{c}"
                if key in merge_map:
                    # 只在单元格为空时填充
                    if pd.isna(df.iloc[r, c]) or str(df.iloc[r, c]).strip() == "":
                        df.iloc[r, c] = merge_map[key]
        return df

    # ------------------------------------------------------------------
    # 智能表头检测
    # ------------------------------------------------------------------

    def _detect_header_row(self, df: pd.DataFrame) -> int:
        """
        检测真正的表头行。

        策略：遍历前 15 行，找到第一个满足以下条件的行作为表头：
        1. 至少有 2 个非空单元格
        2. 非空单元格中短文本（2~30 字符）占比高
        3. 该行不是页码/版权行
        4. 下一行存在数据
        5. 该行不含多行单元格（\n 换行）

        如果找不到高质量的表头，返回 0 并让后续逻辑降级处理。
        """
        rows, cols = df.shape
        if rows == 0:
            return 0

        best_score = -1
        best_idx = 0

        for i in range(min(rows, 15)):
            non_empty = [(c, str(df.iloc[i, c]).strip()) for c in range(cols)
                         if pd.notna(df.iloc[i, c]) and str(df.iloc[i, c]).strip()]

            if len(non_empty) < 2:
                continue

            # 判据 1：是否包含多行单元格（\n 换行）→ 排除，这种通常是正文内容
            has_multiline = sum(1 for _, v in non_empty if '\n' in v)
            if has_multiline >= 1:
                continue

            # 判据 2：是否是页码/版权行
            first_vals = ' '.join(v for _, v in non_empty[:3]).lower()
            if any(kw in first_vals for kw in ['page', 'all rights', 'copyright', '第', '页']):
                continue

            # 判据 3：短文本比例（列名通常较短）
            short = sum(1 for _, v in non_empty if 2 <= len(v) <= 40)
            short_ratio = short / len(non_empty) if non_empty else 0

            # 判据 4：该行不全是数字
            number_count = sum(1 for _, v in non_empty if re.match(r'^[\d\s.,\-]+$', v))
            number_ratio = number_count / len(non_empty) if non_empty else 0

            # 判据 5：下一行有数据
            next_has_data = False
            if i + 1 < rows:
                next_non_empty = sum(1 for c in range(cols)
                                     if pd.notna(df.iloc[i + 1, c]) and str(df.iloc[i + 1, c]).strip())
                next_has_data = next_non_empty >= 2

            score = 0
            if short_ratio >= 0.5:
                score += 2
            if next_has_data:
                score += 2
            if number_ratio < 0.3:
                score += 1
            if short_ratio >= 0.8:
                score += 1  # 全是短文本 → 强信号

            if score > best_score:
                best_score = score
                best_idx = i

        return best_idx if best_score >= 3 else 0

    # ------------------------------------------------------------------
    # Step 2: 自动分类
    # ------------------------------------------------------------------

    def _classify_sheet(self, df: pd.DataFrame) -> str:
        """
        根据数据特征自动分类。
        - 'sparse': 封面、修订记录等 → 整页全文提取
        - 'tabular': 规整表格 → 每行 "列名: 值"
        """
        rows, cols = df.shape
        if rows == 0 or cols == 0:
            return "sparse"

        # 总非空单元格比例
        total_cells = rows * cols
        non_empty = sum(1 for r in range(rows) for c in range(cols)
                        if pd.notna(df.iloc[r, c]) and str(df.iloc[r, c]).strip())
        density = non_empty / total_cells if total_cells > 0 else 0

        # 特征 A：行数 ≤ 3 或密度极低 → 稀疏型
        if rows <= 3 or density < 0.15:
            return "sparse"

        # 特征 B：列名是否有明确含义（非 Col_N 模式）
        col_names = list(df.columns)
        auto_col_ratio = sum(1 for c in col_names if re.match(r'^Col_\d+$', c)) / len(col_names)

        if auto_col_ratio > 0.5:
            return "sparse"

        # 默认：表格型
        return "tabular"

    # ------------------------------------------------------------------
    # Step 3: 生成 Chunks
    # ------------------------------------------------------------------

    def _generate_chunks(self, df: pd.DataFrame, strategy: str) -> List[Dict[str, Any]]:
        if strategy == "sparse":
            return self._generate_sparse(df)
        else:
            return self._generate_tabular(df)

    def _generate_sparse(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """稀疏型：整页一个 chunk，用自然语言拼接，行内+行间去重。

        forward-fill 会把合并单元格的值填到多列，导致同一行里
        相同内容重复出现。去重逻辑：先列内去重（保留顺序），
        再行间去重。
        """
        text_parts = []
        seen_rows: set = set()
        seen_core: set = set()
        for idx, row in df.iterrows():
            # 1. 列内去重
            row_parts = []
            seen_cols: set = set()
            for col in df.columns:
                val = str(row[col]).strip()
                if val and val not in ("NaT", "nan", "") and val not in seen_cols:
                    seen_cols.add(val)
                    row_parts.append(val)
            if not row_parts:
                continue
            # 2. 行间去重
            cur_text = " ".join(row_parts)
            if cur_text in seen_rows:
                continue
            seen_rows.add(cur_text)
            # 3. 规范化去重（去掉 "All rights reserved" 前缀再比）
            core = cur_text
            if core.startswith("All rights reserved"):
                core = core[len("All rights reserved"):].strip()
            if core and core in seen_core:
                continue
            if core:
                seen_core.add(core)
            text_parts.append(cur_text)
        text = "\n".join(text_parts)
        if not text.strip():
            return []
        return [{
            "content": text,
            "modality": "table",
            "chunk_index": 0,
            "position_info": {"type": "excel_sparse", "chunk_index": 0},
            "metadata": {},
        }]

    def _generate_tabular(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """表格型：按字符窗口合并行，每行输出 '列名: 值' 格式。

        不按"一行一 chunk"硬切，而是在 500~1500 字符范围内
        动态合并连续行，保证 chunk 语义完整且大小均匀。
        """
        TARGET_MIN = 500
        TARGET_MAX = 1500

        def row_to_text(row) -> str:
            parts = []
            for col in df.columns:
                val = str(row[col]).strip()
                if val and val not in ("NaT", "nan", ""):
                    col_name = str(col)
                    if re.match(r'^Col_\d+$', col_name):
                        parts.append(val)
                    else:
                        parts.append(f"{col_name}: {val}")
            return "; ".join(parts) if parts else ""

        def flush_buffer(buf: list) -> dict:
            rows_idx = [r for r, _ in buf]
            merged = "\n".join(t for _, t in buf)
            return {
                "content": merged,
                "modality": "table",
                "chunk_index": rows_idx[0],
                "position_info": {
                    "type": "excel_tabular",
                    "row_start": rows_idx[0],
                    "row_end": rows_idx[-1],
                    "chunk_index": rows_idx[0],
                },
                "metadata": {"row_index": rows_idx[0], "row_count": len(buf)},
            }

        chunks = []
        buffer: list[tuple[int, str]] = []
        buffer_len = 0

        for idx, row in df.iterrows():
            text = row_to_text(row)
            if not text or len(text) < 10:
                continue
            if buffer_len + len(text) > TARGET_MAX and buffer:
                chunks.append(flush_buffer(buffer))
                buffer, buffer_len = [], 0
            buffer.append((int(idx), text))
            buffer_len += len(text)
            if buffer_len >= TARGET_MIN:
                chunks.append(flush_buffer(buffer))
                buffer, buffer_len = [], 0

        if buffer:
            chunks.append(flush_buffer(buffer))
        return chunks

    # ------------------------------------------------------------------
    # 全局清洗
    # ------------------------------------------------------------------

    def _global_clean_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去除残留的解析噪音"""
        noise_patterns = [
            r'Col_\d+:\s*NaT',
            r'Col_\d+:\s*$',
            r'dtype:\s*\w+',
            r'Name:\s*\d+\s*,?\s*',
        ]
        cleaned = []
        for c in chunks:
            content = c["content"]
            for pat in noise_patterns:
                content = re.sub(pat, "", content)
            content = re.sub(r' {2,}', " ", content)
            content = re.sub(r'\n{3,}', "\n\n", content)
            content = content.strip()
            if not content or len(content) < 10:
                continue
            c["content"] = content
            cleaned.append(c)
        return cleaned
