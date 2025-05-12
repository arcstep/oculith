import os
import mimetypes
import logging
import tempfile
from pathlib import Path
from PIL import Image
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# 初始化mimetype
mimetypes.init()

# 文件类型映射
MIME_TO_TYPE = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'text/html': 'html',
    'text/markdown': 'md',
    'text/csv': 'csv',
    'text/plain': 'txt',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/bmp': 'bmp',
    'image/tiff': 'tiff',
    'image/webp': 'webp',
}

# 图片文件扩展名
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'}

def detect_file_type(file_path: str) -> str:
    """
    检测文件类型
    
    参数:
        file_path: 文件路径
        
    返回:
        文件类型字符串 (pdf, docx, jpg 等)
    """
    # 首先通过文件扩展名判断
    ext = Path(file_path).suffix.lower().lstrip('.')
    if ext:
        return ext
    
    # 尝试通过mime类型判断
    try:
        import magic  # 如果安装了python-magic
        mime = magic.Magic(mime=True).from_file(file_path)
        if mime in MIME_TO_TYPE:
            return MIME_TO_TYPE[mime]
    except (ImportError, Exception) as e:
        logger.debug(f"使用magic检测文件类型失败: {e}")
    
    # 退回到mimetypes
    mime, _ = mimetypes.guess_type(file_path)
    if mime in MIME_TO_TYPE:
        return MIME_TO_TYPE[mime]
    
    # 如果都失败了，返回空字符串
    return ""

def is_image_file(file_type: str) -> bool:
    """判断是否为图片文件类型"""
    return file_type.lower() in IMAGE_EXTENSIONS

def convert_image_to_pdf(image_path: str) -> Tuple[str, bool]:
    """
    将图片转换为PDF
    
    参数:
        image_path: 图片文件路径
        
    返回:
        (pdf文件路径, 是临时文件)
    """
    try:
        # 打开图片
        img = Image.open(image_path)
        
        # 创建临时PDF文件
        pdf_path = os.path.splitext(image_path)[0] + ".pdf"
        if os.path.exists(pdf_path):
            # 如果PDF已存在，创建一个临时文件
            fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            is_temp = True
        else:
            is_temp = False
        
        # 转换为RGB模式（如果是RGBA）
        if img.mode == 'RGBA':
            img = img.convert('RGB')
            
        # 保存为PDF
        img.save(pdf_path, "PDF", resolution=100.0)
        logger.info(f"图片转换为PDF成功: {image_path} -> {pdf_path}")
        
        return pdf_path, is_temp
    except Exception as e:
        logger.exception(f"图片转PDF失败: {e}")
        raise
