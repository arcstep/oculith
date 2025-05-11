import os
import sys
import hashlib
import logging
import asyncio
import traceback
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
    ocr: Optional[str] = None,  # None表示不使用OCR，字符串值表示引擎名称
    language: str = "zh",       # 默认中文
    return_type: Literal["markdown", "markdown_embedded", "chunks"] = "markdown",
    force_convert: bool = False,
    chunker_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    统一的文档转换入口
    
    参数:
        content: 文档内容(路径、URL或Base64)
        content_type: 内容类型(auto/file/url/base64)
        file_type: 文件类型(pdf/docx等)
        document_id: 文档ID，用于命名和目录组织
        ocr: OCR引擎名称(mac/rapid/tesseract/easy等)，None表示不使用OCR
        language: 语言代码或语言代码列表，'auto'表示自动检测，'zh'表示中文
        return_type: 返回类型(markdown/markdown_embedded/chunks)
        force_convert: 是否强制重新转换
        chunker_config: 切片配置，包含以下可选字段:
            - max_chunk_size: 每个切片的最大token数
            - overlap: 切片重叠token数
            - metadata: 传递给切片器的元数据
            - model_name: 使用的tiktoken模型名称
        
    返回:
        包含转换结果的字典，根据return_type不同而变化
    """
    try:
        # 检测图片类型，自动选择OCR引擎
        image_extensions = ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff', 'webp']
        
        # 从文件路径或file_type推断文件类型
        detected_type = ""
        if content_type in ("file", "auto") and os.path.exists(content):
            detected_type = Path(content).suffix.lower().lstrip('.')
        else:
            detected_type = file_type.lower()
        
        # 如果是图片类型且未指定OCR引擎，自动选择
        if detected_type in image_extensions and ocr is None:
            # 检测是否为Mac系统
            if sys.platform == 'darwin':
                ocr = "rapid"  # mac引擎在fork模式下会崩溃，改用rapid
            else:
                ocr = "rapid"
            logger.info(f"检测到图片类型 {detected_type}，自动选择OCR引擎: {ocr}")
        
        # 验证文件是否存在（如果是本地文件）
        if content_type in ("file", "auto") and not os.path.exists(content):
            return {
                "error": True,
                "message": f"文件不存在: {content}",
                "error_type": "FileNotFoundError"
            }
        
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
            logger.info(f"开始转换文档，{'使用OCR引擎: ' + ocr if ocr else '不使用OCR'}")
            
            if ocr:
                # 使用OCR处理
                result_path = ocr_text_from_document(
                    content, 
                    content_type, 
                    file_type,
                    output_path=str(parquet_path),
                    engine=ocr,
                    language=language
                )
            else:
                # 使用标准处理
                result_path = fetch_text_from_document(
                    content, 
                    content_type, 
                    file_type,
                    output_path=str(parquet_path)
                )
        
        # 准备响应
        response = {
            "document_id": document_id,
            "from_cache": parquet_exists and not force_convert
        }
        
        # 处理切片器配置
        chunker_config = chunker_config or {}
        
        # 根据请求的返回类型生成输出
        if return_type == "chunks":
            # 返回文档切片
            chunk_result = chunk_markdown(
                result_path, 
                **chunker_config  # 直接传递整个配置字典
            )
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
    except Exception as e:
        logger.exception(f"文档转换失败: {str(e)}")
        return {
            "error": True,
            "message": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
