# src/oculith/common.py
import os
import tempfile
import base64
import re
from pathlib import Path
import logging
from typing import Optional

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

def prepare_file(content: str, content_type: str = "auto", file_type: str = "") -> tuple[str, bool]:
    """准备文件以供docling处理，返回(文件路径, 是否为临时文件)"""
    if content_type == "file" or (content_type == "auto" and os.path.exists(content)):
        # 返回绝对路径，但标记为非临时文件
        return os.path.abspath(content), False

    # URL处理 - 创建临时文件
    if content_type == 'url' or (content_type == 'auto' and content.startswith(('http://', 'https://'))):
        import tempfile
        import requests
        
        # 下载文件到临时位置
        suffix = f".{file_type}" if file_type else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            response = requests.get(content, stream=True)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            return tmp.name, True
    
    # Base64处理 - 创建临时文件
    if content_type == 'base64' or (content_type == 'auto' and is_base64(content)):
        import tempfile
        import base64
        
        # 解码并写入临时文件
        suffix = f".{file_type}" if file_type else ""
        decoded = base64.b64decode(content)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(decoded)
            return tmp.name, True
    
    # 无法处理的情况
    raise ValueError(f"无法处理的内容类型: {content_type}")