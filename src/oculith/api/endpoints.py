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
    
    # 处理文档上传
    @router.post("/process", response_class=JSONResponse)
    async def process_document(
        file: UploadFile = File(...),
        output_format: str = Form("markdown"),
        enable_remote_services: bool = Form(False),
        do_ocr: bool = Form(False),
        do_table_detection: bool = Form(False),
        do_formula_detection: bool = Form(False),
        enable_pic_description: bool = Form(False),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """处理上传的文档"""
        # 使用JWT中的用户ID
        user_id = token_data["user_id"]
        
        # 日志记录用户信息，便于调试
        logger.info(f"处理文档请求: 用户ID={user_id}, 用户信息={token_data}")
        
        try:
            # 创建临时文件
            temp_dir = Path(os.path.join(tempfile.gettempdir(), "illufly_docling_uploads"))
            temp_dir.mkdir(exist_ok=True, parents=True)
            
            # 生成带用户ID的文件名，避免冲突
            temp_file = temp_dir / f"{user_id}_{int(time.time())}_{file.filename}"
            
            # 保存上传的文件
            content = await file.read()
            with open(temp_file, "wb") as f:
                f.write(content)
                
            logger.info(f"文件已保存到临时位置: {temp_file}, 大小: {len(content)} 字节")
            
            # 创建文档状态跟踪器
            doc_id = f"doc_{user_id}_{int(time.time())}"
            status_tracker = DocumentProcessStatus(doc_id=doc_id)
            
            # 创建SSE响应
            async def event_generator():
                try:
                    # 开始处理文档
                    async for update in converter.convert_async(
                        source=str(temp_file),
                        doc_id=doc_id,
                        status_tracker=status_tracker
                    ):
                        # 将更新转换为SSE事件格式
                        yield f"data: {json.dumps(update)}\n\n"
                        
                        # 如果处理完成或失败，退出循环
                        if update["stage"] in ["completed", "error"]:
                            break
                
                finally:
                    # 清理临时文件
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                            logger.debug(f"已删除临时文件: {temp_file}")
                    except Exception as e:
                        logger.warning(f"删除临时文件 {temp_file} 失败: {e}")
            
            # 返回SSE响应
            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream"
            )
            
        except Exception as e:
            import traceback
            logger.error(f"处理文档时出错: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # 处理URL
    @router.post("/process-url", response_class=JSONResponse)
    async def process_url(
        request: ProcessUrlRequest,
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """处理URL指向的文档"""
        # 使用JWT中的用户ID
        user_id = token_data["user_id"]
        
        # 日志记录用户信息，便于调试
        logger.info(f"处理URL请求: 用户ID={user_id}, URL={request.url}")
        
        try:
            # 创建文档状态跟踪器
            doc_id = f"doc_{user_id}_{int(time.time())}"
            status_tracker = DocumentProcessStatus(doc_id=doc_id)
            
            # 创建SSE响应
            async def event_generator():
                try:
                    # 开始处理URL指向的文档
                    async for update in converter.convert_async(
                        source=str(request.url),
                        doc_id=doc_id,
                        status_tracker=status_tracker
                    ):
                        # 将更新转换为SSE事件格式
                        yield f"data: {json.dumps(update)}\n\n"
                        
                        # 如果处理完成或失败，退出循环
                        if update["stage"] in ["completed", "error"]:
                            break
                except Exception as e:
                    # 处理错误，发送错误事件
                    error_event = {
                        "stage": "error",
                        "message": f"处理URL文档时出错: {str(e)}",
                        "error": str(e),
                        "progress": 1.0,
                        "doc_id": doc_id
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
            
            # 返回SSE响应
            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream"
            )
            
        except Exception as e:
            import traceback
            logger.error(f"处理URL时出错: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))
    
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
    
    # 注册路由
    app.include_router(router, prefix=prefix)
