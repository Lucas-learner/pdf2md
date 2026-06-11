"""
PDF转图片模块
将PDF/PPTX文件转换为图片序列，支持指定页码范围、DPI设置
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from pdf2image import convert_from_path
from PIL import Image


def find_libreoffice() -> Optional[str]:
    """查找系统安装的 LibreOffice 可执行文件"""
    candidates = [
        "soffice",
        "libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/libreoffice",
    ]
    for cmd in candidates:
        if shutil.which(cmd):
            return cmd
    return None


class PPTXConverter:
    """PPTX转图片转换器（借助LibreOffice先转PDF）"""

    def __init__(self, dpi: int = 300, fmt: str = "png"):
        self.dpi = dpi
        self.fmt = fmt.lower()
        self.libreoffice = find_libreoffice()

    def is_available(self) -> bool:
        """检查LibreOffice是否可用"""
        return self.libreoffice is not None

    def convert(
        self,
        pptx_path: str,
        output_dir: Optional[str] = None,
    ) -> List[Path]:
        """
        将PPTX转换为图片序列

        Args:
            pptx_path: PPTX文件路径
            output_dir: 图片输出目录，默认PPTX同级目录

        Returns:
            生成的图片路径列表
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX文件不存在: {pptx_path}")

        if not self.is_available():
            raise RuntimeError(
                "LibreOffice 未安装，无法将 PPTX 转换为图片。\n"
                "macOS: brew install libreoffice\n"
                "Ubuntu/Debian: apt-get install libreoffice\n"
                "或直接从 https://www.libreoffice.org 下载安装"
            )

        # 确定输出目录
        if output_dir is None:
            output_dir = pptx_path.parent / f"{pptx_path.stem}_pages"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. PPTX → PDF（使用LibreOffice）
        with tempfile.TemporaryDirectory(prefix="pptx_to_pdf_") as tmpdir:
            pdf_path = self._pptx_to_pdf(pptx_path, Path(tmpdir))

            # 2. PDF → 图片
            pdf_converter = PDFConverter(dpi=self.dpi, fmt=self.fmt)
            image_paths = pdf_converter.convert(
                pdf_path=str(pdf_path),
                output_dir=output_dir,
            )

        print(f"成功转换 {len(image_paths)} 页到: {output_dir}")
        return image_paths

    def _pptx_to_pdf(self, pptx_path: Path, output_dir: Path) -> Path:
        """使用LibreOffice将PPTX转为PDF"""
        print(f"正在将PPTX转为PDF（使用LibreOffice）...")

        cmd = [
            self.libreoffice,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(pptx_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"LibreOffice转换失败: {e.stderr or e.stdout or '未知错误'}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice转换超时（超过180秒）")

        # LibreOffice输出文件名与输入相同，扩展名改为pdf
        pdf_name = pptx_path.stem + ".pdf"
        pdf_path = output_dir / pdf_name
        if not pdf_path.exists():
            raise FileNotFoundError(
                f"LibreOffice转换后未找到PDF文件，可能文件名不匹配。"
                f"预期: {pdf_path}"
            )

        return pdf_path

    def convert_to_base64(
        self,
        pptx_path: str,
    ) -> List[Tuple[int, str]]:
        """
        将PPTX转换为base64编码的图片

        Returns:
            [(页码, base64字符串), ...]
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX文件不存在: {pptx_path}")

        if not self.is_available():
            raise RuntimeError("LibreOffice 未安装")

        with tempfile.TemporaryDirectory(prefix="pptx_to_pdf_") as tmpdir:
            pdf_path = self._pptx_to_pdf(pptx_path, Path(tmpdir))
            pdf_converter = PDFConverter(dpi=self.dpi, fmt=self.fmt)
            return pdf_converter.convert_to_base64(pdf_path)

    def get_slide_count(self, pptx_path: str) -> int:
        """获取PPTX幻灯片总数（通过python-pptx）"""
        try:
            from pptx import Presentation
            prs = Presentation(str(pptx_path))
            return len(prs.slides)
        except ImportError:
            raise ImportError("python-pptx 未安装，请运行: pip install python-pptx")



class PDFConverter:
    """PDF转图片转换器"""

    def __init__(self, dpi: int = 300, fmt: str = "png"):
        """
        初始化转换器

        Args:
            dpi: 输出图片分辨率，默认300（识别建议≥300）
            fmt: 输出格式，默认png（可选jpeg）
        """
        self.dpi = dpi
        self.fmt = fmt.lower()
        self._temp_dir: Optional[Path] = None

    def convert(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> List[Path]:
        """
        将PDF转换为图片序列

        Args:
            pdf_path: PDF文件路径
            output_dir: 图片输出目录，默认PDF同级目录
            start_page: 起始页码（1-based），默认从第1页
            end_page: 结束页码（1-based），默认到最后页

        Returns:
            生成的图片路径列表
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        # 确定输出目录
        if output_dir is None:
            output_dir = pdf_path.parent / f"{pdf_path.stem}_pages"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 页码参数转换（pdf2image使用0-based first_page）
        first_page = start_page if start_page else 1
        last_page = end_page

        print(f"正在转换PDF: {pdf_path.name}")
        print(f"页码范围: {first_page} - {last_page or '末尾'}")
        print(f"输出DPI: {self.dpi}")

        # 转换PDF为图片
        images = convert_from_path(
            pdf_path,
            dpi=self.dpi,
            fmt=self.fmt,
            first_page=first_page,
            last_page=last_page,
        )

        # 保存图片
        saved_paths = []
        page_num = first_page
        for img in images:
            img_path = output_dir / f"page_{page_num:04d}.{self.fmt}"
            img.save(img_path, self.fmt.upper())
            saved_paths.append(img_path)
            page_num += 1

        print(f"成功转换 {len(saved_paths)} 页到: {output_dir}")
        return saved_paths

    def convert_to_base64(
        self,
        pdf_path: str,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> List[Tuple[int, str]]:
        """
        将PDF转换为base64编码的图片（直接用于API）

        Args:
            pdf_path: PDF文件路径
            start_page: 起始页码（1-based）
            end_page: 结束页码（1-based）

        Returns:
            [(页码, base64字符串), ...]
        """
        import base64
        import io

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        first_page = start_page if start_page else 1

        images = convert_from_path(
            pdf_path,
            dpi=self.dpi,
            fmt=self.fmt,
            first_page=first_page,
            last_page=end_page,
        )

        result = []
        page_num = first_page
        for img in images:
            buffer = io.BytesIO()
            img.save(buffer, format=self.fmt.upper())
            img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            result.append((page_num, img_base64))
            page_num += 1

        return result

    def get_page_count(self, pdf_path: str) -> int:
        """获取PDF总页数"""
        from pdf2image.pdf2image import pdfinfo_from_path

        info = pdfinfo_from_path(pdf_path)
        return int(info.get("Pages", 0))


def preprocess_image(image_path: Path, enhance: bool = True) -> Path:
    """
    图片预处理：去噪、增强对比度

    Args:
        image_path: 图片路径
        enhance: 是否增强对比度

    Returns:
        处理后图片路径（原路径覆盖或新路径）
    """
    img = Image.open(image_path)

    if enhance:
        # 增强对比度
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.2)  # 轻微增强

        # 自动亮度
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)

    # 保存
    img.save(image_path)
    return image_path
