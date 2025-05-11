# src/oculith/ocr.py
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union, List

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractOcrOptions,
    TesseractCliOcrOptions,
    OcrMacOptions,
    EasyOcrOptions
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from .parquet import save_to_parquet
from .common import convert_file

# 日志
logger = logging.getLogger(__name__)

def ocr_text_from_document(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    output_path: Optional[str] = None,
    engine: str = "rapid",
    language: Union[str, List[str]] = "zh"
) -> str:
    """使用OCR处理文档
    
    参数:
        language: 语言代码或语言代码列表，'auto'表示自动检测，'zh'表示中文
    """
    # 获取OCR转换器
    converter = get_ocr_converter(engine, language)
    
    # 转换文档
    res = convert_file(content, content_type, file_type, converter)
    
    # 保存为parquet
    if not output_path:
        from datetime import datetime
        output_dir = Path("./docling/parquet")
        output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = output_dir / f"ocr_{now}.parquet"
    
    # 保存结果
    save_to_parquet(res, output_path)
    
    return output_path

def get_ocr_converter(engine: str, language: Union[str, List[str]] = "zh") -> DocumentConverter:
    """根据指定的引擎获取OCR转换器
    
    参数:
        engine: OCR引擎名称
        language: 语言代码或语言代码列表，'auto'表示自动检测，'zh'表示中文
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_page_images = True
    
    # 配置OCR选项
    if engine == "rapid":
        # RapidOCR已默认内置中英文支持
        ocr_options = RapidOcrOptions()
        # 默认就支持中英文，无需特别设置
        ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options = ocr_options
    
    elif engine == "mac":
        # Mac OCR 支持
        lang_codes = ["zh-Hans"] if language == "zh" else (
            language if isinstance(language, list) else [language]
        )
        ocr_options = OcrMacOptions(lang=lang_codes)
        ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options = ocr_options
    
    elif engine == "easy":
        # EasyOCR 支持
        lang_codes = ["ch_sim"] if language == "zh" else (
            language if isinstance(language, list) else [language]
        )
        ocr_options = EasyOcrOptions(lang=lang_codes)
        ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options = ocr_options
    
    elif engine == "tesseract":
        # Tesseract CLI
        lang_codes = ["chi_sim"] if language == "zh" else (
            language if isinstance(language, list) else [language]
        )
        ocr_options = TesseractCliOcrOptions(lang=lang_codes)
        ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options = ocr_options
    
    else:
        # 默认使用RapidOCR
        logger.warning(f"未知OCR引擎 '{engine}'，使用RapidOCR")
        ocr_options = RapidOcrOptions()
        ocr_options.force_full_page_ocr = True
        pipeline_options.ocr_options = ocr_options
    
    # 创建转换器
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options
            )
        }
    )