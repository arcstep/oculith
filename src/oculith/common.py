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

def convert_pdf(
    content: str,
    content_type: str,
    file_type: str,
    converter
):
    """
    通用PDF转换：支持本地文件、URL和Base64三种输入。
    返回 DocumentConverter.convert 的结果。
    """
    # URL 直接转换
    if content_type == 'url' or (content_type == 'auto' and content.startswith(('http://', 'https://'))):
        return converter.convert(content)

    # Base64 解码
    if content_type == 'base64' or (content_type == 'auto' and is_base64(content)):
        decoded = base64.b64decode(content)
        if not file_type:
            file_type = ''
    else:
        # 本地文件读取
        if os.path.exists(content):
            decoded = Path(content).read_bytes()
            if not file_type:
                file_type = Path(content).suffix.lstrip('.')
        else:
            # 作为URL尝试
            return converter.convert(content)

    # 写入临时文件并转换
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{file_type}" if file_type else ".pdf"
        ) as tmp:
            tmp.write(decoded)
            tmp_path = tmp.name
        return converter.convert(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)