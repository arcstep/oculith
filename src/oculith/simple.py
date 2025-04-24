from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import DoclingDocument
from voidrail import ServiceDealer, service_method

import logging

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
    def local_convert(self, from_path: str, format: str = "markdown") -> str:
        """
        Convert a local document to markdown or text or html.
        """
        result = self.converter.convert(from_path)
        self.logger.info(result)
        if format == "markdown":
            yield result.document.export_to_markdown()
        elif format == "text":
            yield result.document.export_to_text()
        elif format == "html":
            yield result.document.export_to_html()
        else:
            raise ValueError(f"Invalid format: {format}")
    
    @service_method
    def remote_convert(self, web_path: str, format: str = "markdown") -> str:
        """
        Convert a web document to markdown or text or html.
        """
        result = self.converter.convert(web_path)
        self.logger.info(result)
        if format == "markdown":
            yield result.document.export_to_markdown()
        elif format == "text":
            yield result.document.export_to_text()
        elif format == "html":
            yield result.document.export_to_html()
        else:
            raise ValueError(f"Invalid format: {format}")
