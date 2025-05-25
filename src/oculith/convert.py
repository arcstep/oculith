import os
import sys
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, Union, Literal
import json
import base64
from docling_core.types.doc import ImageRefMode, PictureItem
import io
import time
from pypdf import PdfReader

# 1. 开启 MPS 回退，禁用 CUDA
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
os.environ['CUDA_VISIBLE_DEVICES'] = ''

# 2. 强制 docling_ibm_models 中的 CodeFormulaPredictor 全程使用 CPU
try:
    from docling_ibm_models.code_formula_model.code_formula_predictor import CodeFormulaPredictor
    _orig_predict = CodeFormulaPredictor.predict
    def _cpu_only_predict(self, images, labels):
        # 把模型和运算都移动到 CPU
        self._device = 'cpu'
        self._model.to('cpu')
        return _orig_predict(self, images, labels)
    CodeFormulaPredictor.predict = _cpu_only_predict
except ImportError:
    pass

# 3. 之后再 import torch，确保以上环境变量和补丁已生效
import torch
# 将默认 device 全部设为 CPU
torch.set_default_device('cpu')

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, VlmPipelineOptions, ApiVlmOptions, ResponseFormat,
    RapidOcrOptions, TesseractCliOcrOptions, OcrMacOptions, EasyOcrOptions,
    PictureDescriptionApiOptions
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline

from voidrail import create_app

from .common import convert_file, prepare_file
from .vlm_config import get_vlm_pipeline_options

logger = logging.getLogger(__name__)

# 🔧 Monkey patch for tokenizer compatibility
def _apply_tokenizer_patch():
    """应用tokenizer兼容性补丁"""
    try:
        from transformers import AutoTokenizer
        
        # 只在第一次导入时应用补丁
        if not hasattr(AutoTokenizer, '_oculith_patched'):
            # 保存原始方法
            original_from_pretrained = AutoTokenizer.from_pretrained
            
            @classmethod
            def patched_from_pretrained(cls, pretrained_model_name_or_path, *args, **kwargs):
                """强制使用慢速tokenizer解决ModelWrapper兼容性问题"""
                # 对公式模型强制使用慢速tokenizer
                if 'CodeFormula' in str(pretrained_model_name_or_path):
                    kwargs['use_fast'] = False
                    logger.debug(f"应用tokenizer补丁: {pretrained_model_name_or_path}")
                
                return original_from_pretrained(pretrained_model_name_or_path, *args, **kwargs)
            
            # 替换方法并标记已补丁
            AutoTokenizer.from_pretrained = patched_from_pretrained
            AutoTokenizer._oculith_patched = True
            logger.debug("✅ Tokenizer兼容性补丁已应用")
            
    except ImportError:
        # transformers未安装时忽略
        pass

# 应用补丁
_apply_tokenizer_patch()


# 创建Celery应用
app = create_app("docling")

def sanitize_filename(filename: str) -> str:
    """将字符串转换为安全的文件名"""
    # 移除或替换不安全的字符
    safe_name = re.sub(r'[<>:"/\\|?*#]', '_', filename)
    # 移除开头和结尾的点和空格
    safe_name = safe_name.strip('. ')
    # 确保不为空
    if not safe_name:
        safe_name = "unnamed"
    return safe_name

@app.task(name="docling.convert")
def convert(
    content: str,
    content_type: str = "auto",
    file_type: str = "",
    document_id: Optional[str] = None,
    pipeline: Literal["standard", "simple", "vlm"] = "auto",
    ocr: Optional[str] = None,
    language: str = "zh",
    return_base64_images: bool = False,
    images_scale: float = 2.0,
    generate_images: Literal["none", "page", "picture", "all"] = "picture",
    output_dir: Optional[str] = None,
    enable_vlm_picture_description: bool = False,
    enable_picture_classification: bool = False,
    enable_formula_enrichment: bool = True,
    enable_code_enrichment: bool = True,
    vlm_provider: Optional[str] = None,
    vlm_model: Optional[str] = None,
    vlm_prompt: Optional[str] = None,
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
        return_base64_images: 是否返回图片的base64编码数据
        images_scale: 图像缩放比例
        generate_images: 图像生成控制
        output_dir: 输出文件路径
        enable_vlm_picture_description: 是否启用VLM图片描述功能
        enable_formula_enrichment: 是否启用公式理解功能
        enable_picture_classification: 是否启用图片分类功能
        enable_code_enrichment: 是否启用代码理解功能
        vlm_provider: VLM提供商(dashscope, ollama, openai, huggingface)
        vlm_model: VLM模型名称
        vlm_prompt: VLM提示词
    """
    if enable_formula_enrichment:
        patch_mps_autocast()
        logger.info("🔧 已修补MPS autocast兼容性问题")
    
    model_info = {
        "pipeline": pipeline,
        "provider": None,
        "model": None,
        "ocr_engine": ocr,
        "vlm_enabled": enable_vlm_picture_description,
    }
    
    try:
        # 获取文档ID
        if not document_id:
            content_hash = hashlib.md5(content.encode() if isinstance(content, str) else content).hexdigest()
            document_id = f"{content_hash}"
        
        logger.info(f"开始处理文档 ID: {document_id}, 管道类型: {pipeline}, OCR引擎: {ocr}, VLM图片描述: {enable_vlm_picture_description}")
        
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
                                
                # 如果启用VLM图片描述功能
                if enable_vlm_picture_description:
                    # 启用远程服务和图片描述
                    pipeline_options.enable_remote_services = True
                    pipeline_options.do_picture_description = True
                    
                    # 从vlm_config获取图片描述API选项
                    from .vlm_config import get_picture_description_api_options
                    
                    # 获取配置选项并应用
                    api_options = get_picture_description_api_options(
                        provider=vlm_provider,
                        model=vlm_model,
                        prompt=vlm_prompt
                    )
                    
                    # 使用正确的选项
                    pipeline_options.picture_description_options = api_options
                    
                    # 更新模型信息
                    vlm_provider = vlm_provider or os.environ.get("VLM_PROVIDER", "ollama")
                    vlm_model = vlm_model or os.environ.get("VLM_MODEL_NAME", "")
                    
                    # 如果模型名为空，获取默认值
                    if not vlm_model:
                        vlm_model = get_default_vlm_model(vlm_provider)
                    
                    model_info["vlm_provider"] = vlm_provider
                    model_info["vlm_model"] = vlm_model
                    logger.info(f"启用VLM图片描述，提供商: {model_info['vlm_provider']}, 模型: {model_info['vlm_model']}")
                            
                # 对于图片转换的PDF，如果没有指定OCR引擎，自动使用rapid
                if not ocr and is_converted_from_image:
                    logger.info(f"检测到图片转换的PDF，未指定OCR引擎，自动使用rapid引擎")
                    ocr = "rapid"
                    model_info["ocr_engine"] = ocr
                
                # 直接使用配置好的选项创建新的转换器
                logger.info(f"创建PDF转换器，OCR引擎: {ocr}, 语言: {language}")
                
                # 🔍 提前检查OCR引擎可用性，给用户友好提示
                try:
                    converter = get_pdf_converter(
                        ocr=ocr, 
                        language=language, 
                        pipeline_options=pipeline_options
                    )
                except ValueError as e:
                    # OCR引擎不可用，返回友好错误
                    return {
                        "error": True,
                        "message": str(e),
                        "error_type": "OCREngineNotAvailable",
                        "suggestion": "请根据安装指导安装相应的OCR引擎，或使用其他可用引擎",
                        "model_info": model_info
                    }
                model_info["ocr_engine"] = ocr or "默认"
                model_info["pipeline"] = "standard"
                
                # 🔥 根据官方文档的简单方法：
                
                # 1. 公式理解
                if enable_formula_enrichment:
                    try:
                        pipeline_options.do_formula_enrichment = True
                        logger.info("✅ 启用官方公式理解功能")
                        model_info["formula_enrichment"] = True
                    except Exception as e:
                        logger.error(f"公式理解启用失败: {e}")
                        # 可以选择返回错误或继续处理
                
                # 2. 图片分类
                if enable_picture_classification:
                    try:
                        pipeline_options.do_picture_classification = True
                        logger.info("✅ 启用图片分类功能")
                        model_info["picture_classification"] = True
                    except Exception as e:
                        logger.error(f"图片分类启用失败: {e}")
                
                # 3. 代码理解（也可以添加）
                if enable_code_enrichment:
                    try:
                        pipeline_options.do_code_enrichment = True
                        logger.info("✅ 启用代码理解功能")
                        model_info["code_enrichment"] = True
                    except Exception as e:
                        logger.error(f"代码理解启用失败: {e}")
            
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
                
                # 更新：如果model为空，获取默认值
                if not model:
                    model = get_default_vlm_model(provider)
                
                logger.info(f"使用VLM服务，提供商: {provider}, 模型: {model}")
                
                converter = get_vlm_converter(
                    provider=provider,
                    model=model,
                    prompt=None,
                    api_key=None
                )
                
                model_info["pipeline"] = "vlm"
                model_info["provider"] = provider
                model_info["model"] = model
                
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
            
            # 处理结果
            result = {
                "document_id": document_id,
                "markdown_content": "",
                "images": {},
                "output_file": None,
                "model_info": model_info
            }
            
            # 如果是PyPDF2快速转换的结果
            if hasattr(res, 'text') and model_info["pipeline"] == "simple_pdf":
                result["markdown_content"] = res.text
                
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
                # 标准或VLM处理结果
                markdown_content = res.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
                result["markdown_content"] = markdown_content
                
                # 检查并处理图片信息
                pic_count = 0
                doc_filename = Path(res.input.file).stem

                for element, _level in res.document.iterate_items():
                    if isinstance(element, PictureItem):
                        pic_count += 1
                        ref_id = element.self_ref
                        caption = element.caption_text(doc=res.document)
                        has_annotations = hasattr(element, "annotations") and element.annotations
                        
                        # 记录日志
                        logger.info(f"图片 {ref_id} - 标题: {caption}")
                        if has_annotations:
                            logger.info(f"图片注释: {element.annotations}")
                        else:
                            logger.info(f"图片没有注释")
                        
                        # 无论是否需要base64数据，都添加到返回结果中
                        safe_ref_id = sanitize_filename(ref_id)  # 安全化文件名
                        image_info = {
                            "filename": f"{safe_ref_id}.png",
                            "ref_path": f"{doc_filename}_artifacts/{safe_ref_id}.png",
                            "caption": caption,
                            "original_ref": ref_id  # 保留原始引用
                        }
                        
                        # 如果有图片注释，则返回
                        if has_annotations:
                            # 将PictureDescriptionData对象转换为可序列化的字典
                            if hasattr(element.annotations, '__dict__'):
                                # 如果是对象类型，转换为字典
                                annotations_dict = {}
                                for key, value in element.annotations.__dict__.items():
                                    if key.startswith('_'):  # 跳过私有属性
                                        continue
                                    if hasattr(value, '__dict__'):
                                        annotations_dict[key] = str(value)  # 复杂对象转为字符串
                                    else:
                                        annotations_dict[key] = value
                                image_info["annotations"] = annotations_dict
                            else:
                                # 如果是其他类型，转为字符串
                                image_info["annotations"] = str(element.annotations)
                        
                        # 只有在需要时才提取并返回base64数据
                        if return_base64_images:
                            try:
                                image = element.get_image(res.document)
                                with io.BytesIO() as buffer:
                                    image.save(buffer, format="PNG")
                                    img_bytes = buffer.getvalue()
                                    image_info["base64"] = base64.b64encode(img_bytes).decode("utf-8")
                            except Exception as e:
                                logger.warning(f"提取图片失败: {e}")
                        
                        # 添加到结果中（无论是否有base64数据）
                        result["images"][ref_id] = image_info
                
                logger.info(f"文档中共包含 {pic_count} 个图片项目")
                
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
                        
                        # 如果有图片并且需要返回base64数据，保存到文件系统
                        if return_base64_images and result["images"]:
                            artifacts_dir = output_path / f"{doc_filename}_artifacts"
                            artifacts_dir.mkdir(exist_ok=True)
                            for ref_id, image_info in result["images"].items():
                                if "base64" in image_info:
                                    # 使用安全化的文件名
                                    img_path = artifacts_dir / image_info["filename"]
                                    logger.info(f"保存图片: {img_path}")
                                    with open(img_path, "wb") as f:
                                        f.write(base64.b64decode(image_info["base64"]))
            
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

def check_ocr_engine_availability(ocr_engine: str) -> tuple[bool, str]:
    """检查OCR引擎是否可用
    
    Returns:
        tuple: (是否可用, 错误信息或安装指导)
    """
    if not ocr_engine or ocr_engine == "rapid":
        # RapidOCR是docling内置的，但也要测试一下
        try:
            from rapidocr_onnxruntime import RapidOCR
            # 尝试创建实例来确保能正常工作
            ocr = RapidOCR()
            return True, ""
        except Exception as e:
            return False, f"❌ RapidOCR初始化失败: {e}\n🔧 可能需要重新安装docling"
    
    try:
        if ocr_engine == "tesseract":
            # 1. 检查Python包
            import tesserocr
            
            # 2. 检查系统命令
            import shutil
            tesseract_path = shutil.which("tesseract")
            if not tesseract_path:
                return False, (
                    "❌ Tesseract系统命令未找到\n"
                    "🔧 安装方法：\n"
                    "   brew install tesseract tesseract-lang\n"
                    "   export TESSDATA_PREFIX=/opt/homebrew/share/tessdata/"
                )
            
            # 3. 检查架构兼容性
            import subprocess
            try:
                result = subprocess.run([tesseract_path, "--version"], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    return False, (
                        f"❌ Tesseract命令执行失败: {result.stderr}\n"
                        "🔧 可能是架构不兼容，尝试重新安装:\n"
                        "   brew uninstall tesseract\n"
                        "   brew install tesseract tesseract-lang"
                    )
            except subprocess.TimeoutExpired:
                return False, "❌ Tesseract命令超时，可能存在架构问题"
            
            # 4. 测试TesserOCR初始化
            try:
                tesserocr.PyTessBaseAPI()
                return True, ""
            except Exception as e:
                return False, (
                    f"❌ TesserOCR初始化失败: {e}\n"
                    "🔧 可能是架构不兼容或语言数据缺失，尝试:\n"
                    "   1. 重新安装: brew reinstall tesseract tesseract-lang\n"
                    "   2. 重新编译Python包: poetry install --no-cache"
                )
            
        elif ocr_engine == "easy":
            # 1. 检查导入
            import easyocr
            
            # 2. 测试初始化（这会下载模型）
            try:
                reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                return True, ""
            except Exception as e:
                return False, (
                    f"❌ EasyOCR初始化失败: {e}\n"
                    "🔧 可能需要重新安装:\n"
                    "   poetry remove easyocr\n"
                    "   poetry add easyocr"
                )
            
        elif ocr_engine == "mac":
            # 1. 检查系统
            import platform
            if platform.system() != "Darwin":
                return False, (
                    "❌ OcrMac只能在macOS系统上使用\n"
                    "🔧 建议使用其他OCR引擎：rapid, tesseract, easy"
                )
            
            # 2. 检查导入
            import ocrmac
            
            # 3. 测试功能
            try:
                # 测试是否能访问系统OCR服务
                ocrmac.OCR("test").recognize("dummy")
                return True, ""
            except Exception as e:
                # 这里可能会失败，但只要能导入就算成功
                return True, ""
            
        else:
            return False, f"❌ 未知的OCR引擎: {ocr_engine}"
            
    except ImportError as e:
        missing_package = str(e).split("'")[1] if "'" in str(e) else ocr_engine
        
        # 针对从Intel迁移的情况给出特别说明
        migration_note = (
            "\n⚠️  从Intel Mac迁移的用户注意：\n"
            "   可能需要完全重新安装依赖以适配Apple Silicon架构"
        )
        
        install_guides = {
            "tesserocr": (
                "❌ TesserOCR未安装或架构不兼容\n"
                "🔧 安装方法：\n"
                "   1. 安装系统依赖: brew install tesseract tesseract-lang\n"
                "   2. 设置环境变量: export TESSDATA_PREFIX=/opt/homebrew/share/tessdata/\n"
                "   3. 重新安装Python包: poetry install --no-cache"
                + migration_note
            ),
            "easyocr": (
                "❌ EasyOCR未安装\n"
                "🔧 安装方法：\n"
                "   poetry add easyocr"
                + migration_note
            ),
            "ocrmac": (
                "❌ OcrMac未安装\n"
                "🔧 安装方法：\n"
                "   poetry install --no-cache"
                + migration_note
            )
        }
        
        guide = install_guides.get(missing_package, f"❌ 缺少依赖包: {missing_package}")
        return False, guide
    
    except Exception as e:
        return False, (
            f"❌ {ocr_engine} 引擎测试失败: {e}\n"
            "🔧 可能是架构不兼容，建议重新安装相关依赖"
        )

def get_pdf_converter(ocr: Optional[str] = None, language: str = "zh", 
                     pipeline_options: Optional[PdfPipelineOptions] = None) -> DocumentConverter:
    """获取PDF处理转换器"""
    
    # 🔍 检查OCR引擎可用性
    if ocr:
        available, error_message = check_ocr_engine_availability(ocr)
        if not available:
            logger.error(f"OCR引擎 '{ocr}' 不可用:")
            logger.error(error_message)
            raise ValueError(f"OCR引擎 '{ocr}' 不可用。\n\n{error_message}")
    
    # 如果没有提供选项，创建默认选项
    if pipeline_options is None:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True  # 启用图像提取
    
    # 如果指定OCR，配置OCR选项
    if ocr:
        pipeline_options.do_ocr = True
        logger.info(f"✅ 使用OCR引擎: {ocr}")
        
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
    """提取文档中的插图、描述和Markdown内容"""
    result = {
        "markdown_content": "",
        "images": {},
        "picture_descriptions": {}  # 新增字段存储图片描述
    }
    
    doc_filename = Path(conv_res.input.file).stem
    
    # 提取图片描述
    for element, _level in conv_res.document.iterate_items():
        if isinstance(element, PictureItem) and hasattr(element, "annotations") and element.annotations:
            # 使用图片引用ID作为键
            ref_id = element.self_ref
            result["picture_descriptions"][ref_id] = {
                "caption": element.caption_text(doc=conv_res.document),
                "annotations": element.annotations
            }
    
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

# 获取OCR引擎的真实默认值（在获取PDF转换器之前）
def get_default_ocr_engine():
    """获取默认OCR引擎名称"""
    return "rapid"  # 或者根据实际情况返回

# 获取VLM模型的真实默认值
def get_default_vlm_model(provider):
    """根据提供商获取默认VLM模型名称"""
    if provider == "ollama":
        return "granite3.2-vision:2b"
    elif provider == "dashscope":
        return "qwen-vl-plus"
    elif provider == "openai":
        return "gpt-4o"
    else:
        return "HuggingFaceTB/SmolVLM-256M-Instruct"

# 添加一个辅助函数来列出可用的OCR引擎
def list_available_ocr_engines() -> Dict[str, bool]:
    """列出所有OCR引擎的可用性状态"""
    engines = ["rapid", "tesseract", "easy", "mac"]
    status = {}
    
    for engine in engines:
        available, _ = check_ocr_engine_availability(engine)
        status[engine] = available
    
    return status

def print_ocr_status():
    """打印OCR引擎状态报告"""
    status = list_available_ocr_engines()
    
    print("\n🔍 OCR引擎可用性检查:")
    print("=" * 40)
    
    for engine, available in status.items():
        status_icon = "✅" if available else "❌"
        status_text = "可用" if available else "不可用"
        print(f"  {status_icon} {engine:<12} {status_text}")
        
        if not available:
            _, guide = check_ocr_engine_availability(engine)
            print(f"     安装指导: {guide.split('🔧')[1].strip() if '🔧' in guide else guide}")
    
    print("=" * 40)
    available_engines = [k for k, v in status.items() if v]
    print(f"✅ 可用引擎: {', '.join(available_engines)}")
    print()

def patch_mps_autocast():
    """修补MPS设备的兼容性问题 - 强制公式理解使用CPU"""
    import os
    
    # 1. 强制整个进程的公式理解部分使用CPU
    os.environ['CUDA_VISIBLE_DEVICES'] = ''  # 禁用CUDA
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
    
    # 2. 修补torch默认设备
    original_set_default_device = torch.set_default_device
    
    def patched_set_default_device(device):
        if str(device) == 'mps':
            logger.warning("🔧 检测到MPS设备设置，为兼容性改为CPU")
            return original_set_default_device('cpu')
        return original_set_default_device(device)
    
    torch.set_default_device = patched_set_default_device
    
    # 3. 修补autocast
    original_autocast = torch.autocast
    
    def patched_autocast(device_type, **kwargs):
        if device_type == 'mps':
            logger.warning("🔧 MPS设备不支持autocast，强制使用CPU")
            return original_autocast('cpu', **kwargs)
        return original_autocast(device_type, **kwargs)
    
    torch.autocast = patched_autocast
    
    # 4. 强制设置默认张量类型为CPU
    torch.set_default_tensor_type(torch.FloatTensor)
    
    logger.info("🔧 已强制公式理解组件使用CPU以确保兼容性")
