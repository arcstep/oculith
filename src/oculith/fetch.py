import os
import hashlib
from pathlib import Path
from typing import Optional
import pandas as pd
import logging
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from .common import convert_file
from .parquet import save_to_parquet
from docling.pipeline.simple_pipeline import SimplePipeline
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

logger = logging.getLogger(__name__)

def fetch_text_from_document(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    output_path: Optional[str] = None
) -> str:
    """标准处理：提取文档文本"""
    
    # 检查是否是Markdown文件
    is_markdown = False
    if content_type == "file" or content_type == "auto":
        if os.path.exists(content) and (content.endswith('.md') or file_type == 'md'):
            is_markdown = True
    
    # 如果是Markdown文件，直接读取内容
    if is_markdown:
        return _handle_markdown_file(content, output_path)
    
    # 配置PDF选项
    pdf_opts = PdfPipelineOptions()
    pdf_opts.images_scale = 2.0
    pdf_opts.generate_page_images = True
    
    # 创建支持多格式的文档转换器
    doc_converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.HTML,
            InputFormat.PPTX,
            InputFormat.IMAGE,
            InputFormat.MD,
            InputFormat.CSV,
            InputFormat.ASCIIDOC
        ],
        format_options={
            # PDF格式配置
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pdf_opts,
                pipeline_cls=StandardPdfPipeline,
                backend=PyPdfiumDocumentBackend  # 使用推荐的后端
            ),
            # DOCX格式配置
            InputFormat.DOCX: WordFormatOption(
                pipeline_cls=SimplePipeline  # DOCX使用SimplePipeline
            )
        }
    )
    
    # 转换文档
    res = convert_file(content, content_type, file_type, doc_converter)
    
    # 保存为parquet
    if not output_path:
        from datetime import datetime
        output_dir = Path("./docling/parquet")
        output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = output_dir / f"doc_{now}.parquet"
    
    save_to_parquet(res, output_path)
    
    return output_path

def _handle_markdown_file(file_path: str, output_path: str) -> str:
    """特殊处理Markdown文件"""
    # 读取Markdown内容
    with open(file_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 创建简化的DataFrame
    df = pd.DataFrame([{
        "contents_md": md_content,
        "contents": md_content,  # 纯文本版本 
        "document": os.path.basename(file_path),
        "hash": hashlib.md5(md_content.encode()).hexdigest(),
        "extra": {"page_num": 1}
    }])
    
    # 保存为parquet
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path)
    
    logger.info(f"Markdown文件已保存为parquet: {output_path}")
    return str(output_path)