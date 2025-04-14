"""
文档处理服务的FastAPI接口 - 直接使用ObservableConverter的简化版本
"""
import os
import logging
import asyncio
import base64
import tempfile
import time
import json
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, HttpUrl
from fastapi.responses import JSONResponse, StreamingResponse
from soulseal import TokenSDK
from docling.datamodel.base_models import ConversionStatus

# 直接导入ObservableConverter
from ..core.converter import ObservableConverter
from ..core.schemas import DocumentProcessStatus

token_sdk = TokenSDK(
    jwt_secret_key=os.environ.get("FASTAPI_SECRET_KEY", "MY-SECRET-KEY"),
    auth_base_url=os.environ.get("SOULSEAL_API_URL", "http://localhost:8000"),
    auth_prefix=os.environ.get("SOULSEAL_API_PREFIX", "/api")
)
verify_token = token_sdk.get_auth_dependency()

logger = logging.getLogger(__name__)

# 定义请求模型
class ProcessDocumentRequest(BaseModel):
    """文档处理请求"""
    output_format: str = "markdown"
    enable_remote_services: bool = False
    do_ocr: bool = False
    do_table_detection: bool = False
    do_formula_detection: bool = False
    enable_pic_description: bool = False

class ProcessUrlRequest(BaseModel):
    """URL处理请求"""
    url: HttpUrl
    output_format: str = "markdown"
    enable_remote_services: bool = False
    do_ocr: bool = False
    do_table_detection: bool = False
    do_formula_detection: bool = False
    enable_pic_description: bool = False

# 定义用户类型
UserDict = Dict[str, Any]

def mount_docling_service(
    app: FastAPI,
    output_dir: Optional[str] = None,
    allowed_formats: Optional[List[str]] = None,
    prefix: str = "/"
) -> None:
    """挂载文档处理服务到FastAPI应用"""
    # 创建路由
    router = APIRouter()
    
    # 为ObservableConverter指定的输出目录（如果未指定）
    if not output_dir:
        output_dir = os.path.join(tempfile.gettempdir(), "illufly_docling_output")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"未指定输出目录，将使用临时目录: {output_dir}")
    
    logger.info(f"创建ObservableConverter: output_dir={output_dir}")
    
    @app.on_event("startup")
    async def startup_converter():
        # 创建转换器实例
        from docling.datamodel.base_models import InputFormat
        
        # 如果指定了允许的格式，将其转换为InputFormat枚举
        converter_allowed_formats = None
        if allowed_formats:
            converter_allowed_formats = [InputFormat(fmt) for fmt in allowed_formats]
        
        # 创建并存储ObservableConverter实例
        app.state.converter = ObservableConverter(
            allowed_formats=converter_allowed_formats
        )
        
        logger.info("文档转换服务已启动")
    
    # 获取转换器的依赖
    async def get_converter():
        return app.state.converter
    
    
    # 获取支持的格式
    @router.get("/formats")
    async def get_formats(
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """获取支持的文档格式"""
        try:
            # 获取允许的格式列表
            formats = [fmt.value for fmt in converter.allowed_formats]
            return {"formats": formats}
        except Exception as e:
            logger.error(f"获取格式列表时出错: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # 服务信息
    @router.get("/info")
    async def get_service_info(
        token_data: Dict[str, Any] = Depends(verify_token)
    ):
        """获取服务信息"""
        return {
            "service": "illufly-docling-service",
            "version": "0.1.0",
            "allowed_formats": [fmt.value for fmt in app.state.converter.allowed_formats],
            "description": "文档处理服务"
        }
    
    
    # 上传并转换 - 简化上传文件并返回markdown结果
    @router.post("/upload/convert", response_class=JSONResponse)
    async def upload_and_convert(
        file: UploadFile = File(...),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """上传文件并直接转换为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"上传并转换请求: 用户ID={user_id}, 文件名={file.filename}")
        
        try:
            # 保存上传文件到临时位置
            temp_dir = Path(os.path.join(tempfile.gettempdir(), "illufly_docling_uploads"))
            temp_dir.mkdir(exist_ok=True, parents=True)
            temp_file = temp_dir / f"{user_id}_{int(time.time())}_{file.filename}"
            
            content = await file.read()
            with open(temp_file, "wb") as f:
                f.write(content)
            
            try:
                # 同步转换文档
                result = converter.convert(source=str(temp_file))
                
                # 处理结果
                if result.status == ConversionStatus.SUCCESS and result.document:
                    # 导出为Markdown
                    markdown_content = result.document.export_to_markdown()
                    return {
                        "success": True,
                        "content": markdown_content,
                        "content_type": "text/markdown"
                    }
                else:
                    # 处理失败
                    error_msg = f"转换失败: {result.status}"
                    if hasattr(result, 'errors') and result.errors:
                        error_msg = str(result.errors[0])
                    
                    raise HTTPException(status_code=500, detail=error_msg)
            finally:
                # 清理临时文件
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception as e:
                        logger.warning(f"删除临时文件失败: {e}")
        except Exception as e:
            logger.error(f"上传并转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # 本地文件转换 - 指定路径并返回markdown结果
    @router.post("/local/convert", response_class=JSONResponse)
    async def local_convert(
        path: str = Form(...),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """转换本地文件路径为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"本地转换请求: 用户ID={user_id}, 路径={path}")
        
        # 验证文件存在
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
        
        try:
            # 同步转换文档
            result = converter.convert(source=path)
            
            # 处理结果
            if result.status == ConversionStatus.SUCCESS and result.document:
                # 导出为Markdown
                markdown_content = result.document.export_to_markdown()
                return {
                    "success": True,
                    "content": markdown_content,
                    "content_type": "text/markdown"
                }
            else:
                # 处理失败
                error_msg = f"转换失败: {result.status}"
                if hasattr(result, 'errors') and result.errors:
                    error_msg = str(result.errors[0])
                
                raise HTTPException(status_code=500, detail=error_msg)
        except Exception as e:
            logger.error(f"本地转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # 远程文件转换 - 指定URL并返回markdown结果
    @router.post("/remote/convert", response_class=JSONResponse)
    async def remote_convert(
        url: str = Form(...),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """转换远程URL为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"远程转换请求: 用户ID={user_id}, URL={url}")
        
        # 验证URL格式
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="无效的URL格式")
        
        try:
            # 同步转换文档
            result = converter.convert(source=url)
            
            # 处理结果
            if result.status == ConversionStatus.SUCCESS and result.document:
                # 导出为Markdown
                markdown_content = result.document.export_to_markdown()
                return {
                    "success": True,
                    "content": markdown_content,
                    "content_type": "text/markdown"
                }
            else:
                # 处理失败
                error_msg = f"转换失败: {result.status}"
                if hasattr(result, 'errors') and result.errors:
                    error_msg = str(result.errors[0])
                
                raise HTTPException(status_code=500, detail=error_msg)
        except Exception as e:
            logger.error(f"远程转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # 注册路由
    app.include_router(router, prefix=prefix)
