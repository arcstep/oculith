from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import DoclingDocument
from voidrail import ServiceDealer, service_method

import logging
import tempfile
import base64
import os

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

class SimpleDocling(ServiceDealer):
    """
    SimpleDocling is a simple service that converts a document to markdown.
    """

    def __init__(self, *args, logger_level: int = logging.INFO, **kwargs):
        super().__init__(*args, **kwargs)
        self.converter = DocumentConverter()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logger_level)

    @service_method
    def convert(
        self,
        content: str,
        content_type: str = "url",
        file_type: str = "",
        output_format: str = "markdown"
    ) -> str:
        """
        统一的转换方法，支持网络资源和base64编码的文件内容。
        
        参数:
            content: URL或base64编码的文件内容
            output_format: 输出格式，支持"markdown"、"text"和"html"
            content_type: 内容类型，"url"或"base64"
            file_type: 文件类型（扩展名），仅在处理base64编码时使用
        """
        if content_type == "base64":
            # 处理base64编码的文件内容
            try:
                # 解码base64内容
                decoded_content = base64.b64decode(content)
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}" if file_type else "") as temp_file:
                    temp_path = temp_file.name
                    temp_file.write(decoded_content)
                
                # 转换文件
                try:
                    result = self.converter.convert(temp_path)
                    self.logger.info(f"成功转换base64编码文件")
                finally:
                    # 确保删除临时文件
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            except Exception as e:
                self.logger.error(f"处理base64内容时出错: {str(e)}")
                raise ValueError(f"处理base64内容失败: {str(e)}")
        else:
            # 处理URL
            try:
                result = self.converter.convert(content)
                self.logger.info(f"成功转换URL: {content}")
            except Exception as e:
                self.logger.error(f"处理URL时出错: {str(e)}")
                raise ValueError(f"处理URL失败: {str(e)}")
        
        # 根据请求的格式返回结果
        if output_format == "markdown":
            yield result.document.export_to_markdown()
        elif output_format == "text":
            yield result.document.export_to_text()
        elif output_format == "html":
            yield result.document.export_to_html()
        else:
            raise ValueError(f"不支持的输出格式: {foroutput_formatmat}")
