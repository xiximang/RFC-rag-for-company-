from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from uuid import UUID
import re


class BaseIngestPipeline(ABC):
    """文档摄取Pipeline抽象基类。返回dict列表，字段：
    content, modality, chunk_index, position_info, metadata
    """

    @property
    @abstractmethod
    def supported_types(self) -> List[str]:
        """支持的文件类型列表"""
        pass

    def can_process(self, file_type: str) -> bool:
        return file_type in self.supported_types

    @abstractmethod
    def process(
        self,
        file_path: str,
        doc_id: UUID,
        metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        pass

    # =====================================================================
    # 文本清洗（所有子类自动继承）
    # 2026-07-08: 新增保守型文本清洗，只处理确定性噪声
    # =====================================================================

    def _clean_text(self, text: str) -> str:
        """保守型文本清洗。只处理确定性的噪声，不碰模糊的。"""
        if not text:
            return text

        # 步骤1: 保护表格区域
        text, table_blocks = self._protect_tables(text)

        # 步骤2: 删除确定性噪声
        text = self._dedup_chinese(text)               # 为为保保证证 → 为保证
        text = self._remove_page_placeholders(text)     # Page<number>、--- 第X页 ---
        text = self._merge_hyphen_newlines(text)        # 孤连字符换行 (\w)-\n(\w)
        text = self._fix_control_chars(text)            # \x0B → \n
        # text = self._remove_toc_dots(text)              # 目录点号 ......1 → 空

        # 步骤3: 规范化空白
        text = self._normalize_whitespace(text)         # 3+换行→2换行, 多空格→1空格

        # 步骤4: 还原表格
        text = self._restore_tables(text, table_blocks)

        return text

    def _protect_tables(self, text: str) -> Tuple[str, Dict[str, str]]:
        """提取 [TABLE]...[/TABLE] 块替换为占位符，空表格直接丢弃"""
        table_blocks: Dict[str, str] = {}
        counter = [0]  # 用列表避免 nonlocal

        def _replace(match: re.Match) -> str:
            full = match.group(0)
            # 检查是否为空表格
            inner = full.replace('[TABLE]', '').replace('[/TABLE]', '')
            inner_clean = inner.replace('|', '').replace('\n', '').strip()
            if not inner_clean:
                return ''
            key = f'<<TABLE_{counter[0]}>>'
            table_blocks[key] = full
            counter[0] += 1
            return '\n' + key + '\n'

        cleaned = re.sub(r'\[TABLE\].*?\[/TABLE\]', _replace, text, flags=re.DOTALL)
        return cleaned, table_blocks

    def _dedup_chinese(self, text: str) -> str:
        """修复 PDF 文本层乱码：为为保保证证 → 为保证"""
        return re.sub(r'([一-鿿])\1+', r'\1', text)

    def _remove_page_placeholders(self, text: str) -> str:
        """删除 Page 占位符和 PPT 页码标记"""
        text = re.sub(r'Page\s*<number>', '', text)
        text = re.sub(r'--- 第\d+页 ---', '', text)
        text = re.sub(r'^\s*<number>\s*$', '', text, flags=re.MULTILINE)
        return text

    def _merge_hyphen_newlines(self, text: str) -> str:
        """合并被硬换行切断的连字符：POE35-\n54A → POE35-54A"""
        return re.sub(r'(\w)-\n(\w)', r'\1-\2', text)

    def _fix_control_chars(self, text: str) -> str:
        """\x0B (PPT 列表分隔符) → 换行"""
        return text.replace('\x0B', '\n')

    # def _remove_toc_dots(self, text: str) -> str:
    #     """清除目录点号：标题......页码 → 标题（保留）。

    #     目录行常见格式：条目文本 + 连续10个以上的点号 + 页码。
    #     只清除点号与页码，保留条目文本。如果一行只有点号则整行删除。
    #     """
    #     if not text:
    #         return text

    #     lines = text.split('\n')
    #     cleaned = []
    #     for line in lines:
    #         stripped = line.strip()
    #         # 整行全是点号 → 跳过
    #         if stripped and stripped.replace('.', '').strip() == '':
    #             continue
    #         # 清除行尾的点号+页码（连续10+个点号）
    #         cleaned_line = re.sub(r'[.]{10,}\s*\d*\s*$', '', line)
    #         # 清除行尾的点号（连续10+个点号后无数字的情况）
    #         cleaned_line = re.sub(r'[.]{10,}\s*$', '', cleaned_line)
    #         cleaned.append(cleaned_line)
    #     return '\n'.join(cleaned)

    def _normalize_whitespace(self, text: str) -> str:
        """3+连续换行 → 2换行, 2+连续空格 → 1空格, 去首尾"""
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()

    def _restore_tables(self, text: str, table_blocks: Dict[str, str]) -> str:
        """将占位符还原为原始表格内容"""
        for key, value in table_blocks.items():
            text = text.replace(key, value)
        return text
