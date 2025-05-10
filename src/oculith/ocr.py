# src/oculith/ocr.py
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractOcrOptions,
    TesseractCliOcrOptions
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from .parquet import save_to_parquet
from .common import convert_pdf

# 日志
logger = logging.getLogger(__name__)

def ocr_text_from_document(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    output_path: Optional[str] = None,
    engine: str = "rapid",
    language: str = "auto"
) -> str:
    """使用OCR处理文档"""
    # 获取OCR转换器
    converter = get_ocr_converter(engine, language)
    
    # 转换文档
    res = convert_pdf(content, content_type, file_type, converter)
    
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

def get_ocr_converter(engine: str, language: str = "auto") -> DocumentConverter:
    """根据指定的引擎获取OCR转换器"""
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_page_images = True
    
    # 配置OCR选项
    if engine == "rapid":
        # RapidOCR配置
        try:
            from huggingface_hub import snapshot_download
            download_path = snapshot_download(repo_id="SWHL/RapidOCR")
            
            lang_prefix = "en" if language == "en" else "ch"
            det_path = os.path.join(download_path, "PP-OCRv4", f"{lang_prefix}_PP-OCRv3_det_infer.onnx")
            rec_path = os.path.join(download_path, "PP-OCRv4", f"{lang_prefix}_PP-OCRv4_rec_infer.onnx")
            cls_path = os.path.join(download_path, "PP-OCRv3", "ch_ppocr_mobile_v2.0_cls_train.onnx")
            
            pipeline_options.ocr_options = RapidOcrOptions(
                det_model_path=det_path,
                rec_model_path=rec_path,
                cls_model_path=cls_path
            )
        except Exception as e:
            logger.error(f"RapidOCR配置失败: {e}")
            # 回退到Tesseract
            pipeline_options.ocr_options = TesseractOcrOptions(lang=[language])
    
    elif engine == "tesseract":
        # Tesseract Python API
        pipeline_options.ocr_options = TesseractOcrOptions(lang=[language])
    
    elif engine == "tesseract_cli":
        # Tesseract CLI
        pipeline_options.ocr_options = TesseractCliOcrOptions(lang=[language])
    
    else:
        # 默认使用标准OCR
        logger.warning(f"未知OCR引擎 '{engine}'，使用默认引擎")
    
    # 创建转换器
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options
            )
        }
    )