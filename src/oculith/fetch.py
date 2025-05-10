# src/oculith/multimodal.py
import logging
import tempfile
import base64
import os
import time
import datetime

from pathlib import Path
from typing import Optional
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.utils.export import generate_multimodal_pages
from docling.utils.utils import create_hash

import pandas as pd


from .common import convert_pdf
from .parquet import save_to_parquet

# 日志
logger = logging.getLogger(__name__)

def fetch_text_from_document(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    output_path: Optional[str] = None,
    image_scale: float = 2.0,
    generate_page_images: bool = True,
) -> str:
    """处理文档并生成多模态数据"""
    # 配置转换器
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.images_scale = image_scale
    pipeline_opts.generate_page_images = generate_page_images
    
    doc_converter = DocumentConverter(
        format_options={ 
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts) 
        }
    )
    
    # 转换文档
    res = convert_pdf(content, content_type, file_type, doc_converter)
    
    # 生成输出路径
    if not output_path:
        output_dir = Path("./docling/parquet")
        output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = output_dir / f"doc_{now}.parquet"
    
    # 将结果保存为parquet
    save_to_parquet(res, output_path)
    
    return output_path
