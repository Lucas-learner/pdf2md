#!/usr/bin/env python3
"""
PDF扫描件转Markdown - 主程序

使用方式：
    python pdf_to_markdown.py <pdf_path> [options]

示例：
    python pdf_to_markdown.py report.pdf
    python pdf_to_markdown.py report.pdf --start-page 5 --end-page 15 --concurrency 5
    python pdf_to_markdown.py report.pdf --api-key your_key --base-url https://api.kimi.com/coding/
"""

import os
import sys
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

from pdf_converter import PDFConverter, PPTXConverter
from vision_recognizer import VisionRecognizer
from result_merger import ResultMerger, MergeConfig
from content_reorganizer import ReorganizeConfig
from document_detector import DocumentDetector, DocumentType
from structured_extractors import ExtractorFactory, ExtractedContent


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="将PDF/PPTX/Word文档转换为Markdown格式（PDF/PPTX通过Vision API识别）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s document.pdf
  %(prog)s document.pdf -o ./output/ -s 5 -e 15
  %(prog)s document.pdf --concurrency 5 --dpi 300
  %(prog)s presentation.pptx
        """
    )

    parser.add_argument(
        "pdf_path",
        help="PDF文件路径或包含PDF的目录"
    )

    parser.add_argument(
        "--batch",
        action="store_true",
        help="批量处理：pdf_path为目录时，处理该目录下所有PDF文件"
    )

    parser.add_argument(
        "--force-vision",
        action="store_true",
        dest="force_vision",
        help="已弃用：当前所有PDF和PPTX默认使用Vision API处理"
    )

    parser.add_argument(
        "--no-reorganize",
        action="store_true",
        dest="no_reorganize",
        help="禁用智能重构，使用传统逐页拼接模式"
    )

    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        help="输出目录，默认与PDF同目录"
    )

    parser.add_argument(
        "-s", "--start-page",
        type=int,
        dest="start_page",
        help="起始页码（从1开始）"
    )

    parser.add_argument(
        "-e", "--end-page",
        type=int,
        dest="end_page",
        help="结束页码"
    )

    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=10,
        dest="concurrency",
        help="并发数，默认10"
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="PDF转图片的分辨率，默认300"
    )

    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="保留转换后的图片文件"
    )

    parser.add_argument(
        "--api-key",
        help="Kimi Code API Key（默认从环境变量KIMI_API_KEY读取）"
    )

    parser.add_argument(
        "--model",
        default="kimi-coding",
        help="使用的模型，默认kimi-coding"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        dest="batch_size",
        help="智能重构时每批处理的目标页数，默认25（会小幅均衡以避免小尾批）"
    )

    parser.add_argument(
        "--base-url",
        default="https://api.kimi.com/coding/",
        help="API基础URL，默认https://api.kimi.com/coding/"
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        dest="skip_existing",
        help="跳过已存在 .md 输出文件的源文件（默认启用）"
    )

    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="强制重新处理所有文件，覆盖已存在的 .md"
    )

    return parser.parse_args()


def print_progress(page_num: int, status: str):
    """打印进度"""
    status_icon = {
        "success": "✓",
        "failed": "✗",
        "error": "✗"
    }.get(status, "?")
    print(f"  第{page_num:4d}页 {status_icon}")


def process_vision_document(
    pdf_path: Path,
    output_dir: Path,
    args,
    api_key: str,
    original_path: Optional[Path] = None,
) -> Optional[bool]:
    """处理PDF文件（Vision API识别流程）
    
    Args:
        pdf_path: PDF文件路径（可能是临时转换生成的）
        output_dir: 输出目录
        args: 命令行参数
        api_key: API Key
        original_path: 原始文件路径（用于命名输出文件，如PPTX转换场景）
    
    Returns:
        True: 处理成功
        False: 处理失败
        None: 已存在，跳过
    """
    # 输出文件路径使用原始文件名
    src_path = original_path or pdf_path
    output_file = output_dir / f"{src_path.stem}.md"

    # 检查是否已存在
    if getattr(args, 'skip_existing', True) and output_file.exists():
        print(f"⏭️  跳过（已存在）: {src_path.name} → {output_file.name}")
        return None

    print("=" * 60)
    print(f"处理: {src_path.name}")
    print("=" * 60)
    print(f"输出文件: {output_file}")
    print(f"并发数: {args.concurrency}")
    print(f"DPI: {args.dpi}")
    print("-" * 60)

    # 创建临时目录存放图片
    temp_dir = tempfile.mkdtemp(prefix="pdf_to_md_")
    images_dir = Path(temp_dir) / "pages"

    try:
        # 步骤1: PDF转图片
        print("\n[1/3] 正在转换PDF为图片...")
        converter = PDFConverter(dpi=args.dpi)

        # 获取总页数
        total_pages = converter.get_page_count(str(pdf_path))
        print(f"PDF总页数: {total_pages}")

        # 确定处理范围
        start_page = args.start_page or 1
        end_page = args.end_page or total_pages

        if start_page < 1:
            start_page = 1
        if end_page > total_pages:
            end_page = total_pages

        image_paths = converter.convert(
            pdf_path=str(pdf_path),
            output_dir=images_dir,
            start_page=start_page,
            end_page=end_page,
        )
        print(f"成功转换 {len(image_paths)} 页")

        # 步骤2: 识别图片
        print(f"\n[2/3] 正在识别图片内容（使用 {args.model}）...")
        recognizer = VisionRecognizer(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model
        )

        results = recognizer.recognize_batch(
            image_paths=image_paths,
            max_workers=args.concurrency,
            progress_callback=print_progress,
        )

        # 统计结果（初次）
        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count
        print(f"\n初次识别完成: {success_count}页成功, {failed_count}页失败")

        # 步骤2.5: 补充重试（限流导致的失败页）
        rate_limit_failures = [r for r in results if r.error_type == "rate_limit"]
        if rate_limit_failures:
            print(f"\n[2.5/3] {len(rate_limit_failures)} 页因限流失败，等待 10 秒后补充重试...")
            import time
            time.sleep(10)
            for r in rate_limit_failures:
                page_idx = r.page_num - 1
                if 0 <= page_idx < len(image_paths):
                    new_result = recognizer.recognize_page(
                        image_paths[page_idx], r.page_num,
                        retry_count=3,
                    )
                    results[page_idx] = new_result
                    status = "✓ 补回成功" if new_result.success else "✗ 仍失败"
                    print(f"  第{r.page_num:4d}页 {status}")

        # 重新统计（区分错误类型）
        success_count = sum(1 for r in results if r.success)
        high_risk_pages = [r.page_num for r in results if r.error_type == "high_risk"]
        fatal_pages = [r.page_num for r in results if not r.success and r.error_type == "other"]
        fatal_count = len(fatal_pages)
        total_pages_processed = len(results)

        print(f"\n最终识别统计: {success_count}页成功, {len(high_risk_pages)}页安全审核未通过, {fatal_count}页致命错误")

        # 阈值检查：致命错误率 > 10% 则跳过重构
        fatal_rate = fatal_count / total_pages_processed if total_pages_processed else 0
        skip_reorganize_note = None
        if fatal_rate > 0.1:
            skip_reorganize_note = f"致命错误率{fatal_rate:.1%}（{fatal_count}/{total_pages_processed}页），跳过智能重构"
            print(f"\n⚠️  {skip_reorganize_note}")
            # 修改输出文件名
            output_file = output_dir / f"{src_path.stem}_【{fatal_count}】页未完整提取.md"
            print(f"输出文件已重命名: {output_file.name}")
            enable_reorganize = False
        else:
            enable_reorganize = not args.no_reorganize

        # 步骤3: 合并结果
        print("\n[3/3] 正在合并结果...")
        merge_config = MergeConfig(
            enable_reorganize=enable_reorganize,
            reorganize_config=ReorganizeConfig(
                max_pages_per_batch=args.batch_size,
                enable_reorganize=enable_reorganize,
            ),
        )
        merger = ResultMerger(config=merge_config)

        markdown = merger.merge(
            results=results,
            pdf_path=src_path,
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            high_risk_pages=high_risk_pages if high_risk_pages else None,
            fatal_pages=fatal_pages if fatal_pages else None,
            skip_reorganize_note=skip_reorganize_note,
        )

        # 保存文件
        merger.save(markdown, output_file)
        print(f"已保存到: {output_file}")

        # 如果需要保留图片，移动到输出目录
        if args.keep_images:
            keep_dir = output_dir / f"{src_path.stem}_images"
            keep_dir.mkdir(exist_ok=True)
            for img_path in image_paths:
                target = keep_dir / img_path.name
                img_path.rename(target)
            print(f"图片已保留到: {keep_dir}")

        print("\n" + "=" * 60)
        print(f"完成: {pdf_path.name}")
        print("=" * 60)

        # 如果有失败页面，显示警告
        if failed_count > 0:
            failed_pages = [r.page_num for r in results if not r.success]
            print(f"\n警告: 以下页面识别失败，请手动检查:")
            for page_num in failed_pages:
                print(f"  - 第{page_num}页")

        return True

    except Exception as e:
        print(f"\n错误: 处理 {pdf_path.name} 时出错: {e}")
        return False

    finally:
        # 清理临时文件
        if not args.keep_images:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


def process_pptx(
    pptx_path: Path,
    output_dir: Path,
    args,
    api_key: str
) -> Optional[bool]:
    """处理PPTX文件：先转PDF，再走Vision API流程"""
    pptx_converter = PPTXConverter(dpi=args.dpi, fmt="png")
    if not pptx_converter.is_available():
        print(f"\n⚠️  LibreOffice未安装，无法将PPTX转为图片进行Vision识别")
        print("    请安装LibreOffice后再试")
        print("    macOS: brew install libreoffice")
        print("    Ubuntu: apt-get install libreoffice")
        return False

    with tempfile.TemporaryDirectory(prefix="pptx_to_pdf_") as tmpdir:
        try:
            print("=" * 60)
            print(f"处理: {pptx_path.name}")
            print("=" * 60)
            print(f"方式: PPTX → PDF → 图片 → Vision API识别")
            print("-" * 60)

            # PPTX → PDF
            print("\n[0/4] 正在将PPTX转换为PDF...")
            pdf_path = pptx_converter._pptx_to_pdf(pptx_path, Path(tmpdir))
            print(f"  ✓ 已生成临时PDF: {pdf_path.name}")

            # 复用PDF处理流程（传入原始PPTX路径用于命名）
            return process_vision_document(pdf_path, output_dir, args, api_key, original_path=pptx_path)
        except Exception as e:
            print(f"\n错误: 处理 {pptx_path.name} 时出错: {e}")
            return False


def process_structured_document(
    file_path: Path,
    output_dir: Path,
    doc_type: str,
    skip_existing: bool = True,
) -> Optional[bool]:
    """处理结构化文档（Word）—— 保留结构化提取作为回退
    
    Returns:
        True: 处理成功
        False: 处理失败
        None: 已存在，跳过
    """
    output_file = output_dir / f"{file_path.stem}.md"
    
    # 检查是否已存在
    if skip_existing and output_file.exists():
        print(f"⏭️  跳过（已存在）: {file_path.name} → {output_file.name}")
        return None
    
    try:
        print(f"  使用结构化提取: {file_path.name}")

        result = ExtractorFactory.extract_file(file_path, doc_type)

        # 保存结果
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result.content)

        print(f"  ✓ 已保存: {output_file.name}")
        return True

    except Exception as e:
        print(f"  ✗ 处理失败: {e}")
        return False


def main():
    """主函数"""
    args = parse_args()

    # 检查路径
    input_path = Path(args.pdf_path)
    if not input_path.exists():
        print(f"错误：路径不存在: {input_path}")
        sys.exit(1)

    # 检查API Key（Vision API识别需要）
    api_key = args.api_key or os.environ.get("KIMI_API_KEY")

    # 批量处理
    if args.batch and input_path.is_dir():
        # 使用文档检测器分析所有文件
        detector = DocumentDetector()
        all_results = detector.detect_batch(input_path, recursive=False)

        # 打印检测报告
        detector.print_detection_report(all_results)

        # 确定输出目录
        output_dir = Path(args.output_dir) if args.output_dir else input_path
        output_dir.mkdir(parents=True, exist_ok=True)

        # 分类处理
        scanned_results = [r for r in all_results if r.doc_type == DocumentType.SCANNED_PDF]
        vector_results = [r for r in all_results if r.doc_type == DocumentType.VECTOR_PDF]
        word_results = [r for r in all_results if r.doc_type == DocumentType.WORD]
        pptx_results = [r for r in all_results if r.doc_type == DocumentType.PPTX]

        # 需要Vision API的文档
        vision_results = scanned_results + vector_results + pptx_results

        # 统计
        success_count = {'vision': 0, 'structured': 0}
        failed_count = {'vision': 0, 'structured': 0}
        skip_count = {'vision': 0, 'structured': 0}

        # 1. 处理所有PDF和PPTX（Vision API）
        if vision_results:
            if not api_key:
                print("\n⚠️  警告：检测到需要Vision API识别的文档，但未提供API Key，跳过处理")
                print("    请设置 KIMI_API_KEY 环境变量或使用 --api-key 参数")
            else:
                # 扫描件PDF
                if scanned_results:
                    print(f"\n🔍 正在处理扫描件PDF（Vision API识别）...")
                    print("=" * 60)
                    for i, result in enumerate(scanned_results, 1):
                        print(f"\n[{i}/{len(scanned_results)}] 开始处理...")
                        ret = process_vision_document(result.file_path, output_dir, args, api_key)
                        if ret is True:
                            success_count['vision'] += 1
                        elif ret is False:
                            failed_count['vision'] += 1
                        else:
                            skip_count['vision'] += 1

                # 矢量PDF
                if vector_results:
                    print(f"\n📝 正在处理矢量PDF（Vision API识别）...")
                    print("=" * 60)
                    for i, result in enumerate(vector_results, 1):
                        print(f"\n[{i}/{len(vector_results)}] 开始处理...")
                        ret = process_vision_document(result.file_path, output_dir, args, api_key)
                        if ret is True:
                            success_count['vision'] += 1
                        elif ret is False:
                            failed_count['vision'] += 1
                        else:
                            skip_count['vision'] += 1

                # PPTX
                if pptx_results:
                    print(f"\n📊 正在处理PowerPoint（Vision API识别）...")
                    print("=" * 60)
                    for i, result in enumerate(pptx_results, 1):
                        print(f"\n[{i}/{len(pptx_results)}] 开始处理...")
                        ret = process_pptx(result.file_path, output_dir, args, api_key)
                        if ret is True:
                            success_count['vision'] += 1
                        elif ret is False:
                            failed_count['vision'] += 1
                        else:
                            skip_count['vision'] += 1

        # 2. 处理Word文档（保持结构化提取）
        if word_results:
            print(f"\n📘 正在处理Word文档（结构化提取）...")
            print("=" * 60)

            for result in word_results:
                ret = process_structured_document(
                    result.file_path, output_dir, 'word',
                    skip_existing=getattr(args, 'skip_existing', True)
                )
                if ret is True:
                    success_count['structured'] += 1
                elif ret is False:
                    failed_count['structured'] += 1
                else:
                    skip_count['structured'] += 1

        # 批量处理总结
        print("\n\n" + "=" * 60)
        print("批量处理完成!")
        print("=" * 60)

        total_success = success_count['vision'] + success_count['structured']
        total_failed = failed_count['vision'] + failed_count['structured']
        total_skipped = skip_count['vision'] + skip_count['structured']
        total_files = total_success + total_failed + total_skipped

        print(f"总计: {total_files} 个文件")
        print(f"  ✅ 处理成功: {total_success} 个")
        print(f"     - Vision API识别: {success_count['vision']} 个")
        print(f"     - 结构化提取: {success_count['structured']} 个")

        if total_skipped > 0:
            print(f"  ⏭️  已存在跳过: {total_skipped} 个")
            print(f"     - Vision API识别: {skip_count['vision']} 个")
            print(f"     - 结构化提取: {skip_count['structured']} 个")

        if total_failed > 0:
            print(f"  ❌ 处理失败: {total_failed} 个")
            print(f"     - Vision API识别: {failed_count['vision']} 个")
            print(f"     - 结构化提取: {failed_count['structured']} 个")

    else:
        # 单文件处理
        if input_path.is_dir():
            print(f"错误: {input_path} 是目录。请使用 --batch 参数批量处理，或指定具体文件")
            sys.exit(1)

        # 确定输出目录
        output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # 检测文档类型
        detector = DocumentDetector()
        detection = detector.detect(input_path)

        print("=" * 60)
        print(f"处理: {input_path.name}")
        print(f"检测类型: {detection.reason}")
        print("=" * 60)

        # 根据类型选择处理方式
        ret = None
        if detection.doc_type == DocumentType.SCANNED_PDF:
            if not api_key:
                print("错误：扫描件PDF需要提供API Key")
                print("请设置 KIMI_API_KEY 环境变量或使用 --api-key 参数")
                sys.exit(1)
            ret = process_vision_document(input_path, output_dir, args, api_key)

        elif detection.doc_type == DocumentType.VECTOR_PDF:
            if not api_key:
                print("错误：矢量PDF（Vision API识别）需要提供API Key")
                print("请设置 KIMI_API_KEY 环境变量或使用 --api-key 参数")
                sys.exit(1)
            ret = process_vision_document(input_path, output_dir, args, api_key)

        elif detection.doc_type == DocumentType.WORD:
            ret = process_structured_document(
                input_path, output_dir, 'word',
                skip_existing=getattr(args, 'skip_existing', True)
            )

        elif detection.doc_type == DocumentType.PPTX:
            if not api_key:
                print("错误：PowerPoint（Vision API识别）需要提供API Key")
                print("请设置 KIMI_API_KEY 环境变量或使用 --api-key 参数")
                sys.exit(1)
            ret = process_pptx(input_path, output_dir, args, api_key)

        else:
            print(f"错误：不支持的文件类型 - {detection.reason}")
            sys.exit(1)

        # 单文件处理时，如果跳过了，提示用户
        if ret is None:
            print(f"\n⏭️  输出文件已存在，使用 --no-skip-existing 强制重新处理")


if __name__ == "__main__":
    main()
