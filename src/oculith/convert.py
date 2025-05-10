import os
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, Union, Literal, List

from voidrail import create_app
from .config import get_document_path, ensure_output_dir
from .fetch import fetch_text_from_document
from .ocr import ocr_text_from_document
from .exporter import export_markdown, chunk_markdown
from .chunker import get_chunker

# 日志
logger = logging.getLogger(__name__)

# 创建Celery应用
app = create_app("docling")

@app.task(name="docling.convert")
def convert(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    document_id: Optional[str] = None,
    use_ocr: bool = False,
    ocr_engine: str = "rapid",
    return_type: Literal["markdown", "markdown_embedded", "chunks"] = "markdown",
    force_convert: bool = False,
    max_chunk_size: int = 1000,
    overlap: int = 100,
    chunk_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    统一的文档转换入口
    
    参数:
        content: 文档内容(路径、URL或Base64)
        content_type: 内容类型(auto/file/url/base64)
        file_type: 文件类型(pdf/docx等)
        document_id: 文档ID，用于命名和目录组织
        use_ocr: 是否使用OCR处理
        ocr_engine: OCR引擎(rapid/tesseract/easyocr)
        return_type: 返回类型(markdown/markdown_embedded/chunks)
        force_convert: 是否强制重新转换
        max_chunk_size: 切片的最大token数
        overlap: 切片重叠token数
        chunk_metadata: 传递给切片器的元数据
        
    返回:
        包含转换结果的字典，根据return_type不同而变化
    """
    # 如果未提供document_id，生成hash值
    if not document_id:
        content_hash = hashlib.md5(content.encode() if isinstance(content, str) else content).hexdigest()
        document_id = f"{content_hash}"
    
    # 获取文档保存路径
    doc_path = get_document_path(document_id)
    parquet_path = doc_path.with_suffix('.parquet')
    
    # 检查缓存文件是否存在
    parquet_exists = parquet_path.exists()
    if parquet_exists and not force_convert:
        logger.info(f"使用已存在的转换结果: {parquet_path}")
        result_path = str(parquet_path)
    else:
        # 执行新的转换
        logger.info(f"开始转换文档，{'使用OCR' if use_ocr else '不使用OCR'}")
        
        if use_ocr:
            # 使用OCR处理
            result_path = ocr_text_from_document(
                content, 
                content_type, 
                file_type,
                output_path=str(parquet_path),
                engine=ocr_engine
            )
        else:
            # 使用标准处理
            result_path = fetch_text_from_document(
                content, 
                content_type, 
                file_type,
                output_path=str(parquet_path)
            )
    
    # 根据请求的返回类型生成输出
    response = {
        "document_id": document_id,
        "from_cache": parquet_exists and not force_convert
    }
    
    if return_type == "chunks":
        # 返回文档切片
        chunk_result = chunk_markdown(result_path, max_chunk_size, overlap, chunk_metadata or {})
        response["chunks"] = chunk_result
    elif return_type == "markdown_embedded":
        # 返回带图片的Markdown
        markdown_content = export_markdown(result_path, markdown_type="embedded")
        response["markdown_content"] = markdown_content
    else:  # markdown
        # 返回纯文本Markdown
        markdown_content = export_markdown(result_path, markdown_type="reference")
        response["markdown_content"] = markdown_content
        
    return response
