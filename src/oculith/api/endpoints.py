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

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile, Query, Request
from pydantic import BaseModel, HttpUrl
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from soulseal import TokenSDK
from docling.datamodel.base_models import ConversionStatus

# 导入核心组件
from ..core.converter import ObservableConverter
from ..core.schemas import DocumentProcessStatus
from ..core.file_service import FilesService, FileStatus
from ..core.litellm import init_litellm
from ..core.retriever import ChromaRetriever

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

def init_retriever(retriever: ChromaRetriever, files_service: FilesService):
    for chunk in files_service.iter_chunks_content():
        retriever.add(chunk)

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
        output_dir = "./.db"
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"未指定输出目录，将使用临时目录: {output_dir}")

    # 初始化litellm
    init_litellm(cache_dir=os.path.join(output_dir, "litellm_cache"))

    @app.on_event("startup")
    async def startup_converter():
        # 创建转换器实例
        from docling.datamodel.base_models import InputFormat
        
        # 如果指定了允许的格式，将其转换为InputFormat枚举
        converter_allowed_formats = None
        if allowed_formats:
            converter_allowed_formats = [InputFormat(fmt) for fmt in allowed_formats]
        
        # 先创建文件服务
        app.state.files_service = FilesService(base_dir=os.path.join(output_dir, "files"))
        
        # 创建并存储ObservableConverter实例，传入files_service
        app.state.converter = ObservableConverter(
            allowed_formats=converter_allowed_formats,
            files_service=app.state.files_service
        )

        # 初始化ChromaRetriever
        app.state.retriever = ChromaRetriever()
        
        # 更新FileService的允许扩展名
        allowed_extensions = format_allowed_extensions([fmt.value for fmt in app.state.converter.allowed_formats])
        app.state.files_service.allowed_extensions = allowed_extensions
    
    # 获取检索器的依赖
    async def get_retriever():
        return app.state.retriever

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
        request: Request,
        file: UploadFile = File(...),
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
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
            
            # 获取文件路径 - 注意这里使用source_type判断
            file_path = None
            if file_info.get("source_type") == "local":
                file_path = files_service.get_raw_file_path(user_id, file_info["id"])
            
            if not file_path or not file_path.exists():
                raise HTTPException(status_code=404, detail="文件上传失败或不存在")
            
            try:
                # 使用新版本的转换和保存
                result = await converter.convert_and_save(
                    source=str(file_path), 
                    user_id=user_id, 
                    file_id=file_info["id"],
                    retriever=retriever
                )
                
                # 处理字典格式的结果
                if result.get("success", False):
                    # 转换成功，返回结果
                    return {
                        "success": True,
                        "file_id": file_info["id"],
                        "original_name": file_info["original_name"],
                        "content": result.get("content", ""),
                        "content_type": "text/markdown",
                        "file_url": str(request.url_for("download_file", file_id=file_info["id"]))
                    }
                else:
                    # 转换失败
                    error_msg = result.get("error", "未知错误")
                    
                    # 记录错误信息到文件元数据
                    await files_service.update_metadata(user_id, file_info["id"], {
                        "converted": False,
                        "conversion_status": "ERROR",
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
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """转换本地文件路径为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"本地转换请求: 用户ID={user_id}, 路径={path}")
        
        # 验证文件存在
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
        
        try:
            # 创建文件记录
            filename = os.path.basename(path)
            with open(path, "rb") as file_data:
                file_info = await files_service.save_file(
                    user_id=user_id,
                    file=UploadFile(filename=filename, file=file_data),
                    metadata={"source": "local_path", "original_path": path}
                )
            
            # 使用convert_and_save处理文件
            result = await converter.convert_and_save(
                source=path,
                user_id=user_id,
                file_id=file_info["id"],
                retriever=retriever
            )
            
            if result.get("success", False):
                return {
                    "success": True,
                    "file_id": file_info["id"],
                    "content": result.get("content", ""),
                    "content_type": "text/markdown"
                }
            else:
                error_msg = result.get("error", "未知错误")
                raise HTTPException(status_code=500, detail=error_msg)
                
        except Exception as e:
            logger.error(f"本地转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # 远程文件转换 - 指定URL并返回markdown结果
    @router.post("/oculith/remote/convert", response_class=JSONResponse)
    async def remote_convert(
        url: str = Form(...),
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """转换远程URL为Markdown"""
        user_id = token_data["user_id"]
        logger.info(f"远程转换请求: 用户ID={user_id}, URL={url}")
        
        # 验证URL格式
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="无效的URL格式")
        
        try:
            # 为远程URL创建文件记录
            import urllib.parse
            filename = os.path.basename(urllib.parse.urlparse(url).path) or "remote_document"
            if not filename.strip():
                filename = "remote_document.html"
            
            # 创建远程文件记录
            file_info = await files_service.create_remote_file_record(
                user_id=user_id,
                url=url,
                filename=filename,
                metadata={"source": "url"}
            )
            
            # 使用convert_and_save处理URL
            result = await converter.convert_and_save(
                source=url,
                user_id=user_id,
                file_id=file_info["id"],
                retriever=retriever
            )
            
            if result.get("success", False):
                return {
                    "success": True,
                    "file_id": file_info["id"],
                    "content": result.get("content", ""),
                    "content_type": "text/markdown"
                }
            else:
                error_msg = result.get("error", "未知错误")
                raise HTTPException(status_code=500, detail=error_msg)
            
        except Exception as e:
            logger.error(f"远程转换失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # =================== 文件管理相关接口 ===================

    # 获取用户文件列表
    @router.get("/oculith/files")
    async def list_files(
        request: Request,
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
            # 确定下载URL - 仅本地文件可下载原始内容
            download_url = None
            if file_info.get("source_type") == "local":
                download_url = str(request.url_for("download_file", file_id=file_info["id"]))
            
            # 适配新的元数据结构
            result.append({
                "id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "extension": file_info.get("extension", ""),
                "created_at": file_info["created_at"],
                "updated_at": file_info.get("updated_at", file_info["created_at"]),
                "status": file_info.get("status", FileStatus.ACTIVE),
                "download_url": download_url,
                "title": file_info.get("title", ""),
                "description": file_info.get("description", ""),
                "tags": file_info.get("tags", []),
                "converted": file_info.get("converted", False),
                "has_markdown": file_info.get("has_markdown", False),
                "has_chunks": file_info.get("has_chunks", False),
                "source_type": file_info.get("source_type", "local"),
                "source_url": file_info.get("source_url", ""),
                "chunks_count": file_info.get("chunks_count", 0),
                "custom_metadata": {k: v for k, v in file_info.items() 
                                  if k not in ["id", "original_name", "size", "type", "extension", "path", 
                                              "created_at", "updated_at", "status", "title", "description", 
                                              "tags", "has_markdown", "has_chunks", "source_type", "source_url",
                                              "chunks_count", "chunks"]}
            })
        
        return result
    
    # 单纯上传文件
    @router.post("/oculith/local/upload")
    async def upload_file(
        request: Request,
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
                "download_url": str(request.url_for("download_file", file_id=file_info["id"])),
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
        request: Request,
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取文件信息和元数据"""
        user_id = token_data["user_id"]
        
        file_info = await files_service.get_file_meta(user_id, file_id)
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
            "download_url": str(request.url_for("download_file", file_id=file_id)),
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
    @router.get("/oculith/files/{file_id}/markdown")
    async def get_file_markdown(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """获取文件的Markdown内容"""
        user_id = token_data["user_id"]
        
        try:
            # 获取文件元数据
            file_info = await files_service.get_file_meta(user_id, file_id)
            if not file_info or file_info.get("status") != FileStatus.ACTIVE:
                raise HTTPException(status_code=404, detail="文件不存在")
            
            # 检查是否有Markdown内容
            if not file_info.get("has_markdown", False):
                raise HTTPException(status_code=404, detail="此文件没有Markdown内容")
            
            # 获取Markdown内容
            markdown_content = await files_service.get_markdown_content(user_id, file_id)
            
            return {
                "success": True,
                "file_id": file_id,
                "original_name": file_info["original_name"],
                "content": markdown_content,
                "content_type": "text/markdown"
            }
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"获取Markdown内容失败: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
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
        file_info = await files_service.get_file_meta(user_id, file_id)
        
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
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """删除文件"""
        user_id = token_data["user_id"]
        
        # 1. 首先从向量库中删除文件相关的切片
        try:
            # 使用元数据过滤删除特定文件的切片
            await delete_file_chunks_from_vectordb(user_id, file_id, retriever)
            logger.info(f"已从向量库中删除文件切片: user_id={user_id}, file_id={file_id}")
        except Exception as e:
            logger.error(f"从向量库删除切片失败: {str(e)}")
            # 继续执行文件删除，不因向量库操作失败而中断整个删除流程
        
        # 2. 然后删除文件资源
        success = await files_service.delete_file(user_id, file_id)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法删除")
        
        return {"success": True, "message": "文件已删除"}
    
    # 下载文件
    @router.get("/oculith/files/{file_id}/download", name="download_file")
    async def download_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service)
    ):
        """下载原始文件"""
        user_id = token_data["user_id"]
        
        try:
            file_info = await files_service.get_file_meta(user_id, file_id)
            if not file_info or file_info.get("status") != FileStatus.ACTIVE:
                raise HTTPException(status_code=404, detail="文件不存在")
            
            # 判断文件类型
            if file_info.get("source_type") == "remote":
                # 远程文件无法下载原始内容，重定向到原始URL
                source_url = file_info.get("source_url")
                if not source_url:
                    raise HTTPException(status_code=404, detail="远程文件没有可用的源URL")
                
                # 返回重定向或提供URL信息
                return {
                    "success": False,
                    "message": "这是一个远程资源，请直接使用原始链接下载",
                    "source_url": source_url
                }
            
            # 本地文件 - 从raw目录获取
            file_path = files_service.get_raw_file_path(user_id, file_id)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="原始文件不存在")
            
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
    @router.post("/oculith/files/{file_id}/convert", response_class=JSONResponse)
    async def convert_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        converter: ObservableConverter = Depends(get_converter),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """转换已上传的文件为Markdown"""
        user_id = token_data["user_id"]
        
        try:
            # 获取文件信息
            file_info = await files_service.get_file_meta(user_id, file_id)
            if not file_info or file_info.get("status") != FileStatus.ACTIVE:
                raise HTTPException(status_code=404, detail="文件不存在")
            
            # 获取文件路径
            file_path = None
            if file_info.get("source_type") == "local":
                file_path = files_service.get_raw_file_path(user_id, file_id)
            elif file_info.get("source_type") == "remote":
                # 远程文件使用URL作为源
                file_path = file_info.get("source_url")
            
            if not file_path:
                raise HTTPException(status_code=404, detail="文件路径无效")
            
            if isinstance(file_path, Path) and not file_path.exists():
                raise HTTPException(status_code=404, detail="文件不存在")
            
            # 使用convert_and_save处理文件
            result = await converter.convert_and_save(
                source=str(file_path) if isinstance(file_path, Path) else file_path,
                user_id=user_id,
                file_id=file_id,
                retriever=retriever
            )
            
            if result.get("success", False):
                return {
                    "success": True,
                    "file_id": file_id,
                    "original_name": file_info["original_name"],
                    "content": result.get("content", ""),
                    "content_type": "text/markdown"
                }
            else:
                # 转换失败
                error_msg = result.get("error", "未知错误")
                
                # 更新文件元数据，记录失败信息
                await files_service.update_metadata(user_id, file_id, {
                    "converted": False,
                    "conversion_status": "ERROR",
                    "conversion_time": time.time(),
                    "conversion_error": error_msg
                })
                
                raise HTTPException(status_code=500, detail=error_msg)
                
        except HTTPException:
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
            # 使用新的存储计算方法
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
    
    @router.post("/oculith/init/vectordb")
    async def load_chunks_to_vectordb(
        request: Request,
        file_id: str = None,  # 可选参数，如果提供则只加载特定文件的切片
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """加载用户的所有文档切片到向量库"""
        user_id = token_data["user_id"]
        
        # 计数器
        chunks_added = 0
        
        # 遍历所有切片
        async for chunk in files_service.iter_chunks_content(user_id, file_id):
            # 添加到向量库
            await retriever.add(
                texts=chunk["content"],
                user_id=user_id,
                metadatas=chunk["metadata"]
            )
            chunks_added += 1
        
        return {
            "success": True,
            "message": f"成功加载{chunks_added}个切片到向量库",
            "chunks_count": chunks_added
        }
    
    # 检索与给定文本相似的切片
    @router.post("/oculith/search/chunks")
    async def search_similar_chunks(
        request: Request,
        query: str = Form(...),
        file_id: Optional[str] = Form(None),
        threshold: float = Form(0.7),
        limit: int = Form(10),
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """检索与给定文本相似的切片"""
        user_id = token_data["user_id"]
        
        try:
            # 构建查询条件
            query_config = {"n_results": 30}  # 先获取较多结果，后面再过滤
            
            # 使用retriever进行检索
            results = await retriever.query(
                texts=query,
                threshold=threshold,
                user_id=user_id,
                query_config=query_config
            )
            
            # 处理查询结果
            similar_chunks = []
            
            if results and len(results) > 0:
                query_result = results[0]  # 获取第一个查询的结果
                
                # 遍历文档和距离
                for i in range(len(query_result["documents"])):
                    doc = query_result["documents"][i]
                    distance = query_result["distances"][i]
                    metadata = query_result["metadatas"][i]
                    
                    # 根据file_id过滤
                    if file_id and metadata.get("file_id") != file_id:
                        continue
                    
                    # 添加到结果
                    chunk_data = {
                        "content": doc,
                        "distance": distance,  # 距离值（越小表示越相似）
                        "metadata": metadata,
                        "file_id": metadata.get("file_id"),
                        "chunk_index": metadata.get("chunk_index")
                    }
                    similar_chunks.append(chunk_data)
                    
                    # 达到数量限制就退出
                    if len(similar_chunks) >= limit:
                        break
            
            # 确保按距离升序排序
            similar_chunks.sort(key=lambda x: x["distance"])
            
            return {
                "query": query,
                "threshold": threshold,
                "chunks_found": len(similar_chunks),
                "chunks": similar_chunks
            }
            
        except Exception as e:
            logger.error(f"切片检索失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")

    # 检索与给定文本相似的Markdown文档
    @router.post("/oculith/search/documents")
    async def search_similar_documents(
        request: Request,
        query: str = Form(...),
        threshold: float = Form(0.7),
        limit: int = Form(10),
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        retriever: ChromaRetriever = Depends(get_retriever)
    ):
        """检索与给定文本相似的Markdown文档"""
        user_id = token_data["user_id"]
        
        try:
            # 使用retriever进行检索
            results = await retriever.query(
                texts=query,
                threshold=threshold,
                user_id=user_id,
                query_config={"n_results": 100}
            )
            
            # 按文档ID分组
            doc_chunks_count = {}  # 文档ID -> 匹配切片数量
            doc_chunks_distance = {}  # 文档ID -> 最小距离
            doc_metadata = {}  # 文档ID -> 基本元数据
            
            if results and len(results) > 0:
                query_result = results[0]
                
                # 遍历所有匹配的切片
                for i in range(len(query_result["documents"])):
                    metadata = query_result["metadatas"][i]
                    distance = query_result["distances"][i]
                    
                    file_id = metadata.get("file_id")
                    if not file_id:
                        continue
                    
                    # 计数并记录最小距离
                    if file_id not in doc_chunks_count:
                        doc_chunks_count[file_id] = 0
                        doc_chunks_distance[file_id] = float('inf')  # 初始化为无穷大
                        doc_metadata[file_id] = {
                            "id": file_id,
                            "original_name": metadata.get("original_name", ""),
                            "source_type": metadata.get("source_type", "local")
                        }
                    
                    doc_chunks_count[file_id] += 1
                    # 直接比较距离，保留最小的
                    if distance < doc_chunks_distance[file_id]:
                        doc_chunks_distance[file_id] = distance
            
            # 获取文档详细信息
            similar_docs = []
            for file_id, count in doc_chunks_count.items():
                try:
                    file_info = await files_service.get_file_meta(user_id, file_id)
                    if file_info:
                        # 合并信息
                        doc_info = {
                            "id": file_id,
                            "original_name": file_info.get("original_name", ""),
                            "size": file_info.get("size", 0),
                            "created_at": file_info.get("created_at", 0),
                            "total_chunks": file_info.get("chunks_count", 0),
                            "matching_chunks": count,
                            "min_distance": doc_chunks_distance[file_id],
                            "source_type": file_info.get("source_type", "local"),
                            "source_url": file_info.get("source_url", "")
                        }
                        similar_docs.append(doc_info)
                except Exception as e:
                    logger.error(f"获取文档信息失败: {file_id}, 错误: {e}")
            
            # 按距离排序，升序（距离小的在前）
            similar_docs.sort(key=lambda x: x["min_distance"])
            
            # 限制返回结果数量
            similar_docs = similar_docs[:limit]
            
            return {
                "query": query,
                "threshold": threshold,
                "documents_found": len(similar_docs),
                "documents": similar_docs
            }
            
        except Exception as e:
            logger.error(f"文档检索失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")

    # 注册路由
    app.include_router(router, prefix=prefix)

async def delete_file_chunks_from_vectordb(user_id: str, file_id: str, retriever: ChromaRetriever) -> None:
    """从向量库中删除指定文件的所有切片
    
    使用元数据过滤器删除特定文件的所有切片
    """
    # 使用where过滤条件删除
    where_filter = {
        "user_id": user_id,
        "file_id": file_id
    }
    
    # 从默认集合中删除
    collection_name = "default"
    
    # 执行删除
    retriever.delete(
        collection_name=collection_name,
        where=where_filter
    )
    
    logger.info(f"已从向量库删除文件所有切片: user_id={user_id}, file_id={file_id}")
