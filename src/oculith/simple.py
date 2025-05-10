from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import DoclingDocument
from voidrail import create_app
from .common import convert_pdf, format_output

import logging
import tempfile
import base64
import os

# 设置日志记录器
logger = logging.getLogger(__name__)

app = create_app("docling")

def save_markdown(document: DoclingDocument, path: str) -> str:
    """
    Save as markdown text file.
    """
    if not path.endswith(".md"):
        path = path + ".md"
    with open(path, "w") as f:
        f.write(document.export_to_markdown())
    return path

def save_text(document: DoclingDocument, path: str) -> str:
    """
    Save as text file.
    """
    if not path.endswith(".txt"):
        path = path + ".txt"
    with open(path, "w") as f:
        f.write(document.export_to_text())
    return path

def save_html(document: DoclingDocument, path: str) -> str:
    """
    Save as html file.
    """
    if not path.endswith(".html"):
        path = path + ".html"
    with open(path, "w") as f:
        f.write(document.export_to_html())
    return path

def is_base64(content: str) -> bool:
    """检查字符串是否可能是base64编码"""
    import re
    # 基本的base64格式检查
    if not re.match(r'^[A-Za-z0-9+/]+={0,2}$', content):
        return False
    # 长度是否是4的倍数
    if len(content) % 4 != 0:
        return False
    return True

docling_converter = DocumentConverter()

@app.task(name="docling.simple")
def convert(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    output_format: str = "markdown"
) -> str:
    """
    统一的转换方法，智能处理不同类型的输入。
    """
    # 调用公共PDF转换工具
    res = convert_pdf(content, content_type, file_type, docling_converter)
    # 导出指定格式输出
    return format_output(res, output_format)
