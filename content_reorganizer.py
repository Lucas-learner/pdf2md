"""
内容重构模块

将多页PDF的逐页识别结果，通过LLM全局理解后重构为结构化的报告格式。

核心能力：
- 去除重复页眉页脚
- 合并跨页段落
- 识别章节结构并重新组织
- 去除过渡页/装饰页
- 完全保留原文内容
"""

import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import anthropic
except ImportError:
    raise ImportError("请安装anthropic SDK: python3 -m pip install anthropic")


@dataclass
class ReorganizeConfig:
    """重构配置"""
    max_pages_per_batch: int = 25  # 每批处理的目标页数
    enable_reorganize: bool = True  # 是否启用重构
    preserve_page_markers: bool = False  # 是否保留页码标记
    remove_footer_patterns: List[str] = None  # 额外的页脚匹配模式


class ContentReorganizer:
    """内容重构器 - 使用LLM全局理解文档结构"""

    # 重构提示词模板
    REORGANIZE_PROMPT = """你是一位资深的文档编辑与结构分析师。你的任务是将多页PDF的逐页识别结果，整理为一份结构清晰、格式规范的报告文档。

## 输入格式
以下内容是PDF各页的原始识别结果，用 `<!-- PAGE: N -->` 标记分页：

{pages_content}

---

## 整理要求（极其重要）

### 1. 完整保留内容（最高优先级）
- **严禁删减、修改、概括任何原文内容**
- 所有文字、数字、百分比、金额、日期、人名、公司名必须原样保留
- 所有表格数据必须完整保留，不得合并行或列
- 所有列表项必须逐条保留，不得合并
- 保留原文的粗体 `**text**`、斜体 `*text*` 等格式标记

### 2. 去除重复装饰信息
- 删除每页重复的页眉、页脚（如FA机构名称、"保密"水印、页码等）
- 删除纯装饰性的公司Logo文字（如每页底部重复的"XX资本"）
- 删除空白的过渡页内容

### 3. 合并跨页内容
- 如果一个段落、列表项或表格在页底被截断、在下一页继续，必须合并为完整内容
- 合并后去除分页痕迹，让内容自然衔接

### 4. 构建报告结构
- 分析文档逻辑，将其组织为清晰的章节层级
- 使用 Markdown 标题层级：`#` 文档标题、`##` 大章节、`###` 小章节、`####` 子项
- 过渡页上的章节标题应成为对应正文部分的章节标题
- 目录页（如有）可去除或简化为文首说明
- 保持合理的标题层级关系，不要所有标题都用同一级别

### 5. 格式规范
- 表格：使用标准Markdown表格格式，必须有表头分隔行 `|:---|:---|`
- 列表：无序列表用 `- `，有序列表用 `1. `、`2. `
- 引用：原文中的注释/说明可用 `> ` 引用块
- 流程图：保留为代码块或Mermaid语法
- 空行：段落之间用空行分隔，但不要用过多空行

## 输出要求

1. 只输出整理后的Markdown内容，不要添加"以下是整理结果"等说明文字
2. 文档开头使用单个 `# ` 作为主标题
3. 不要在末尾添加总结性段落
4. 保持内容的专业性和可读性
"""

    # 长文档分块重构的摘要提示词
    SUMMARY_PROMPT = """请对以下PDF页面识别结果进行结构摘要，提取：
1. 本章节的主题/标题
2. 包含的主要小节标题
3. 关键内容概述（简要，用于上下文衔接）
4. 是否有跨页未完结的内容

输入内容：
{content}

请用简洁的结构化格式输出。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "kimi-coding",
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("需要提供API Key（ANTHROPIC_AUTH_TOKEN 或 KIMI_API_KEY）")

        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.kimi.com/coding/"
        self.model = model

        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def reorganize(
        self,
        pages: List[Tuple[int, str]],
        doc_title: str,
        config: Optional[ReorganizeConfig] = None,
    ) -> str:
        """
        将多页识别结果重构为报告格式

        Args:
            pages: [(页码, 页面markdown内容), ...]
            doc_title: 文档标题
            config: 重构配置

        Returns:
            重构后的Markdown字符串
        """
        config = config or ReorganizeConfig()

        if not config.enable_reorganize or not pages:
            # 不启用重构时，简单拼接
            return self._simple_join(pages, doc_title)

        # 准备带页码标记的内容
        pages_content = self._prepare_pages_content(pages)

        # 判断是否需要分块处理
        total_pages = len(pages)
        if total_pages <= config.max_pages_per_batch:
            # 短文档：直接全文重构
            return self._reorganize_single_batch(pages_content, doc_title)
        else:
            # 长文档：分块重构
            return self._reorganize_in_batches(pages, doc_title, config)

    def _prepare_pages_content(self, pages: List[Tuple[int, str]]) -> str:
        """准备带页码标记的页面内容"""
        parts = []
        for page_num, content in pages:
            parts.append(f"<!-- PAGE: {page_num} -->")
            parts.append(content.strip())
            parts.append("")
        return "\n\n".join(parts)

    def _simple_join(self, pages: List[Tuple[int, str]], doc_title: str) -> str:
        """简单拼接（不启用重构时）"""
        lines = [f"# {doc_title}", ""]
        for _, content in pages:
            lines.append(content.strip())
            lines.append("")
        return "\n\n".join(lines)

    def _reorganize_single_batch(self, pages_content: str, doc_title: str) -> str:
        """单批次重构（适合短文档）"""
        prompt = self.REORGANIZE_PROMPT.format(pages_content=pages_content)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=32768,
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                stream=True,
            )

            # 收集 streaming 响应中的文本
            result = ""
            for chunk in response:
                if chunk.type == "content_block_delta":
                    if hasattr(chunk.delta, "text") and chunk.delta.text:
                        result += chunk.delta.text

            result = result.strip()

            # 清理可能的代码块标记
            result = self._clean_code_block_markers(result)

            # 确保有文档标题
            if not result.startswith("# "):
                result = f"# {doc_title}\n\n{result}"

            return result

        except Exception as e:
            print(f"  ⚠️  重构失败: {e}，降级为简单拼接")
            return self._simple_join_from_content(pages_content, doc_title)

    def _reorganize_one_batch(
        self,
        idx: int,
        batch: List[Tuple[int, str]],
        doc_title: str,
        total_batches: int,
        retry_count: int = 2,
    ) -> Tuple[int, str]:
        """
        重构单批次，支持限流重试
        
        Returns:
            (batch_idx, result_text)
        """
        start_page = batch[0][0]
        end_page = batch[-1][0]
        print(f"  正在重构第 {idx + 1}/{total_batches} 批（原PDF页码 {start_page}-{end_page}）...")

        pages_content = self._prepare_pages_content(batch)

        # 添加批次说明
        batch_note = (
            f"这是长文档《{doc_title}》的第 {idx + 1}/{total_batches} 部分，"
            f"包含原PDF第 {start_page}-{end_page} 页。\n\n"
            f"注意：如果某些内容明显是前一部分的延续（如段落跨页），"
            f"请保留并正常格式化。"
        )
        if idx > 0:
            batch_note += (
                "文档主标题已由前一部分提供，"
                "请只输出本章节的结构化内容，不要重复输出 `# 文档标题`。"
            )
        batch_note += "\n\n"

        prompt = self.REORGANIZE_PROMPT.format(pages_content=batch_note + pages_content)

        # 带限流重试的调用
        for attempt in range(retry_count + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=32768,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }],
                    stream=True,
                )

                # 收集 streaming 响应中的文本
                result = ""
                for chunk in response:
                    if chunk.type == "content_block_delta":
                        if hasattr(chunk.delta, "text") and chunk.delta.text:
                            result += chunk.delta.text

                result = result.strip()
                result = self._clean_code_block_markers(result)

                # 后续批次：移除模型生成的文档主标题，避免重复
                if idx > 0:
                    lines = result.split('\n')
                    if lines and lines[0].startswith('# '):
                        result = '\n'.join(lines[1:]).strip()

                return idx, result

            except anthropic.RateLimitError as e:
                if attempt < retry_count:
                    wait_time = 2 ** attempt
                    print(f"  第{idx + 1}批触发限流，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"  ⚠️  第{idx + 1}批限流重试耗尽，降级为简单拼接")
                    break
            except Exception as e:
                print(f"  ⚠️  第{idx + 1}批重构失败: {e}，降级为简单拼接")
                break

        # 降级为简单拼接
        fallback = self._simple_join(batch, doc_title)
        if idx > 0:
            lines = fallback.split('\n')
            if lines and lines[0].startswith('# '):
                fallback = '\n'.join(lines[1:]).strip()
        return idx, fallback

    def _reorganize_in_batches(
        self,
        pages: List[Tuple[int, str]],
        doc_title: str,
        config: ReorganizeConfig,
    ) -> str:
        """分批次重构（适合长文档）- 并发执行"""
        batches = self._split_balanced_batches(pages, config.max_pages_per_batch)
        batch_sizes = "/".join(str(len(batch)) for batch in batches)

        print(f"  文档共{len(pages)}页，分{len(batches)}批重构（{batch_sizes}页），并发数: 3...")

        # 并发处理各批
        batch_results = [None] * len(batches)
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_idx = {}
            for idx, batch in enumerate(batches):
                future = executor.submit(
                    self._reorganize_one_batch,
                    idx, batch, doc_title, len(batches)
                )
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    _, result = future.result()
                    batch_results[idx] = result
                except Exception as e:
                    print(f"  ⚠️  第{idx + 1}批并发执行异常: {e}，降级为简单拼接")
                    batch = batches[idx]
                    fallback = self._simple_join(batch, doc_title)
                    if idx > 0:
                        lines = fallback.split('\n')
                        if lines and lines[0].startswith('# '):
                            fallback = '\n'.join(lines[1:]).strip()
                    batch_results[idx] = fallback

        # 合并所有批次结果
        final = '\n\n'.join(batch_results)

        # 确保整体有文档标题
        if not final.startswith("# "):
            final = f"# {doc_title}\n\n{final}"

        return final

    @staticmethod
    def _split_balanced_batches(
        pages: List[Tuple[int, str]],
        target_batch_size: int,
    ) -> List[List[Tuple[int, str]]]:
        """
        按目标页数均衡切分，允许单批小幅超出目标，避免 25/25/1 这类小尾批。
        """
        total_pages = len(pages)
        if total_pages == 0:
            return []

        target_batch_size = max(1, target_batch_size)
        overflow_allowance = max(1, (target_batch_size + 9) // 10)
        hard_batch_size = target_batch_size + overflow_allowance

        batch_count = (total_pages + hard_batch_size - 1) // hard_batch_size
        base_size = total_pages // batch_count
        larger_batches = total_pages % batch_count

        batches = []
        start = 0
        for idx in range(batch_count):
            size = base_size + (1 if idx < larger_batches else 0)
            end = start + size
            batches.append(pages[start:end])
            start = end

        return batches

    def _summarize_batch(self, pages_content: str) -> str:
        """对一批页面提取结构摘要"""
        prompt = self.SUMMARY_PROMPT.format(content=pages_content)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                stream=True,
            )

            # 收集 streaming 响应中的文本
            result = ""
            for chunk in response:
                if chunk.type == "content_block_delta":
                    if hasattr(chunk.delta, "text") and chunk.delta.text:
                        result += chunk.delta.text

            return result.strip()
        except Exception as e:
            return f"摘要提取失败: {e}"

    def _build_structure_prompt(self, batch_summaries: List[dict], doc_title: str) -> str:
        """构建全局结构提示"""
        lines = [
            f"你正在整理一份长文档：{doc_title}",
            "",
            "## 文档结构概览",
            "",
        ]

        for summary in batch_summaries:
            lines.append(f"### 第{summary['batch_idx'] + 1}部分（页码范围待识别）")
            lines.append(summary['summary'])
            lines.append("")

        lines.extend([
            "",
            "请基于以上结构概览和以下完整内容，整理为一份结构清晰的报告。",
            "要求：去除重复页眉页脚、合并跨页内容、构建合理章节层级、完整保留所有原文内容。",
            "",
        ])

        return "\n".join(lines)

    def _simple_join_from_content(self, pages_content: str, doc_title: str) -> str:
        """从已格式化的内容简单拼接"""
        lines = [f"# {doc_title}", ""]

        # 提取各页内容
        page_pattern = r"<!-- PAGE: \d+ -->\n+(.*?)(?=\n*<!-- PAGE: |$)"
        matches = re.findall(page_pattern, pages_content, re.DOTALL)

        for content in matches:
            lines.append(content.strip())
            lines.append("")

        return "\n\n".join(lines)

    @staticmethod
    def _clean_code_block_markers(text: str) -> str:
        """清理可能的代码块标记"""
        if text.startswith("```markdown"):
            text = text[11:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    def post_cleanup(self, markdown: str, config: Optional[ReorganizeConfig] = None) -> str:
        """
        后处理清理：去除残余的重复模式和格式问题

        Args:
            markdown: 重构后的Markdown
            config: 配置

        Returns:
            清理后的Markdown
        """
        config = config or ReorganizeConfig()

        # 1. 去除残余的页码标记
        if not config.preserve_page_markers:
            markdown = re.sub(r'\n*<!-- PAGE: \d+ -->\n*', '\n\n', markdown)

        # 2. 去除连续的---分隔线（过渡页残留）
        markdown = re.sub(r'\n---\n+---\n', '\n---\n', markdown)
        markdown = re.sub(r'\n{3,}---\n{3,}', '\n\n---\n\n', markdown)

        # 3. 去除孤立的机构名称/保密标识行（常见页脚模式）
        footer_patterns = [
            # 中文机构名 + 英文名称（如"XX资本\nCYGNUS EQUITY"）
            r'\n+[^\n]{2,20}(资本|基金|证券|投行|投资|咨询|律所|事务所)\s*\n+[A-Z][A-Za-z\s&\.]{2,30}[A-Za-z]\s*\n+',
            # 通用机构名称行
            r'\n+[^\n]{2,20}(资本|基金|证券|投行|投资|咨询|律所|事务所)\s*\n+',
            r'\n+CONFIDENTIAL\s*\n+',
            r'\n+保密文件\s*\n+',
            r'\n+内部资料\s*\n+',
        ]

        if config.remove_footer_patterns:
            footer_patterns.extend(config.remove_footer_patterns)

        for pattern in footer_patterns:
            markdown = re.sub(pattern, '\n\n', markdown, flags=re.IGNORECASE)

        # 4. 合并过多的空行
        markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)

        # 5. 去除行尾空格
        markdown = re.sub(r' +\n', '\n', markdown)

        # 6. 修复表格格式：确保表头分隔行存在
        markdown = self._fix_table_separators(markdown)

        return markdown.strip()

    @staticmethod
    def _fix_table_separators(markdown: str) -> str:
        """修复缺失的表格分隔行"""
        lines = markdown.split('\n')
        result = []
        i = 0

        def _is_separator_row(text: str) -> bool:
            """判断是否为表格分隔行"""
            stripped = text.strip()
            if not stripped.startswith('|') or not stripped.endswith('|'):
                return False
            # 分隔行只包含 |、-、:、空白
            inner = stripped[1:-1]
            return bool(re.match(r'^[\s\-:|]+$', inner))

        while i < len(lines):
            line = lines[i]

            # 检测表格块的开始行：包含 | 且不是分隔行
            if '|' in line and not _is_separator_row(line):
                # 收集整个表格块
                table_block = [line]
                j = i + 1
                while j < len(lines) and '|' in lines[j]:
                    table_block.append(lines[j])
                    j += 1

                # 如果表格块只有一行，或者第二行不是分隔行，则需要插入分隔行
                needs_separator = len(table_block) == 1 or not _is_separator_row(table_block[1])

                if needs_separator and len(table_block) >= 1:
                    # 计算列数
                    cols = line.count('|') - 1
                    if cols > 0:
                        separator = '|' + '---|' * cols
                        # 输出表头行
                        result.append(line)
                        # 输出分隔行
                        result.append(separator)
                        # 输出剩余行（跳过原来的第一行）
                        for k in range(1, len(table_block)):
                            result.append(table_block[k])
                        i = j
                        continue
                else:
                    # 已有分隔行，直接输出整个表格块
                    for row in table_block:
                        result.append(row)
                    i = j
                    continue

            result.append(line)
            i += 1

        return '\n'.join(result)
