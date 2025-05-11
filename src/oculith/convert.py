import os
import sys
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union, Literal
import json
import base64
from docling_core.types.doc import ImageRefMode, PictureItem
import io

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, VlmPipelineOptions, ApiVlmOptions,
    RapidOcrOptions, TesseractCliOcrOptions, OcrMacOptions, EasyOcrOptions
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline

from voidrail import create_app

from .common import convert_file, prepare_file

logger = logging.getLogger(__name__)

# 创建Celery应用
app = create_app("docling")

@app.task(name="docling.convert")
def convert(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    document_id: Optional[str] = None,
    pipeline_type: Literal["standard", "simple", "vlm"] = "auto",
    ocr: Optional[str] = None,
    language: str = "zh",
    return_type: Literal["markdown", "markdown_embedded", "dict_with_images"] = "dict_with_images",
    images_scale: float = 2.0,
    generate_images: Literal["none", "page", "picture", "all"] = "picture",
    advanced_features: Optional[Dict[str, bool]] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """统一的文档转换入口
    
    参数:
        content: 文档内容(路径、URL或Base64)
        content_type: 内容类型(auto/file/url/base64)
        file_type: 文件类型(pdf/docx等)
        document_id: 文档ID
        pipeline_type: 处理管道类型 (auto自动检测，standard适用于PDF/图片，simple适用于其他格式，vlm使用视觉语言模型)
        ocr: OCR引擎名称，None表示根据文件类型自动决定
        language: 语言代码
        return_type: 返回类型
        images_scale: 图像缩放比例
        generate_images: 图像生成控制
        advanced_features: 高级特性控制
        output_dir: 输出文件路径
    """
    try:
        # 获取文档ID
        if not document_id:
            content_hash = hashlib.md5(content.encode() if isinstance(content, str) else content).hexdigest()
            document_id = f"{content_hash}"
        
        # 使用convert_file预处理 - 这将准备文件并识别格式
        temp_file_path = None
        is_temp_file = False
        
        try:
            temp_file_path, is_temp_file = prepare_file(content, content_type, file_type)
            
            # 根据管道类型配置选项
            if pipeline_type in ["standard", "auto"]:
                # 对于标准和自动模式，创建带有正确选项的PDF转换器
                pipeline_options = PdfPipelineOptions()
                pipeline_options.images_scale = images_scale
                
                # 根据generate_images设置图像生成选项
                if generate_images == "none":
                    pipeline_options.generate_page_images = False
                    pipeline_options.generate_picture_images = False
                elif generate_images == "page":
                    pipeline_options.generate_page_images = True
                    pipeline_options.generate_picture_images = False
                elif generate_images == "picture":
                    pipeline_options.generate_page_images = False
                    pipeline_options.generate_picture_images = True
                elif generate_images == "all":
                    pipeline_options.generate_page_images = True
                    pipeline_options.generate_picture_images = True
                
                # 应用高级特性
                if advanced_features:
                    for feature, enabled in advanced_features.items():
                        if hasattr(pipeline_options, feature):
                            setattr(pipeline_options, feature, enabled)
                            
                # 直接使用配置好的选项创建新的转换器
                converter = get_pdf_converter(
                    ocr=ocr, 
                    language=language, 
                    pipeline_options=pipeline_options
                )
            elif pipeline_type == "simple":
                if file_type:
                    # 根据文件扩展名获取格式
                    converter = get_simple_converter(file_type)
                else:
                    # 默认简单转换器
                    converter = get_simple_converter()
            elif pipeline_type == "vlm":
                converter = get_vlm_converter()
            else:
                # 自动检测
                ext = Path(temp_file_path).suffix.lower()[1:] if Path(temp_file_path).suffix else file_type
                if ext in ["pdf", "jpg", "jpeg", "png", "gif", "bmp", "tiff"]:
                    converter = get_pdf_converter(ocr=ocr, language=language)
                else:
                    converter = get_simple_converter(ext)
            
            # 执行转换
            res = converter.convert(temp_file_path)
            
            # 根据返回类型处理结果
            if return_type == "dict_with_images":
                # 提取插图和Markdown
                result = extract_images_with_markdown(res, output_dir)
                
                return {
                    "document_id": document_id,
                    "markdown_content": result["markdown"],
                    "images": result["images"]
                }
            else:
                # 直接从document生成Markdown
                markdown_type = ImageRefMode.EMBEDDED if return_type == "markdown_embedded" else ImageRefMode.REFERENCED
                markdown_content = res.document.export_to_markdown(image_mode=markdown_type)
                
                # 如果提供了输出路径，保存到文件
                if output_dir:
                    output_dir = Path(output_dir)
                    output_dir.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_dir, "w", encoding="utf-8") as f:
                        f.write(markdown_content)
                    logger.info(f"Markdown内容已保存至: {output_dir}")
                
                return {
                    "document_id": document_id,
                    "markdown_content": markdown_content,
                    "output_file": str(output_dir) if output_dir else None
                }
        
        finally:
            # 只删除临时创建的文件
            if temp_file_path and os.path.exists(temp_file_path) and is_temp_file:
                os.unlink(temp_file_path)

    except Exception as e:
        logger.exception(f"文档转换失败: {str(e)}")
        import traceback
        return {
            "error": True,
            "message": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }

def get_pdf_converter(ocr: Optional[str] = None, language: str = "zh", 
                     pipeline_options: Optional[PdfPipelineOptions] = None) -> DocumentConverter:
    """获取PDF处理转换器"""
    # 如果没有提供选项，创建默认选项
    if pipeline_options is None:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True  # 启用图像提取
    
    # 如果指定OCR，配置OCR选项
    if ocr:
        pipeline_options.do_ocr = True
        
        # 配置OCR选项
        if ocr == "rapid":
            ocr_options = RapidOcrOptions(force_full_page_ocr=True)
        elif ocr == "mac":
            lang_codes = ["zh-Hans"] if language == "zh" else [language]
            ocr_options = OcrMacOptions(lang=lang_codes, force_full_page_ocr=True)
        elif ocr == "tesseract":
            lang_codes = ["chi_sim"] if language == "zh" else [language]
            ocr_options = TesseractCliOcrOptions(lang=lang_codes, force_full_page_ocr=True)
        elif ocr == "easy":
            lang_codes = ["ch_sim"] if language == "zh" else [language]
            ocr_options = EasyOcrOptions(lang=lang_codes, force_full_page_ocr=True)
        else:
            # 默认使用RapidOCR
            ocr_options = RapidOcrOptions(force_full_page_ocr=True)
            
        pipeline_options.ocr_options = ocr_options
    
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            ),
            InputFormat.IMAGE: PdfFormatOption(
                pipeline_options=pipeline_options,
            ),
        }
    )

def get_simple_converter(input_format: Optional[InputFormat] = None) -> DocumentConverter:
    """获取SimplePipeline处理其他格式的转换器"""
    # 支持的所有格式
    allowed_formats = [
        InputFormat.DOCX, InputFormat.HTML, InputFormat.PPTX,
        InputFormat.MD, InputFormat.CSV, InputFormat.XLSX,
        InputFormat.ASCIIDOC
    ]
    
    # 如果指定了具体格式，只允许该格式
    if input_format and input_format in allowed_formats:
        allowed_formats = [input_format]
    
    return DocumentConverter(allowed_formats=allowed_formats)

def get_vlm_converter() -> DocumentConverter:
    """获取基于视觉语言模型的转换器"""
    vlm_options = VlmPipelineOptions(
        enable_remote_services=True
    )
    
    # 使用Ollama作为默认VLM
    vlm_options.vlm_options = ApiVlmOptions(
        url="http://localhost:11434/v1/chat/completions",
        params=dict(model="granite3.2-vision:2b"),
        prompt="OCR the full page to markdown.",
        timeout=90,
    )
    
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=vlm_options,
                pipeline_cls=VlmPipeline,
            ),
            InputFormat.IMAGE: PdfFormatOption(
                pipeline_options=vlm_options,
                pipeline_cls=VlmPipeline,
            ),
        }
    )

def extract_images_with_markdown(conv_res, output_dir=None):
    """提取文档中的插图和Markdown内容"""
    result = {
        "markdown": "",
        "images": {}
    }
    
    doc_filename = Path(conv_res.input.file).stem
    
    # 如果需要保存到本地
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用官方方法直接保存Markdown和图片
        md_filename = output_dir / f"{doc_filename}.md"
        conv_res.document.save_as_markdown(md_filename, image_mode=ImageRefMode.REFERENCED)
        
        # 读取生成的Markdown
        with open(md_filename, "r", encoding="utf-8") as f:
            result["markdown"] = f.read()
            
        # 提取并收集图片信息
        artifacts_dir = output_dir / f"{doc_filename}_artifacts"
        if artifacts_dir.exists():
            for img_path in artifacts_dir.glob("*.png"):
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    result["images"][img_path.name] = img_b64
    else:
        # 直接使用export_to_markdown方法 - 这不需要文件路径
        result["markdown"] = conv_res.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
            
        # 手动提取图片
        try:
            for element, _level in conv_res.document.iterate_items():
                if isinstance(element, PictureItem):
                    try:
                        image = element.get_image(conv_res.document)
                        img_id = hash(str(image))
                        img_name = f"image_{img_id}.png"
                        
                        with io.BytesIO() as buffer:
                            image.save(buffer, format="PNG")
                            img_bytes = buffer.getvalue()
                            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                            result["images"][img_name] = img_b64
                    except Exception as e:
                        logger.warning(f"提取图片失败: {e}")
        except Exception as e:
            # 某些格式可能没有iterate_items方法
            logger.debug(f"提取图片过程中遇到异常 (可能是不支持图像的格式): {e}")
    
    return result
