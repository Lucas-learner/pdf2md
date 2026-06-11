"""
Kimi Code Vision识别模块
使用Claude SDK调用Kimi Code API识别图片内容
"""

import os
import base64
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import anthropic
except ImportError:
    raise ImportError("请安装anthropic SDK: python3 -m pip install anthropic")


@dataclass
class RecognitionResult:
    """单页识别结果"""
    page_num: int
    markdown: str
    success: bool
    error: Optional[str] = None
    error_type: Optional[str] = None  # 'rate_limit' | 'high_risk' | 'other'


class VisionRecognizer:
    """Kimi Code Vision识别器 - 使用Anthropic SDK"""

    # 识别提示词模板
    DEFAULT_PROMPT = """请将这张PDF页面转换为Markdown格式。

## 核心识别要求：

### 1. 内容完整性（最高优先级）
- **必须完整识别页面上的所有文字**，包括标题、正文、列表、表格、注释等
- **严禁遗漏**任何文字、数字、百分比、金额、日期、人名、公司名
- 保留原文的换行和分段结构，不要擅自合并段落

### 2. 表格处理
- 识别为Markdown表格格式，必须有表头分隔行 `|:---|:---|`
- 保持行列对齐，表头加粗
- 合并单元格用HTML `<td colspan="N">` 或标注"合并单元格"
- 表格中的每一行、每一列都必须完整输出，不要省略

### 3. 层级结构
- 根据字体大小、加粗、编号判断标题层级（# ## ### ####）
- 列表转为Markdown列表（- 或 1. 2. 3.）
- 列表项不要合并，保持原文的每一项独立

### 4. 流程图/架构图
- 优先转换为Mermaid语法或ASCII流程图
- 复杂流程用文字层级描述（如 ├── 分支结构）

### 5. 特殊元素处理
- 页眉页脚：如果页面顶部/底部有重复出现的机构名称、页码等，用 `<!-- HEADER: 内容 -->` 和 `<!-- FOOTER: 内容 -->` 标注后正常输出内容
- 印章：描述为 `[印章：文字内容]`
- 手写批注：识别为 `> 批注：内容`
- 图片：非表格/流程图的普通图片描述为 `[图片：简要说明]`

### 6. 跨页内容标记
- 如果页面底部的段落/列表明显被截断（未完整结束），在末尾标注 `<!-- CONTINUED -->`
- 如果页面顶部明显是上一页段落的延续（无标题开头，直接接上一段内容），在开头标注 `<!-- CONTINUATION -->`

## 输出格式：

只输出纯Markdown内容，不要添加```markdown代码块标记，不要添加"以下是转换结果"等说明文字。

如果页面包含表格，确保表格格式正确，列对齐使用 `|:---|:---|:---|` 这样的分隔符。
"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "kimi-coding",
    ):
        """
        初始化识别器

        Args:
            api_key: API Key，默认从环境变量 ANTHROPIC_AUTH_TOKEN 或 KIMI_API_KEY 读取
            base_url: API基础URL，默认从环境变量 ANTHROPIC_BASE_URL 读取
            model: 使用的模型，默认kimi-coding
        """
        # 优先使用 ANTHROPIC_AUTH_TOKEN（Claude Code配置）
        self.api_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("需要提供API Key（ANTHROPIC_AUTH_TOKEN 或 KIMI_API_KEY）")

        # 优先使用 ANTHROPIC_BASE_URL（Claude Code配置）
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        if not self.base_url:
            self.base_url = "https://api.kimi.com/coding/"

        self.model = model

        # 初始化Anthropic客户端
        # Anthropic SDK 会自动使用 ANTHROPIC_AUTH_TOKEN 和 ANTHROPIC_BASE_URL
        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def recognize_page(
        self,
        image_path: Path,
        page_num: int,
        custom_prompt: Optional[str] = None,
        retry_count: int = 2,
    ) -> RecognitionResult:
        """
        识别单页图片

        Args:
            image_path: 图片文件路径
            page_num: 页码编号
            custom_prompt: 自定义提示词
            retry_count: 失败重试次数

        Returns:
            RecognitionResult
        """
        prompt = custom_prompt or self.DEFAULT_PROMPT

        # 读取图片并编码
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return RecognitionResult(
                page_num=page_num,
                markdown="",
                success=False,
                error=f"读取图片失败: {str(e)}"
            )

        # 判断图片格式
        ext = image_path.suffix.lower()
        media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

        # 调用API识别
        for attempt in range(retry_count + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            }
                        ]
                    }]
                )

                markdown = response.content[0].text.strip()

                # 清理可能的代码块标记
                if markdown.startswith("```markdown"):
                    markdown = markdown[11:]
                if markdown.startswith("```"):
                    markdown = markdown[3:]
                if markdown.endswith("```"):
                    markdown = markdown[:-3]

                return RecognitionResult(
                    page_num=page_num,
                    markdown=markdown.strip(),
                    success=True,
                )

            except anthropic.RateLimitError as e:
                if attempt < retry_count:
                    wait_time = 2 ** attempt  # 指数退避
                    print(f"  页{page_num}触发限流，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    return RecognitionResult(
                        page_num=page_num,
                        markdown="",
                        success=False,
                        error=f"API限流: {str(e)}",
                        error_type="rate_limit",
                    )

            except Exception as e:
                error_msg = str(e)
                # 区分 high_risk 内容安全错误
                if "high risk" in error_msg.lower() or "invalid_request_error" in error_msg.lower():
                    error_type = "high_risk"
                    print(f"  页{page_num}内容安全审核未通过: {error_msg}")
                else:
                    error_type = "other"
                    print(f"  页{page_num}识别失败: {error_msg}")
                if attempt < retry_count:
                    print(f"  重试{attempt+1}/{retry_count}...")
                    time.sleep(1)
                else:
                    return RecognitionResult(
                        page_num=page_num,
                        markdown="",
                        success=False,
                        error=f"识别异常: {error_msg}",
                        error_type=error_type,
                    )

        return RecognitionResult(
            page_num=page_num,
            markdown="",
            success=False,
            error="未知错误",
            error_type="other",
        )

    def recognize_batch(
        self,
        image_paths: List[Path],
        max_workers: int = 3,
        progress_callback: Optional[callable] = None,
    ) -> List[RecognitionResult]:
        """
        批量识别多张图片（并发）

        Args:
            image_paths: 图片路径列表
            max_workers: 最大并发数
            progress_callback: 进度回调函数(page_num, status)

        Returns:
            RecognitionResult列表（按页码排序）
        """
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_page = {
                executor.submit(
                    self.recognize_page, path, self._extract_page_num(path)
                ): self._extract_page_num(path)
                for path in image_paths
            }

            # 收集结果
            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    result = future.result()
                    results.append(result)
                    if progress_callback:
                        progress_callback(page_num, "success" if result.success else "failed")
                except Exception as e:
                    results.append(RecognitionResult(
                        page_num=page_num,
                        markdown="",
                        success=False,
                        error=str(e)
                    ))
                    if progress_callback:
                        progress_callback(page_num, "error")

        # 按页码排序
        results.sort(key=lambda x: x.page_num)
        return results

    def recognize_base64(
        self,
        base64_image: str,
        media_type: str = "image/png",
        custom_prompt: Optional[str] = None,
    ) -> str:
        """
        直接识别base64编码的图片

        Args:
            base64_image: base64编码的图片数据
            media_type: 图片类型
            custom_prompt: 自定义提示词

        Returns:
            Markdown字符串
        """
        prompt = custom_prompt or self.DEFAULT_PROMPT

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64_image,
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ]
            }]
        )

        return response.content[0].text.strip()

    @staticmethod
    def _extract_page_num(image_path: Path) -> int:
        """从文件名提取页码（page_0001.png → 1）"""
        try:
            stem = image_path.stem  # page_0001
            num_part = stem.split("_")[-1]  # 0001
            return int(num_part)
        except (ValueError, IndexError):
            return 0
