"""
文档处理服务的FastAPI接口 - 直接使用ObservableConverter和FileService
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

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel, HttpUrl
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from soulseal import TokenSDK
from docling.datamodel.base_models import ConversionStatus

# 导入核心组件
from ..core.converter import ObservableConverter
from ..core.schemas import DocumentProcessStatus
from ..core.file_service import FilesService, FileStatus

token_sdk = TokenSDK(
    jwt_secret_key=os.environ.get("FASTAPI_SECRET_KEY", "MY-SECRET-KEY"),
    auth_base_url=os.environ.get("SOULSEAL_API_URL", "http://localhost:8000"),
    auth_prefix=os.environ.get("SOULSEAL_API_PREFIX", "/api")
)
verify_token = token_sdk.get_auth_dependency()

logger = logging.getLogger(__name__)

# 文件元数据请求模型
class FileMetadataUpdate(BaseModel):
    """文件元数据更新请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_metadata: Optional[Dict[str, Any]] = None


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

def format_allowed_extensions(allowed_formats):
    """从允许的格式中提取文件扩展名"""
    extensions = []
    format_to_extension = {
        "docx": [".docx"],
        "pptx": [".pptx"],
        "html": [".html", ".htm"],
        "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".bmp"],
        "pdf": [".pdf"],
        "asciidoc": [".adoc", ".asciidoc"],
        "md": [".md", ".markdown"],
        "csv": [".csv"],
        "xlsx": [".xlsx", ".xls"],
        "xml_uspto": [".xml"],
        "xml_jats": [".xml"],
        "json_docling": [".json"]
    }
    
    for fmt in allowed_formats:
        if fmt in format_to_extension:
            extensions.extend(format_to_extension[fmt])
    
    return list(set(extensions))  # 去重

def mount_docling_service(
    app: FastAPI,
    output_dir: Optional[str] = None,
    allowed_formats: Optional[List[str]] = None,
    prefix: str = "/"
) -> None:
    """挂载文档处理服务到FastAPI应用"""
    # 创建路由
    router = APIRouter()
    
    # 为服务指定的输出目录（如果未指定）
    if not output_dir:
        output_dir = os.path.join(tempfile.gettempdir(), "illufly_docling_output")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"未指定输出目录，将使用临时目录: {output_dir}")
    
    # 创建文件服务，使用相同的输出目录
    files_dir = os.path.join(output_dir, "files")
    files_service = FilesService(base_dir=files_dir)
    app.state.files_service = files_service
    
    logger.info(f"创建ObservableConverter和FileService: output_dir={output_dir}")
    
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
        
        # 更新FileService的允许扩展名
        allowed_extensions = format_allowed_extensions([fmt.value for fmt in app.state.converter.allowed_formats])
        app.state.files_service.allowed_extensions = allowed_extensions
        
        logger.info(f"文档转换服务已启动，支持的扩展名: {allowed_extensions}")
    
    # 获取转换器的依赖
    async def get_converter():
        return app.state.converter
    
    # 获取文件服务的依赖
    async def get_files_service():
        return app.state.files_service
        
    # 服务信息
    @router.get("/oculith/info")
    async def get_service_info(
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """获取服务信息"""
        formats = [fmt.value for fmt in converter.allowed_formats]
        extensions = format_allowed_extensions(formats)
        
        return {
            "service": "oculith-document-service",
            "version": "0.1.1",
            "allowed_formats": formats,
            "allowed_extensions": extensions,
            "description": "文档处理服务"
        }    
    
    # 获取支持的格式
    @router.get("/oculith/formats")
    async def get_formats(
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter)
    ):
        """获取支持的文档格式"""
        try:
            # 获取允许的格式列表
            formats = [fmt.value for fmt in converter.allowed_formats]
            extensions = format_allowed_extensions(formats)
            
            return {
                "formats": formats,
                "extensions": extensions
            }
        except Exception as e:
            logger.error(f"获取格式列表时出错: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # 上传并转换 - 整合FileService
    @router.post("/oculith/upload/convert", response_class=JSONResponse)
    async def upload_and_convert(
        file: UploadFile = File(...),
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service)
    ):
        """上传文件、保存到文件系统并转换为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"上传并转换请求: 用户ID={user_id}, 文件名={file.filename}")
        
        try:
            # 准备元数据
            metadata = {}
            if title:
                metadata["title"] = title
            if description:
                metadata["description"] = description
            if tags:
                try:
                    metadata["tags"] = json.loads(tags)
                except:
                    metadata["tags"] = [t.strip() for t in tags.split(',') if t.strip()]
            
            # 保存文件到FileService
            file_info = await files_service.save_file(user_id, file, metadata)
            file_path = file_info["path"]
            
            try:
                # 同步转换文档
                result = converter.convert(source=file_path)
                
                # 处理结果
                if result.status == ConversionStatus.SUCCESS and result.document:
                    # 导出为Markdown
                    markdown_content = result.document.export_to_markdown()
                    
                    # 更新文件元数据，添加转换结果
                    await files_service.update_metadata(user_id, file_info["id"], {
                        "converted": True,
                        "conversion_status": str(result.status),
                        "conversion_time": time.time(),
                        "markdown_content": markdown_content
                    })
                    
                    return {
                        "success": True,
                        "file_id": file_info["id"],
                        "original_name": file_info["original_name"],
                        "content": markdown_content,
                        "content_type": "text/markdown",
                        "file_url": files_service.get_download_url(user_id, file_info["id"])
                    }
                else:
                    # 处理失败
                    error_msg = f"转换失败: {result.status}"
                    if hasattr(result, 'errors') and result.errors:
                        error_msg = str(result.errors[0])
                    
                    # 更新文件元数据，记录失败信息
                    await files_service.update_metadata(user_id, file_info["id"], {
                        "converted": False,
                        "conversion_status": str(result.status),
                        "conversion_time": time.time(),
                        "conversion_error": error_msg
                    })
                    
                    raise HTTPException(status_code=500, detail=error_msg)
            except Exception as e:
                # 转换过程中出错，记录错误信息
                error_msg = f"转换过程出错: {str(e)}"
                await files_service.update_metadata(user_id, file_info["id"], {
                    "converted": False,
                    "conversion_status": "ERROR",
                    "conversion_time": time.time(),
                    "conversion_error": error_msg
                })
                
                logger.error(f"转换失败: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=error_msg)
                
        except ValueError as e:
            # 文件上传失败
            logger.error(f"文件上传失败: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            # 其他错误
            logger.error(f"上传并转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # 本地文件转换 - 指定路径并返回markdown结果
    @router.post("/oculith/local/convert", response_class=JSONResponse)
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
    @router.post("/oculith/remote/convert", response_class=JSONResponse)
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
    
    # =================== 文件管理相关接口 ===================

    # 获取用户文件列表
    @router.get("/oculith/files")
    async def list_files(
        include_deleted: bool = Query(False, description="是否包含已删除文件"),
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取用户所有文件"""
        user_id = token_data["user_id"]
        files = await files_service.list_files(user_id)
        
        # 转换为前端格式
        result = []
        for file_info in files:
            result.append({
                "id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "extension": file_info.get("extension", ""),
                "created_at": file_info["created_at"],
                "updated_at": file_info.get("updated_at", file_info["created_at"]),
                "status": file_info.get("status", FileStatus.ACTIVE),
                "download_url": files_service.get_download_url(user_id, file_info["id"]),
                "preview_url": files_service.get_preview_url(user_id, file_info["id"]),
                # 添加其他自定义元数据
                "title": file_info.get("title", ""),
                "description": file_info.get("description", ""),
                "tags": file_info.get("tags", []),
                "converted": file_info.get("converted", False),
                "conversion_status": file_info.get("conversion_status", ""),
                "custom_metadata": {k: v for k, v in file_info.items() 
                                  if k not in ["id", "original_name", "size", "type", "extension", "path", 
                                              "created_at", "updated_at", "status", "title", "description", 
                                              "tags", "markdown_content"]}
            })
        
        return result
    
    # 单纯上传文件
    @router.post("/oculith/local/upload")
    async def upload_file(
        file: UploadFile = File(...), 
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """上传文件（不进行转换）"""
        user_id = token_data["user_id"]
        
        # 准备元数据
        metadata = {}
        if title:
            metadata["title"] = title
        if description:
            metadata["description"] = description
        if tags:
            try:
                metadata["tags"] = json.loads(tags)
            except:
                metadata["tags"] = [t.strip() for t in tags.split(',') if t.strip()]
        
        try:
            file_info = await files_service.save_file(user_id, file, metadata)
            
            return {
                "id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "extension": file_info.get("extension", ""),
                "created_at": file_info["created_at"],
                "download_url": files_service.get_download_url(user_id, file_info["id"]),
                "preview_url": files_service.get_preview_url(user_id, file_info["id"]),
                "title": file_info.get("title", ""),
                "description": file_info.get("description", ""),
                "tags": file_info.get("tags", []),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"上传文件失败: {str(e)}")
            raise HTTPException(status_code=500, detail="上传文件失败")
    
    # 获取文件信息
    @router.get("/oculith/files/{file_id}")
    async def get_file_info(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取文件信息和元数据"""
        user_id = token_data["user_id"]
        
        file_info = await files_service.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        return {
            "id": file_info["id"],
            "original_name": file_info["original_name"],
            "size": file_info["size"],
            "type": file_info["type"],
            "extension": file_info.get("extension", ""),
            "created_at": file_info["created_at"],
            "updated_at": file_info.get("updated_at", file_info["created_at"]),
            "download_url": files_service.get_download_url(user_id, file_info["id"]),
            "preview_url": files_service.get_preview_url(user_id, file_info["id"]),
            "title": file_info.get("title", ""),
            "description": file_info.get("description", ""),
            "tags": file_info.get("tags", []),
            "converted": file_info.get("converted", False),
            "conversion_status": file_info.get("conversion_status", ""),
            "custom_metadata": {k: v for k, v in file_info.items() 
                               if k not in ["id", "original_name", "size", "type", "extension", "path", 
                                           "created_at", "updated_at", "status", "title", "description", 
                                           "tags", "markdown_content"]}
        }
    
    # 获取已转换的Markdown内容
    @router.get("/oculith/files/{file_id}/content")
    async def get_file_content(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取文件的Markdown内容（如果已转换）"""
        user_id = token_data["user_id"]
        
        file_info = await files_service.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 检查文件是否已转换
        if not file_info.get("converted") or not file_info.get("markdown_content"):
            raise HTTPException(status_code=400, detail="文件尚未转换为Markdown或转换失败")
        
        return {
            "success": True,
            "file_id": file_id,
            "original_name": file_info["original_name"],
            "content": file_info["markdown_content"],
            "content_type": "text/markdown"
        }
    
    # 更新文件元数据
    @router.patch("/oculith/files/{file_id}")
    async def update_file_metadata(
        file_id: str,
        metadata: FileMetadataUpdate,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """更新文件元数据"""
        user_id = token_data["user_id"]
        
        # 构建元数据字典
        update_data = {}
        
        if metadata.title is not None:
            update_data["title"] = metadata.title
            
        if metadata.description is not None:
            update_data["description"] = metadata.description
            
        if metadata.tags is not None:
            update_data["tags"] = metadata.tags
            
        if metadata.custom_metadata:
            update_data.update(metadata.custom_metadata)
        
        success = await files_service.update_metadata(user_id, file_id, update_data)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法更新")
        
        # 获取更新后的文件信息
        file_info = await files_service.get_file(user_id, file_id)
        
        return {
            "id": file_info["id"],
            "original_name": file_info["original_name"],
            "updated_at": file_info["updated_at"],
            "title": file_info.get("title", ""),
            "description": file_info.get("description", ""),
            "tags": file_info.get("tags", [])
        }
    
    # 删除文件
    @router.delete("/oculith/files/{file_id}")
    async def delete_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """删除文件"""
        user_id = token_data["user_id"]
        
        success = await files_service.delete_file(user_id, file_id)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法删除")
        
        return {"success": True, "message": "文件已删除"}
    
    # 下载文件
    @router.get("/oculith/files/{file_id}/download")
    async def download_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """下载原始文件"""
        user_id = token_data["user_id"]
        
        try:
            file_info = await files_service.get_file(user_id, file_id)
            if not file_info or file_info.get("status") != FileStatus.ACTIVE:
                raise HTTPException(status_code=404, detail="文件不存在")
            
            file_path = Path(file_info["path"])
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="文件不存在")
            
            return FileResponse(
                path=file_path,
                filename=file_info["original_name"],
                media_type=files_service.get_file_mimetype(file_info["original_name"])
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="文件不存在")
        except Exception as e:
            logger.error(f"下载文件失败: {str(e)}")
            raise HTTPException(status_code=500, detail="下载文件失败")
    
    # 转换已上传的文件
    @router.post("/oculith/files/{file_id}/convert")
    async def convert_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service)
    ):
        """转换已上传的文件为Markdown"""
        user_id = token_data["user_id"]
        
        try:
            # 获取文件信息
            file_info = await files_service.get_file(user_id, file_id)
            if not file_info or file_info.get("status") != FileStatus.ACTIVE:
                raise HTTPException(status_code=404, detail="文件不存在")
            
            file_path = file_info["path"]
            
            # 同步转换文档
            result = converter.convert(source=file_path)
            
            # 处理结果
            if result.status == ConversionStatus.SUCCESS and result.document:
                # 导出为Markdown
                markdown_content = result.document.export_to_markdown()
                
                # 更新文件元数据，添加转换结果
                await files_service.update_metadata(user_id, file_id, {
                    "converted": True,
                    "conversion_status": str(result.status),
                    "conversion_time": time.time(),
                    "markdown_content": markdown_content
                })
                
                return {
                    "success": True,
                    "file_id": file_id,
                    "original_name": file_info["original_name"],
                    "content": markdown_content,
                    "content_type": "text/markdown"
                }
            else:
                # 处理失败
                error_msg = f"转换失败: {result.status}"
                if hasattr(result, 'errors') and result.errors:
                    error_msg = str(result.errors[0])
                
                # 更新文件元数据，记录失败信息
                await files_service.update_metadata(user_id, file_id, {
                    "converted": False,
                    "conversion_status": str(result.status),
                    "conversion_time": time.time(),
                    "conversion_error": error_msg
                })
                
                raise HTTPException(status_code=500, detail=error_msg)
                
        except HTTPException as e:
            # 直接重新抛出HTTP异常
            raise
        except Exception as e:
            logger.error(f"转换文件失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"转换文件失败: {str(e)}")
    
    # 获取用户存储状态
    @router.get("/oculith/files/storage/status")
    async def get_storage_status(
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取用户存储状态"""
        user_id = token_data["user_id"]
        
        try:
            usage = await files_service.calculate_user_storage_usage(user_id)
            files = await files_service.list_files(user_id)
            
            return {
                "used": usage,
                "limit": files_service.max_total_size_per_user,
                "available": files_service.max_total_size_per_user - usage,
                "usage_percentage": round(usage * 100 / files_service.max_total_size_per_user, 2),
                "file_count": len(files),
                "last_updated": time.time()
            }
        except Exception as e:
            logger.error(f"获取存储状态失败: {str(e)}")
            raise HTTPException(status_code=500, detail="获取存储状态失败")
    
    # 注册路由
    app.include_router(router, prefix=prefix)
