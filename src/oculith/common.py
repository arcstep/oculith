# src/oculith/common.py
import os
import tempfile
import base64
import re
from pathlib import Path
import logging
from typing import Optional
from .file_utils import detect_file_type, is_image_file, convert_image_to_pdf

logger = logging.getLogger(__name__)

def is_base64(content: str) -> bool:
    """简单判断是否为Base64字符串"""
    if not re.match(r'^[A-Za-z0-9+/]+={0,2}$', content):
        return False
    return len(content) % 4 == 0

def convert_file(
    content: str,
    content_type: str,
    file_type: str,
    converter
):
    """
    通用文档转换：支持本地文件、URL和Base64三种输入，以及多种文档格式。
    根据 file_type 或原始文件后缀生成临时文件后缀，返回 DocumentConverter.convert 的结果。
    """
    # URL 直接转换
    if content_type == 'url' or (content_type == 'auto'
        and content.startswith(('http://', 'https://'))
    ):
        return converter.convert(content)

    # Base64 解码并写入临时文件
    if content_type == 'base64' or (content_type == 'auto' and is_base64(content)):
        decoded = base64.b64decode(content)
        suffix = f".{file_type}" if file_type else ""
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(decoded)
                tmp_path = tmp.name
            return converter.convert(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # 本地文件直接转换
    if os.path.exists(content):
        return converter.convert(content)

    # 其他情况当作URL转换
    return converter.convert(content)

def prepare_file(content: str, content_type: str = "auto", file_type: str = "") -> tuple[str, bool, str, bool]:
    """
    准备文件以供docling处理
    
    参数:
        content: 文档内容(路径、URL或Base64)
        content_type: 内容类型(auto/file/url/base64)
        file_type: 文件类型(pdf/docx等)，如果提供则优先使用
    
    返回:
        (文件路径, 是否为临时文件, 检测到的文件类型, 是否为图片转换的PDF)
    """
    temp_file_path = None
    is_temp_file = False
    detected_type = ""
    is_converted_from_image = False
    
    try:
        # 本地文件处理
        if content_type == "file" or (content_type == "auto" and os.path.exists(content)):
            temp_file_path = os.path.abspath(content)
            is_temp_file = False
            
            # 检测文件类型
            if not file_type:
                detected_type = detect_file_type(temp_file_path)
            else:
                detected_type = file_type
                
            # 如果是图片，转换为PDF
            if is_image_file(detected_type):
                logger.info(f"检测到图片文件: {temp_file_path}，将自动转换为PDF")
                pdf_path, is_pdf_temp = convert_image_to_pdf(temp_file_path)
                temp_file_path = pdf_path
                is_temp_file = is_pdf_temp
                detected_type = "pdf"
                is_converted_from_image = True
                
            return temp_file_path, is_temp_file, detected_type, is_converted_from_image

        # URL处理
        if content_type == 'url' or (content_type == 'auto' and content.startswith(('http://', 'https://'))):
            import tempfile
            import requests
            
            # 检测文件类型
            if file_type:
                detected_type = file_type
                suffix = f".{file_type}"
            else:
                # 尝试从URL中获取文件类型
                from urllib.parse import urlparse
                path = urlparse(content).path
                ext = os.path.splitext(path)[1].lstrip('.')
                detected_type = ext if ext else ""
                suffix = f".{ext}" if ext else ""
            
            # 下载文件到临时位置
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                response = requests.get(content, stream=True)
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                temp_file_path = tmp.name
                is_temp_file = True
            
            # 如果没有检测到类型，现在检测下载的文件
            if not detected_type:
                detected_type = detect_file_type(temp_file_path)
                
            # 如果是图片，转换为PDF
            if is_image_file(detected_type):
                logger.info(f"检测到图片文件: {temp_file_path}，将自动转换为PDF")
                pdf_path, _ = convert_image_to_pdf(temp_file_path)
                # 删除原临时文件，使用转换后的PDF
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                temp_file_path = pdf_path
                detected_type = "pdf"
                is_converted_from_image = True
                
            return temp_file_path, is_temp_file, detected_type, is_converted_from_image
        
        # Base64处理
        if content_type == 'base64' or (content_type == 'auto' and is_base64(content)):
            import tempfile
            import base64
            
            # 使用指定的文件类型或空
            detected_type = file_type
            suffix = f".{file_type}" if file_type else ""
            
            # 解码并写入临时文件
            decoded = base64.b64decode(content)
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(decoded)
                temp_file_path = tmp.name
                is_temp_file = True
            
            # 如果没有指定类型，检测文件类型
            if not detected_type:
                detected_type = detect_file_type(temp_file_path)
                
            # 如果是图片，转换为PDF
            if is_image_file(detected_type):
                logger.info(f"检测到图片文件: {temp_file_path}，将自动转换为PDF")
                pdf_path, _ = convert_image_to_pdf(temp_file_path)
                # 删除原临时文件，使用转换后的PDF
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                temp_file_path = pdf_path
                detected_type = "pdf"
                is_converted_from_image = True
                
            return temp_file_path, is_temp_file, detected_type, is_converted_from_image
        
        # 无法处理的情况
        raise ValueError(f"无法处理的内容类型: {content_type}")
        
    except Exception as e:
        # 出错时清理临时文件
        if temp_file_path and os.path.exists(temp_file_path) and is_temp_file:
            try:
                os.unlink(temp_file_path)
            except:
                pass
        raise