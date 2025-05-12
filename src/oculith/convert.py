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
import time
from pypdf import PdfReader

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, VlmPipelineOptions, ApiVlmOptions, ResponseFormat,
    RapidOcrOptions, TesseractCliOcrOptions, OcrMacOptions, EasyOcrOptions
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline

from voidrail import create_app

from .common import convert_file, prepare_file
from .vlm_config import get_vlm_pipeline_options

logger = logging.getLogger(__name__)

# 创建Celery应用
app = create_app("docling")

@app.task(name="docling.convert")
def convert(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    document_id: Optional[str] = None,
    pipeline: Literal["standard", "simple", "vlm"] = "auto",
    ocr: Optional[str] = None,
    language: str = "zh",
    return_type: Literal["markdown", "markdown_embedded", "dict_with_images"] = "markdown",
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
        pipeline: 处理管道类型 (auto自动检测，standard适用于PDF/图片，simple适用于其他格式，vlm使用视觉语言模型)
        ocr: OCR引擎名称，None表示根据文件类型自动决定
        language: 语言代码
        return_type: 返回类型
        images_scale: 图像缩放比例
        generate_images: 图像生成控制
        advanced_features: 高级特性控制
        output_dir: 输出文件路径
    """
    model_info = {
        "pipeline": pipeline,
        "provider": None,
        "model": None,
        "ocr_engine": ocr,
    }
    
    try:
        # 获取文档ID
        if not document_id:
            content_hash = hashlib.md5(content.encode() if isinstance(content, str) else content).hexdigest()
            document_id = f"{content_hash}"
        
        logger.info(f"开始处理文档 ID: {document_id}, 管道类型: {pipeline}, OCR引擎: {ocr}")
        
        # 使用convert_file预处理 - 这将准备文件并识别格式
        temp_file_path = None
        is_temp_file = False
        
        try:
            temp_file_path, is_temp_file, detected_type, is_converted_from_image = prepare_file(content, content_type, file_type)
            logger.info(f"文件准备完成: {temp_file_path}, 检测到文件类型: {detected_type}, 是否图片转PDF: {is_converted_from_image}")
            
            # 如果未指定文件类型，使用检测到的类型
            if not file_type and detected_type:
                file_type = detected_type
            
            # 根据管道类型配置选项
            if pipeline in ["standard", "auto"]:
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
                            
                # 对于图片转换的PDF，如果没有指定OCR引擎，自动使用rapid
                if not ocr and is_converted_from_image:
                    logger.info(f"检测到图片转换的PDF，未指定OCR引擎，自动使用rapid引擎")
                    ocr = "rapid"
                    model_info["ocr_engine"] = ocr
                
                # 直接使用配置好的选项创建新的转换器
                logger.info(f"创建PDF转换器，OCR引擎: {ocr}, 语言: {language}")
                converter = get_pdf_converter(
                    ocr=ocr, 
                    language=language, 
                    pipeline_options=pipeline_options
                )
                model_info["ocr_engine"] = ocr or "默认"
                model_info["pipeline"] = "standard"
                
            elif pipeline == "simple":
                ext = Path(temp_file_path).suffix.lower()[1:] if Path(temp_file_path).suffix else file_type
                
                if ext == "pdf":
                    logger.info("检测到PDF文件，使用PyPDF2快速转换")
                    # 使用PyPDF2快速转换
                    res = get_fast_pdf_converter(temp_file_path)
                    model_info["pipeline"] = "simple_pdf"
                else:
                    # 原有的simple转换逻辑
                    if file_type:
                        logger.info(f"创建Simple转换器，文件类型: {file_type}")
                        converter = get_simple_converter(file_type)
                    else:
                        logger.info("创建默认Simple转换器")
                        converter = get_simple_converter()
                    
                    model_info["pipeline"] = "simple"
                    res = converter.convert(temp_file_path)
            
            elif pipeline == "vlm":
                logger.info("创建VLM转换器")
                # 获取环境变量中的提供商和模型信息
                provider = os.environ.get("VLM_PROVIDER", "ollama")
                model = os.environ.get("VLM_MODEL_NAME", "")
                
                logger.info(f"使用VLM服务，提供商: {provider}, 模型: {model or '默认'}")
                
                converter = get_vlm_converter(
                    provider=provider,
                    model=model,
                    prompt=None,
                    api_key=None
                )
                
                model_info["pipeline"] = "vlm"
                model_info["provider"] = provider
                model_info["model"] = model or "默认模型"
                
            else:
                # 自动检测
                ext = Path(temp_file_path).suffix.lower()[1:] if Path(temp_file_path).suffix else file_type
                if ext == "pdf" or is_converted_from_image:  # 使用标志而不是列举扩展名
                    logger.info(f"自动检测为PDF文件，创建PDF转换器")
                    # 对于图片转换的PDF，如果没有指定OCR引擎，自动使用rapid
                    if not ocr and is_converted_from_image:
                        logger.info(f"检测到图片转换的PDF，未指定OCR引擎，自动使用rapid引擎")
                        ocr = "rapid"
                        model_info["ocr_engine"] = ocr
                        
                    converter = get_pdf_converter(ocr=ocr, language=language)
                    model_info["pipeline"] = "standard"
                    model_info["ocr_engine"] = ocr or "默认"
                else:
                    logger.info(f"自动检测为其他格式，创建Simple转换器")
                    converter = get_simple_converter(ext)
                    model_info["pipeline"] = "simple"
            
            # 执行转换
            logger.info(f"开始文档转换: {temp_file_path}")
            start_time = time.time()
            res = converter.convert(temp_file_path)
            conversion_time = time.time() - start_time
            logger.info(f"文档转换完成，耗时: {conversion_time:.2f}秒")
            
            # 如果是PyPDF2快速转换的结果
            if hasattr(res, 'text') and model_info["pipeline"] == "simple_pdf":
                if return_type == "dict_with_images":
                    result = {
                        "document_id": document_id,
                        "markdown_content": res.text,
                        "images": {},  # 空图片字典
                        "output_file": None
                    }
                    
                    # 如果需要输出到文件
                    if output_dir:
                        output_path = Path(output_dir)
                        output_path.mkdir(parents=True, exist_ok=True)
                        doc_filename = Path(res.input.file).stem
                        md_filename = output_path / f"{doc_filename}.md"
                        logger.info(f"保存快速提取的文本到文件: {md_filename}")
                        with open(md_filename, "w", encoding="utf-8") as f:
                            f.write(res.text)
                        result["output_file"] = str(md_filename)
                else:
                    # markdown或markdown_embedded模式
                    result = {
                        "document_id": document_id,
                        "markdown_content": res.text,
                        "output_file": None
                    }
                    
                    # 如果需要输出到文件
                    if output_dir:
                        output_path = Path(output_dir)
                        output_path.mkdir(parents=True, exist_ok=True)
                        doc_filename = Path(res.input.file).stem
                        md_filename = output_path / f"{doc_filename}.md"
                        logger.info(f"保存快速提取的文本到文件: {md_filename}")
                        with open(md_filename, "w", encoding="utf-8") as f:
                            f.write(res.text)
                        result["output_file"] = str(md_filename)
            else:
                # 处理单文件输出
                if return_type == "dict_with_images":
                    logger.info(f"导出Markdown，类型: {return_type}")
                    # 使用extract_images_with_markdown功能提取图像和内容
                    result = extract_images_with_markdown(res, output_dir)
                    # 添加document_id
                    result["document_id"] = document_id
                    
                    # 如果指定了输出目录，保存结果
                    if output_dir:
                        output_path = Path(output_dir)
                        output_path.mkdir(parents=True, exist_ok=True)
                        doc_filename = Path(res.input.file).stem
                        md_filename = output_path / f"{doc_filename}.md"
                        logger.info(f"保存Markdown到文件: {md_filename}")
                        with open(md_filename, "w", encoding="utf-8") as f:
                            f.write(result["markdown_content"])
                        result["output_file"] = str(md_filename)
                else:
                    # 处理markdown和markdown_embedded模式
                    markdown_type = ImageRefMode.EMBEDDED if return_type == "markdown_embedded" else ImageRefMode.REFERENCED
                    logger.info(f"导出Markdown，类型: {return_type}")
                    markdown_content = res.document.export_to_markdown(image_mode=markdown_type)
                    
                    # 构建基本结果
                    result = {
                        "document_id": document_id,
                        "markdown_content": markdown_content,
                        "output_file": None
                    }
                    
                    # 如果要输出到文件
                    if output_dir:
                        output_path = Path(output_dir)
                        # 判断是文件还是目录
                        if output_path.suffix:  # 有后缀名，当作文件处理
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            logger.info(f"保存Markdown到文件: {output_path}")
                            with open(output_path, "w", encoding="utf-8") as f:
                                f.write(markdown_content)
                            result["output_file"] = str(output_path)
                        else:  # 无后缀，当作目录处理
                            output_path.mkdir(parents=True, exist_ok=True)
                            doc_filename = Path(res.input.file).stem
                            md_filename = output_path / f"{doc_filename}.md"
                            logger.info(f"保存Markdown到文件: {md_filename}")
                            with open(md_filename, "w", encoding="utf-8") as f:
                                f.write(markdown_content)
                            result["output_file"] = str(md_filename)
            
            # 添加模型信息到结果中
            result["model_info"] = model_info
            logger.info(f"处理完成，文档ID: {document_id}")
            
            return result
        
        finally:
            # 只删除临时创建的文件
            if temp_file_path and os.path.exists(temp_file_path) and is_temp_file:
                logger.debug(f"清理临时文件: {temp_file_path}")
                os.unlink(temp_file_path)

    except Exception as e:
        logger.exception(f"文档转换失败: {str(e)}")
        import traceback
        return {
            "error": True,
            "message": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
            "model_info": model_info  # 在错误情况下也返回模型信息
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

def get_vlm_converter(
    provider: str = None, 
    model: str = None, 
    prompt: str = None, 
    api_key: str = None
) -> DocumentConverter:
    """获取基于视觉语言模型的转换器"""
    from .vlm_config import get_vlm_pipeline_options
    
    # 从环境变量读取缺失值，默认使用ollama
    provider = provider or os.environ.get("VLM_PROVIDER", "ollama")
    model = model or os.environ.get("VLM_MODEL_NAME", "")
    prompt = prompt or os.environ.get("VLM_PROMPT", "")
    api_key = api_key or os.environ.get("VLM_API_KEY", "")
    
    logger.info(f"配置VLM转换器 - 提供商: {provider}, 模型: {model or '默认'}")
    
    vlm_options = get_vlm_pipeline_options(
        provider=provider,
        model=model,
        prompt=prompt,
        api_key=api_key
    )
    
    logger.info(f"VLM选项已配置, 是否使用远程服务: {vlm_options.enable_remote_services}")
    
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
        "markdown_content": "",
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
            result["markdown_content"] = f.read()
            
        # 提取并收集图片信息
        artifacts_dir = output_dir / f"{doc_filename}_artifacts"
        if artifacts_dir.exists():
            for img_path in artifacts_dir.glob("*.png"):
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    result["images"][img_path.name] = img_b64
    else:
        # 直接使用export_to_markdown方法
        result["markdown_content"] = conv_res.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
            
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
            logger.debug(f"提取图片过程中遇到异常 (可能是不支持图像的格式): {e}")
    
    return result

def extract_with_pypdf2(pdf_path):
    """使用PyPDF2快速提取PDF文本"""
    start_time = time.time()
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n\n"
    end_time = time.time()
    return text, end_time - start_time

def get_fast_pdf_converter(input_file):
    """获取基于PyPDF2的快速PDF转换器"""
    try:
        text, conversion_time = extract_with_pypdf2(input_file)
        logger.info(f"PyPDF2提取完成，耗时: {conversion_time:.2f}秒")
        
        # 创建一个类似于Docling转换结果的简单对象
        class SimpleConversionResult:
            def __init__(self, text, input_file):
                self.text = text
                self.input = type('obj', (object,), {'file': input_file})
                self.document = self

            def export_to_markdown(self, image_mode=None):
                return self.text
                
            def save_as_markdown(self, path, image_mode=None):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.text)
        
        return SimpleConversionResult(text, input_file)
    except Exception as e:
        logger.exception(f"PyPDF2快速提取失败: {str(e)}")
        raise
