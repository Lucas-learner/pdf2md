"""
结果合并模块

将多页识别结果合并为完整的Markdown文档。
支持两种模式：
1. 简单拼接模式：传统逐页拼接（保留向后兼容）
2. 智能重构模式：调用LLM全局理解并重构为报告格式（推荐）
"""

import os
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass

from vision_recognizer import RecognitionResult
from content_reorganizer import ContentReorganizer, ReorganizeConfig


@dataclass
class MergeConfig:
    """合并配置"""
    add_page_separator: bool = True  # 简单模式下是否添加分页分隔线
    remove_duplicate_headers: bool = True  # 去除重复页眉
    merge_broken_paragraphs: bool = True  # 合并跨页断开的段落
    add_toc: bool = False  # 是否添加目录
    enable_reorganize: bool = True  # 是否启用智能重构（核心改进）
    reorganize_config: Optional[ReorganizeConfig] = None  # 重构配置
    chapter_keywords: Optional[List[str]] = None  # 章节标题关键词（默认FA/投行报告常用章节）


class ResultMerger:
    """结果合并器"""

    def __init__(self, config: Optional[MergeConfig] = None):
        self.config = config or MergeConfig()

    def merge(
        self,
        results: List[RecognitionResult],
        pdf_path: Path,
        title: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "kimi-coding",
        high_risk_pages: Optional[List[int]] = None,
        fatal_pages: Optional[List[int]] = None,
        skip_reorganize_note: Optional[str] = None,
    ) -> str:
        """
        合并识别结果为完整Markdown

        Args:
            results: 各页识别结果列表
            pdf_path: 原始PDF路径
            title: 文档标题，默认使用PDF文件名
            api_key: API Key（智能重构模式需要）
            base_url: API基础URL
            model: 使用的模型
            high_risk_pages: 内容安全审核未通过的页码列表
            fatal_pages: 致命错误（无法恢复）的页码列表
            skip_reorganize_note: 跳过重构的原因说明

        Returns:
            完整Markdown字符串
        """
        # 过滤失败结果
        successful_results = [r for r in results if r.success]
        failed_pages = [r.page_num for r in results if not r.success]

        # 文档标题
        doc_title = title or pdf_path.stem

        # 判断是否启用智能重构
        if self.config.enable_reorganize and len(successful_results) > 0:
            try:
                if not api_key:
                    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or \
                              os.environ.get("KIMI_API_KEY")

                if api_key:
                    print("\n  🧠 正在智能重构文档结构...")
                    reorganizer = ContentReorganizer(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                    )

                    pages = [(r.page_num, r.markdown) for r in successful_results]
                    reorganize_config = self.config.reorganize_config or ReorganizeConfig()

                    markdown = reorganizer.reorganize(
                        pages=pages,
                        doc_title=doc_title,
                        config=reorganize_config,
                    )

                    # 后处理清理
                    markdown = reorganizer.post_cleanup(markdown, reorganize_config)

                    # 添加转换信息头部（在智能重构后）
                    markdown = self._add_conversion_header(
                        markdown, pdf_path, len(results), len(successful_results),
                        failed_pages, mode="智能重构",
                        high_risk_pages=high_risk_pages,
                        fatal_pages=fatal_pages,
                        skip_reorganize_note=skip_reorganize_note,
                    )

                    return markdown
                else:
                    print("\n  ⚠️  未提供API Key，跳过智能重构，使用简单拼接模式")
            except Exception as e:
                print(f"\n  ⚠️  智能重构失败: {e}，降级为简单拼接模式")

        # 简单拼接模式（向后兼容）
        return self._simple_merge(
            successful_results, failed_pages, pdf_path, doc_title,
            high_risk_pages=high_risk_pages,
            fatal_pages=fatal_pages,
            skip_reorganize_note=skip_reorganize_note,
        )

    def _simple_merge(
        self,
        successful_results: List[RecognitionResult],
        failed_pages: List[int],
        pdf_path: Path,
        doc_title: str,
        high_risk_pages: Optional[List[int]] = None,
        fatal_pages: Optional[List[int]] = None,
        skip_reorganize_note: Optional[str] = None,
    ) -> str:
        """简单拼接模式（传统方式）"""
        # 构建文档头部
        lines = [
            f"# {doc_title}",
            "",
            "> **转换信息**",
            f"> - 源文件：{pdf_path.name}",
            f"> - 总页数：{len(successful_results) + len(failed_pages)}",
            f"> - 成功识别：{len(successful_results)}页",
        ]

        if high_risk_pages:
            lines.append(f"> - 内容安全未通过：第{', '.join(map(str, high_risk_pages))}页")
        if fatal_pages:
            lines.append(f"> - 致命错误未识别：第{', '.join(map(str, fatal_pages))}页")
        if skip_reorganize_note:
            lines.append(f"> - ⚠️ {skip_reorganize_note}")

        lines.extend([
            f"> - 转换时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "---",
            "",
        ])

        # 合并各页内容
        for i, result in enumerate(successful_results):
            if self.config.add_page_separator and i > 0:
                lines.extend(["", "---", ""])

            # 处理页面内容
            page_content = self._process_page_content(result.markdown, result.page_num)
            lines.append(page_content)

        return "\n".join(lines)

    def _add_conversion_header(
        self,
        markdown: str,
        pdf_path: Path,
        total_pages: int,
        success_pages: int,
        failed_pages: List[int],
        mode: str = "智能重构",
        high_risk_pages: Optional[List[int]] = None,
        fatal_pages: Optional[List[int]] = None,
        skip_reorganize_note: Optional[str] = None,
    ) -> str:
        """添加转换信息头部"""
        header_lines = [
            f"> **转换信息**",
            f"> - 源文件：{pdf_path.name}",
            f"> - 总页数：{total_pages}",
            f"> - 成功识别：{success_pages}页",
            f"> - 处理模式：{mode}",
        ]

        if high_risk_pages:
            header_lines.append(f"> - 内容安全未通过：第{', '.join(map(str, high_risk_pages))}页")
        if fatal_pages:
            header_lines.append(f"> - 致命错误未识别：第{', '.join(map(str, fatal_pages))}页")
        if skip_reorganize_note:
            header_lines.append(f"> - ⚠️ {skip_reorganize_note}")

        header_lines.extend([
            f"> - 转换时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "---",
            "",
        ])

        header = "\n".join(header_lines)

        # 如果文档已有主标题，将转换信息插入到标题之后
        if markdown.startswith("# "):
            # 找到第一个标题后的位置
            title_end = markdown.find('\n')
            if title_end > 0:
                # 跳过标题后的空行
                content_start = title_end + 1
                while content_start < len(markdown) and markdown[content_start] == '\n':
                    content_start += 1
                return markdown[:content_start] + header + markdown[content_start:]

        return header + markdown

    def _process_page_content(self, content: str, page_num: int) -> str:
        """处理单页内容"""
        # 去除多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        # 确保表格格式正确
        content = self._fix_table_format(content)

        # 简单的章节标题规范化
        content = self._normalize_chapter_titles(content)

        return content.strip()

    def _normalize_chapter_titles(self, content: str) -> str:
        """
        规范化章节标题：将6大章节标题统一为二级标题格式
        只处理页面顶部的标题（前3行）
        """
        lines = content.split('\n')
        if not lines:
            return content

        # 章节关键词（可配置，默认覆盖FA/投行报告常用章节）
        chapter_keywords = self.config.chapter_keywords or [
            '项目概括', '行业概况', '公司介绍', '技术与产品', '项目访谈', '财务与投资'
        ]

        # 只处理前3行
        for i in range(min(3, len(lines))):
            stripped = lines[i].strip()

            # 跳过已经是二级标题的行
            if stripped.startswith('## '):
                continue

            # 检查是否是6大章节标题（纯文本或粗体格式）
            for keyword in chapter_keywords:
                # 纯文本匹配
                if stripped == keyword or stripped.startswith(keyword + ' '):
                    lines[i] = f'## {stripped}'
                    break
                # 粗体格式匹配: **关键词**
                if stripped == f'**{keyword}**' or stripped.startswith(f'**{keyword}'):
                    lines[i] = f'## {keyword}'
                    break

        return '\n'.join(lines)

    def _fix_table_format(self, content: str) -> str:
        """修复表格格式问题"""
        lines = content.split('\n')
        result = []
        in_table = False
        table_lines = []

        for line in lines:
            # 检测表格行（包含 | 的行）
            if '|' in line:
                in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    # 处理表格结束
                    result.extend(self._format_table_lines(table_lines))
                    table_lines = []
                    in_table = False
                result.append(line)

        # 处理文档末尾的表格
        if table_lines:
            result.extend(self._format_table_lines(table_lines))

        return '\n'.join(result)

    def _format_table_lines(self, lines: List[str]) -> List[str]:
        """格式化表格行"""
        if not lines:
            return []

        # 解析表格
        rows = []
        for line in lines:
            # 分割单元格
            cells = [cell.strip() for cell in line.split('|')]
            # 去除首尾空单元格
            cells = cells[1:-1] if cells[0] == '' and cells[-1] == '' else cells
            if cells:
                rows.append(cells)

        if not rows:
            return lines

        # 检查是否有分隔行（包含 :--- 的行）
        has_separator = False
        for row in rows:
            if all('-' in cell or ':' in cell for cell in row):
                has_separator = True
                break

        # 如果没有分隔行，在第1行后添加
        if not has_separator and len(rows) >= 1:
            separator = [':---'] * len(rows[0])
            rows.insert(1, separator)

        # 重新构建表格
        result = []
        for row in rows:
            result.append('| ' + ' | '.join(row) + ' |')

        return result

    def save(
        self,
        markdown: str,
        output_path: Path,
        encoding: str = "utf-8",
    ) -> Path:
        """
        保存Markdown到文件

        Args:
            markdown: Markdown内容
            output_path: 输出文件路径
            encoding: 文件编码

        Returns:
            保存的文件路径
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding=encoding) as f:
            f.write(markdown)

        return output_path
