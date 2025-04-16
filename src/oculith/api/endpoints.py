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
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union, AsyncGenerator
from pathlib import Path
from functools import partial

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile, Query, Request
from pydantic import BaseModel, HttpUrl
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from soulseal import TokenSDK
from docling.datamodel.base_models import ConversionStatus

# 导入核心组件
from ..core.converter import ObservableConverter
from ..core.schemas import DocumentProcessStatus, FileProcessStatus
from ..core.file_service import FilesService, FileStatus
from ..core.litellm import init_litellm
from ..core.retriever import LanceRetriever
from ..core.queue_manager import QueueManager, TaskType, FileTask

token_sdk = TokenSDK(
    jwt_secret_key=os.environ.get("FASTAPI_SECRET_KEY", "MY-SECRET-KEY"),
    auth_base_url=os.environ.get("SOULSEAL_API_URL", "http://localhost:8000"),
    auth_prefix=os.environ.get("SOULSEAL_API_PREFIX", "/api")
)
verify_token = token_sdk.get_auth_dependency()

logger = logging.getLogger(__name__)

# 通用函数：确保队列管理器正在运行
async def ensure_queue_manager_running(queue_manager: QueueManager) -> None:
    """确保队列管理器正在运行，如果已停止则重启它
    
    检查工作进程状态，并在必要时重启队列管理器。
    在所有向队列添加任务的API端点中调用此函数，确保队列正常运行。
    """
    if (queue_manager.worker_task is None or 
        queue_manager.worker_task.done() or 
        queue_manager.worker_task.cancelled()):
        # 强制重置运行状态
        queue_manager.is_running = False
        queue_manager.worker_task = None
        logger.warning("检测到工作进程未运行或已取消，正在重新启动...")
        await queue_manager.start()
        logger.info("队列管理器已重新启动，工作进程ID: " + 
                   (str(id(queue_manager.worker_task)) if queue_manager.worker_task else "无"))

# 文件元数据请求模型
class FileMetadataUpdate(BaseModel):
    """文件元数据更新请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    extra_fields: Optional[Dict[str, Any]] = None  # 用于接收任何附加字段


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

def format_sse(data: Dict[str, Any], event: Optional[str] = None) -> str:
    """格式化数据为SSE格式"""
    message = []
    
    # 添加事件类型（如果有）
    if event is not None:
        message.append(f"event: {event}")
    
    # 添加数据（JSON格式）
    json_data = json.dumps(data, ensure_ascii=False)
    for line in json_data.splitlines():
        message.append(f"data: {line}")
    
    # 添加空行表示消息结束
    message.append("")
    message.append("")
    
    return "\n".join(message)

def mount_docling_service(
    app: FastAPI,
    output_dir: Optional[str] = None,
    allowed_formats: Optional[List[str]] = None,
    prefix: str = ""
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

    # 使用on_event方式处理生命周期事件
    # 注意: 虽然on_event已弃用，但在mount_docling_service函数中使用lifespan参数有困难
    @app.on_event("startup")
    async def startup_event():
        # 创建转换器实例
        from docling.datamodel.base_models import InputFormat
        
        # 导入任务队列管理器
        from ..core.queue_manager import QueueManager, TaskType, FileTask
        
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

        # 初始化LanceRetriever
        app.state.retriever = LanceRetriever(output_dir=os.path.join(output_dir, "lance_db"))
        
        # 初始化任务队列管理器
        app.state.queue_manager = QueueManager(max_concurrent_tasks=3)
        
        # 启动任务队列
        await app.state.queue_manager.start()
        
        # 在注册处理器之前增加日志
        logger.info("开始注册任务处理器...")
        for task_type in [TaskType.CONVERT, TaskType.CHUNK, TaskType.INDEX, TaskType.PROCESS_ALL]:
            logger.info(f"注册处理器: {task_type.value}")
        
        # 注册任务处理器
        await app.state.queue_manager.register_processor(
            TaskType.CONVERT, 
            partial(process_convert_task, 
                    converter=app.state.converter,
                    files_service=app.state.files_service)
        )
        
        await app.state.queue_manager.register_processor(
            TaskType.CHUNK, 
            partial(process_chunk_task,
                    converter=app.state.converter,
                    files_service=app.state.files_service)
        )
        
        await app.state.queue_manager.register_processor(
            TaskType.INDEX, 
            partial(process_index_task,
                    files_service=app.state.files_service,
                    retriever=app.state.retriever)
        )
        
        await app.state.queue_manager.register_processor(
            TaskType.PROCESS_ALL, 
            partial(process_all_task,
                    converter=app.state.converter,
                    files_service=app.state.files_service,
                    retriever=app.state.retriever)
        )
        
        # 在处理器注册后增加验证
        for task_type in [TaskType.CONVERT, TaskType.CHUNK, TaskType.INDEX, TaskType.PROCESS_ALL]:
            if task_type not in app.state.queue_manager._processors:
                logger.error(f"处理器注册失败: {task_type.value}")
            else:
                logger.info(f"处理器注册成功: {task_type.value}")
        
        # 更新FileService的允许扩展名
        allowed_extensions = format_allowed_extensions([fmt.value for fmt in app.state.converter.allowed_formats])
        app.state.files_service.allowed_extensions = allowed_extensions
    
    @app.on_event("shutdown")
    async def shutdown_event():
        """关闭应用时停止任务队列"""
        if hasattr(app.state, "queue_manager"):
            await app.state.queue_manager.stop()
    
    # 获取检索器的依赖
    async def get_retriever():
        return app.state.retriever

    # 获取转换器的依赖
    async def get_converter():
        return app.state.converter
    
    # 获取文件服务的依赖
    async def get_files_service():
        return app.state.files_service
    
    # 获取任务队列管理器
    async def get_queue_manager():
        return app.state.queue_manager
    
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

    # =================== 文件管理相关接口 ===================

    # 获取用户文件列表
    @router.get("/oculith/files")
    async def list_files(
        request: Request,
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
            
            # 直接使用扁平化结构，去掉custom_metadata
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
                # 保留所有其他字段，直接在顶层
                **{k: v for k, v in file_info.items() 
                  if k not in ["id", "original_name", "size", "type", "extension", "path", 
                              "created_at", "updated_at", "status", "title", "description", 
                              "tags", "has_markdown", "has_chunks", "source_type", "source_url",
                              "chunks_count", "chunks"]}
            })
        
        return result
    
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
            # 直接包含所有其他字段
            **{k: v for k, v in file_info.items() 
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
            
        # 直接更新额外字段
        if metadata.extra_fields:
            update_data.update(metadata.extra_fields)
        
        success = await files_service.update_metadata(user_id, file_id, update_data)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法更新")
        
        # 获取更新后的文件信息
        return await files_service.get_file_meta(user_id, file_id)
    
    # 删除文件
    @router.delete("/oculith/files/{file_id}")
    async def delete_file(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        retriever: LanceRetriever = Depends(get_retriever)
    ):
        """删除文件"""
        user_id = token_data["user_id"]
        
        # 1. 首先从向量库中删除文件相关的切片
        try:
            # 使用元数据过滤器删除特定文件的切片
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
        retriever: LanceRetriever = Depends(get_retriever)
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
        retriever: LanceRetriever = Depends(get_retriever)
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
        retriever: LanceRetriever = Depends(get_retriever)
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

    # 新API端点：上传文件
    @router.post("/oculith/files/upload")
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        auto_process: bool = Form(False),  # 添加自动处理参数
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        converter: ObservableConverter = Depends(get_converter),
        retriever: LanceRetriever = Depends(get_retriever),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """上传文件，可选择是否自动处理"""
        user_id = token_data["user_id"]
        logger.info(f"上传文件请求: 用户ID={user_id}, 文件名={file.filename}, 自动处理={auto_process}")
        
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
            
            # 返回基本文件信息
            result = {
                "success": True,
                "file_id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "extension": file_info.get("extension", ""),
                "created_at": file_info["created_at"],
                "status": FileProcessStatus.UPLOADED.value,
                "download_url": str(request.url_for("download_file", file_id=file_info["id"])),
            }
            
            # 如果自动处理选项开启，添加处理任务
            if auto_process:
                # 确保队列管理器正在运行
                await ensure_queue_manager_running(queue_manager)
                
                # 创建处理任务
                task = FileTask(
                    user_id=user_id,
                    file_id=file_info["id"],
                    task_type=TaskType.PROCESS_ALL,
                    priority=0
                )
                
                # 添加任务到队列
                task_id = await queue_manager.add_task(task)
                
                # 添加任务信息到结果
                result.update({
                    "auto_process": True,
                    "task_id": task_id,
                    "task_type": TaskType.PROCESS_ALL.value,
                    "process_status": FileProcessStatus.QUEUED.value,
                    "process_stream_url": str(request.url_for("stream_file_processing", file_id=file_info["id"]))
                })
            
            return result
        except ValueError as e:
            logger.error(f"文件上传失败: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # 新API端点：文件处理流
    @router.get("/oculith/files/{file_id}/process/stream")
    async def stream_file_processing(
        file_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """以SSE流的形式获取文件处理状态更新"""
        user_id = token_data["user_id"]
        
        # 验证队列管理器状态
        logger.info(f"SSE流启动: file_id={file_id}, 队列管理器状态={queue_manager.is_running}, 活动任务数={len(queue_manager.active_tasks)}")
        
        # 获取当前任务状态
        file_tasks = await queue_manager.get_file_tasks(user_id, file_id)
        if file_tasks:
            logger.info(f"文件相关任务: {len(file_tasks)}个")
            for task in file_tasks:
                logger.info(f"任务状态: id={task['task_id']}, 类型={task['task_type']}, 状态={task['status']}")
        
        # 获取文件信息
        file_info = await files_service.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            logger.error(f"文件不存在: {file_id}")
            raise HTTPException(status_code=404, detail="文件不存在")
        
        logger.info(f"文件信息: {file_info}")
        
        async def status_stream():
            # 发送初始状态
            try:
                initial_status = await queue_manager.get_file_status(user_id, file_id)
                logger.info(f"SSE初始状态: {initial_status}")
                yield format_sse({
                    "type": "status",
                    "file_id": file_id,
                    "status": initial_status["status"],
                    "timestamp": time.time()
                }, event="status")
                await asyncio.sleep(0.01)
                
                # 监控状态变化
                last_status = initial_status["status"]
                check_interval = 1.0  # 初始检查间隔
                max_interval = 5.0    # 最大检查间隔
                max_duration = 300    # 最大监控时间（秒）
                start_time = time.time()
                update_count = 0
                
                while time.time() - start_time < max_duration:
                    try:
                        current_status = await queue_manager.get_file_status(user_id, file_id)
                        current = current_status["status"]
                        update_count += 1
                        
                        if update_count % 5 == 0:  # 每5次输出一次日志，避免日志过多
                            logger.info(f"SSE状态检查 #{update_count}: 当前={current}, 上次={last_status}, 运行时间={time.time() - start_time:.1f}秒")
                        
                        # 状态发生变化，发送更新
                        if current != last_status:
                            logger.info(f"SSE状态变化: {last_status} -> {current}")
                            yield format_sse({
                                "type": "status",
                                "file_id": file_id,
                                "status": current,
                                "previous_status": last_status,
                                "timestamp": time.time()
                            }, event="status")
                            await asyncio.sleep(0.01)
                            last_status = current
                            
                            # 如果到达终态，结束流
                            if current in [FileProcessStatus.COMPLETED.value, FileProcessStatus.FAILED.value]:
                                logger.info(f"SSE检测到终态: {current}, 结束流")
                                yield format_sse({
                                    "type": "complete", 
                                    "file_id": file_id,
                                    "final_status": current,
                                    "timestamp": time.time()
                                }, event="complete")
                                return
                    
                        # 提供定期更新，即使状态没有变化
                        if (time.time() - start_time) % 10 < 1.0:  # 每10秒发送一次心跳
                            logger.info(f"SSE发送心跳: status={current}")
                            yield format_sse({
                                "type": "heartbeat",
                                "file_id": file_id,
                                "status": current,
                                "timestamp": time.time()
                            }, event="heartbeat")
                            await asyncio.sleep(0.01)
                        
                        # 等待下一次检查
                        await asyncio.sleep(check_interval)
                    except Exception as e:
                        logger.error(f"SSE状态检查异常: {str(e)}")
                        await asyncio.sleep(1.0)  # 出错后等待一秒
                    
                    # 根据情况调整检查间隔
                    if current in [FileProcessStatus.QUEUED.value]:
                        check_interval = min(check_interval * 1.2, max_interval)  # 排队中，逐渐增加间隔
                    else:
                        check_interval = 1.0  # 活跃处理中，保持较短间隔
            except Exception as e:
                logger.error(f"SSE流异常: {str(e)}", exc_info=True)
                yield format_sse({
                    "type": "error",
                    "file_id": file_id,
                    "message": f"监控状态时出错: {str(e)}",
                    "timestamp": time.time()
                }, event="error")
        
        # 返回SSE流响应
        logger.info(f"返回SSE流响应: file_id={file_id}")
        return StreamingResponse(
            status_stream(),
            media_type="text/event-stream"
        )
    
    # 新API端点：处理文件 - 可以指定步骤
    @router.post("/oculith/files/{file_id}/process")
    async def process_file(
        request: Request,
        file_id: str,
        step: Optional[str] = Form("all"),  # convert, chunk, index, all
        priority: int = Form(0),
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """添加文件处理任务到队列 - 统一处理入口"""
        user_id = token_data["user_id"]
        logger.info(f"处理文件请求: 用户ID={user_id}, 文件ID={file_id}, 步骤={step}, 优先级={priority}")
        
        # 确保队列管理器正在运行
        await ensure_queue_manager_running(queue_manager)
        
        # 获取文件信息
        file_info = await files_service.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 确定任务类型
        task_type = None
        if step == "convert":
            task_type = TaskType.CONVERT
        elif step == "chunk":
            task_type = TaskType.CHUNK
        elif step == "index":
            task_type = TaskType.INDEX
        elif step == "all":
            task_type = TaskType.PROCESS_ALL
        else:
            raise HTTPException(status_code=400, detail="无效的处理步骤")
        
        # 检查步骤依赖关系
        if step == "chunk" and not file_info.get("has_markdown", False):
            logger.warning(f"文件{file_id}尚未转换为Markdown，无法直接进行切片操作")
            # 可以考虑自动切换为PROCESS_ALL，或返回错误
        
        if step == "index" and not file_info.get("has_chunks", False):
            logger.warning(f"文件{file_id}尚未切片，无法直接进行索引操作")
            # 可以考虑自动切换为适当步骤，或返回错误
        
        # 创建任务
        task = FileTask(
            user_id=user_id,
            file_id=file_id,
            task_type=task_type,
            priority=priority
        )
        
        # 添加任务到队列
        task_id = await queue_manager.add_task(task)
        
        # 返回详细信息
        return {
            "success": True,
            "file_id": file_id,
            "original_name": file_info["original_name"],
            "task_id": task_id,
            "task_type": task_type.value,
            "step": step,
            "priority": priority,
            "status": FileProcessStatus.QUEUED.value,
            "message": "任务已添加到队列",
            "process_stream_url": str(request.url_for("stream_file_processing", file_id=file_id))
        }
    
    # 新API端点：任务状态查询
    @router.get("/oculith/tasks/{task_id}")
    async def get_task_status(
        task_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """获取任务状态"""
        # 获取任务状态
        task_status = await queue_manager.get_task_status(task_id)
        if not task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # 只允许查看自己的任务
        if task_status["user_id"] != token_data["user_id"]:
            raise HTTPException(status_code=403, detail="无权访问此任务")
        
        return task_status
    
    # 新API端点：取消任务
    @router.post("/oculith/tasks/{task_id}/cancel")
    async def cancel_task(
        task_id: str,
        token_data: Dict[str, Any] = Depends(verify_token),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """取消任务"""
        # 获取任务状态
        task_status = await queue_manager.get_task_status(task_id)
        if not task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # 只允许取消自己的任务
        if task_status["user_id"] != token_data["user_id"]:
            raise HTTPException(status_code=403, detail="无权取消此任务")
        
        # 取消任务
        success = await queue_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="无法取消任务，可能已完成或失败")
        
        return {
            "success": True,
            "task_id": task_id,
            "message": "任务已取消"
        }

    # 远程文件收藏与处理
    @router.post("/oculith/files/bookmark-remote")
    async def bookmark_remote_file(
        request: Request,
        url: str = Form(...),
        filename: Optional[str] = Form(None),
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        auto_process: bool = Form(False),  # 是否自动开始处理
        token_data: Dict[str, Any] = Depends(verify_token),
        files_service: FilesService = Depends(get_files_service),
        converter: ObservableConverter = Depends(get_converter),
        retriever: LanceRetriever = Depends(get_retriever),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """收藏远程URL文件，可选择是否自动处理"""
        user_id = token_data["user_id"]
        logger.info(f"收藏远程文件请求: 用户ID={user_id}, URL={url}, 自动处理={auto_process}")
        
        # 验证URL格式
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="无效的URL格式")
        
        try:
            # 确定文件名
            if not filename:
                import urllib.parse
                filename = os.path.basename(urllib.parse.urlparse(url).path) or "remote_document"
                if not filename.strip():
                    filename = "remote_document.html"
            
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
            
            metadata["source"] = "url"
            
            # 创建远程文件记录
            file_info = await files_service.create_remote_file_record(
                user_id=user_id,
                url=url,
                filename=filename,
                metadata=metadata
            )
            
            # 返回基本文件信息
            result = {
                "success": True,
                "file_id": file_info["id"],
                "original_name": file_info["original_name"],
                "type": file_info["type"],
                "extension": file_info.get("extension", ""),
                "created_at": file_info["created_at"],
                "status": FileProcessStatus.UPLOADED.value,
                "source_type": "remote",
                "source_url": url
            }
            
            # 如果自动处理选项开启，添加处理任务
            if auto_process:
                # 确保队列管理器正在运行
                await ensure_queue_manager_running(queue_manager)
                
                # 创建处理任务
                task = FileTask(
                    user_id=user_id,
                    file_id=file_info["id"],
                    task_type=TaskType.PROCESS_ALL,
                    priority=0
                )
                
                # 添加任务到队列
                task_id = await queue_manager.add_task(task)
                
                # 添加任务信息到结果
                result.update({
                    "auto_process": True,
                    "task_id": task_id,
                    "task_type": TaskType.PROCESS_ALL.value,
                    "process_status": FileProcessStatus.QUEUED.value,
                    "process_stream_url": str(request.url_for("stream_file_processing", file_id=file_info["id"]))
                })
            
            return result
        except Exception as e:
            logger.error(f"收藏远程文件失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # 新API端点：队列状态诊断
    @router.get("/oculith/queue/diagnostics")
    async def get_queue_diagnostics(
        token_data: Dict[str, Any] = Depends(verify_token),
        queue_manager: QueueManager = Depends(get_queue_manager)
    ):
        """获取队列管理器的诊断信息，用于调试"""
        # 尝试获取管理员标志（可选）
        is_admin = token_data.get("is_admin", False)
        
        # 获取基本诊断信息
        diagnostics = await queue_manager.get_diagnostics()
        
        # 检查陷入停滞的任务
        stalled_tasks = await queue_manager.check_stalled_tasks()
        diagnostics["stalled_tasks"] = stalled_tasks
        
        # 非管理员用户只返回基本信息
        if not is_admin:
            return {
                "is_running": diagnostics["is_running"],
                "queue_size": diagnostics["queue_size"],
                "active_tasks_count": diagnostics["active_tasks_count"],
                "status_counts": diagnostics["status_counts"],
                "stalled_tasks_count": len(stalled_tasks)
            }
        
        # 管理员用户返回完整信息
        return diagnostics

    # 注册路由
    app.include_router(router, prefix=prefix)

async def delete_file_chunks_from_vectordb(user_id: str, file_id: str, retriever: LanceRetriever) -> None:
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

# 任务处理函数

async def process_convert_task(
    task: FileTask,
    converter: ObservableConverter,
    files_service: FilesService
) -> Dict[str, Any]:
    """处理文档转换任务"""
    user_id = task.user_id
    file_id = task.file_id
    
    try:
        # 获取文件信息
        file_info = await files_service.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return {
                "success": False,
                "error": f"文件不存在或已删除: {file_id}"
            }
        
        # 检查是否为纯文本格式文件（md、markdown、txt）或HTML文件，这些文件可以直接保存为markdown
        file_extension = file_info.get("extension", "").lower()
        direct_process_extensions = [".md", ".markdown", ".txt", ".html", ".htm"]
        
        if file_extension in direct_process_extensions:
            logger.info(f"检测到直接支持的文件格式: {file_id}，扩展名: {file_extension}，将直接处理")
            
            # 获取文件路径或内容
            file_path = None
            file_content = None
            
            if file_info.get("source_type") == "local":
                # 本地文件，直接读取内容
                file_path = files_service.get_raw_file_path(user_id, file_id)
                if not file_path.exists():
                    return {
                        "success": False,
                        "error": "文件不存在"
                    }
                try:
                    # 尝试以UTF-8读取
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                except UnicodeDecodeError:
                    # 如果UTF-8解码失败，尝试以二进制读取再解码
                    with open(file_path, "rb") as f:
                        binary_data = f.read()
                    try:
                        # 尝试检测编码并解码
                        import chardet
                        detected = chardet.detect(binary_data)
                        file_content = binary_data.decode(detected["encoding"] or "utf-8", errors="replace")
                    except:
                        # 所有尝试都失败，使用安全的替换机制
                        file_content = binary_data.decode("utf-8", errors="replace")
                        
            elif file_info.get("source_type") == "remote":
                # 远程文件，需要下载内容
                import aiohttp
                url = file_info.get("source_url")
                if not url:
                    return {
                        "success": False,
                        "error": "远程文件没有有效的URL"
                    }
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as response:
                            if response.status != 200:
                                return {
                                    "success": False,
                                    "error": f"无法下载远程文件: HTTP {response.status}"
                                }
                            
                            # 获取内容类型
                            content_type = response.headers.get("Content-Type", "")
                            logger.info(f"远程文件内容类型: {content_type}")
                            
                            if "text/html" in content_type or file_extension in [".html", ".htm"]:
                                # HTML内容需要特殊处理
                                html_content = await response.text()
                                
                                # 简单HTML到Markdown转换
                                try:
                                    import html2text
                                    h = html2text.HTML2Text()
                                    h.ignore_links = False
                                    h.ignore_images = False
                                    h.ignore_tables = False
                                    file_content = h.handle(html_content)
                                except ImportError:
                                    # 如果没有html2text库，直接使用HTML内容
                                    file_content = html_content
                                    logger.warning("未找到html2text库，将直接使用HTML内容")
                            else:
                                # 普通文本内容
                                file_content = await response.text()
                except Exception as e:
                    logger.error(f"下载远程文件内容失败: {str(e)}", exc_info=True)
                    return {
                        "success": False,
                        "error": f"下载远程文件内容失败: {str(e)}"
                    }
            
            if not file_content:
                return {
                    "success": False,
                    "error": "无法获取文件内容"
                }
            
            # 直接保存为Markdown文件
            await files_service.save_markdown_file(
                user_id=user_id,
                file_id=file_id,
                markdown_content=file_content,
                metadata={"conversion_status": "SUCCESS"}
            )
            
            return {
                "success": True,
                "message": "文件直接保存为Markdown，无需转换",
                "markdown_length": len(file_content)
            }
        
        # 获取文件路径
        file_path = None
        if file_info.get("source_type") == "local":
            # 本地文件直接获取路径
            file_path = files_service.get_raw_file_path(user_id, file_id)
            if not file_path.exists():
                return {
                    "success": False,
                    "error": "文件不存在"
                }
        elif file_info.get("source_type") == "remote":
            # 远程文件直接使用URL作为源
            file_path = file_info.get("source_url")
            if not file_path:
                return {
                    "success": False,
                    "error": "远程文件没有有效的URL"
                }
        
        if not file_path:
            return {
                "success": False,
                "error": "无法确定文件路径"
            }
        
        # 执行转换
        doc_result = None
        
        # 收集所有更新
        updates = []
        logger.info(f"开始处理文件: {file_path}, 类型: {type(file_path)}")
        async for update in converter.convert_async(
            source=str(file_path) if isinstance(file_path, Path) else file_path,
            doc_id=file_id,
            raises_on_error=False
        ):
            updates.append(update)
            if "document" in update:
                doc_result = update
        
        # 处理转换结果
        if doc_result and "document" in doc_result:
            document = doc_result["document"]
            
            # 转换为Markdown
            markdown_content = document.export_to_markdown()
            
            # 保存Markdown文件
            await files_service.save_markdown_file(
                user_id=user_id,
                file_id=file_id,
                markdown_content=markdown_content,
                metadata={"conversion_status": "SUCCESS"}
            )
            
            return {
                "success": True,
                "message": "文档成功转换为Markdown",
                "markdown_length": len(markdown_content)
            }
        else:
            # 处理失败
            error_msg = "转换过程未产生有效文档"
            for update in updates:
                if update.get("stage") == "ERROR":
                    error_msg = update.get("error", error_msg)
            
            # 更新文件元数据
            await files_service.update_metadata(user_id, file_id, {
                "converted": False,
                "conversion_status": "ERROR",
                "conversion_time": time.time(),
                "conversion_error": error_msg
            })
            
            return {
                "success": False,
                "error": error_msg
            }
    except Exception as e:
        logger.error(f"处理转换任务异常: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": f"处理异常: {str(e)}"
        }


async def process_chunk_task(
    task: FileTask,
    converter: ObservableConverter,
    files_service: FilesService
) -> Dict[str, Any]:
    """处理文档切片任务"""
    user_id = task.user_id
    file_id = task.file_id
    
    try:
        # 获取文件信息
        file_info = await files_service.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return {
                "success": False,
                "error": f"文件不存在或已删除: {file_id}"
            }
        
        # 检查是否已经转换为Markdown
        if not file_info.get("has_markdown", False):
            return {
                "success": False,
                "error": "文件尚未转换为Markdown，请先执行转换任务"
            }
        
        # 获取Markdown内容
        markdown_content = await files_service.get_markdown_content(user_id, file_id)
        
        # 使用HybridChunker进行文本切片
        from docling.chunking import HybridChunker
        chunker = HybridChunker()
        
        # 简单的文本切片实现
        chunks = []
        chunk_size = 1000  # 自定义切片大小
        for i in range(0, len(markdown_content), chunk_size):
            chunk_text = markdown_content[i:i+chunk_size]
            chunks.append({
                "content": chunk_text,
                "metadata": {
                    "chunk_index": i // chunk_size,
                    "file_id": file_id,
                    "original_name": file_info.get("original_name", ""),
                    "source_type": file_info.get("source_type", "local"),
                    "user_id": user_id  # 添加用户ID方便向量存储过滤
                }
            })
        
        # 保存切片
        await files_service.save_chunks(
            user_id=user_id,
            file_id=file_id,
            chunks=chunks
        )
        
        return {
            "success": True,
            "message": "文档成功切片",
            "chunks_count": len(chunks)
        }
    except Exception as e:
        logger.error(f"处理切片任务异常: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": f"处理异常: {str(e)}"
        }


async def process_index_task(
    task: FileTask,
    files_service: FilesService,
    retriever: LanceRetriever
) -> Dict[str, Any]:
    """处理向量索引任务"""
    user_id = task.user_id
    file_id = task.file_id
    
    try:
        # 获取文件信息
        file_info = await files_service.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return {
                "success": False,
                "error": f"文件不存在或已删除: {file_id}"
            }
        
        # 检查是否已经切片
        if not file_info.get("has_chunks", False):
            return {
                "success": False,
                "error": "文件尚未切片，请先执行切片任务"
            }
        
        # 向量化所有切片
        indexed_chunks = 0
        total_chunks = file_info.get("chunks_count", 0)
        skipped_chunks = 0
        
        async for chunk_data in files_service.iter_chunks_content(user_id, file_id):
            try:
                add_result = await retriever.add(
                    texts=chunk_data["content"],
                    user_id=user_id,
                    metadatas={
                        "file_id": file_id,
                        "chunk_index": chunk_data.get("chunk_index", 0),
                        **chunk_data.get("metadata", {})
                    }
                )
                
                if isinstance(add_result, dict):
                    indexed_chunks += add_result.get("added", 0)
                    skipped_chunks += add_result.get("skipped", 0)
            except Exception as e:
                logger.error(f"向量化切片失败: {str(e)}")
                skipped_chunks += 1
        
        # 尝试创建索引
        await retriever.ensure_index()
        
        # 更新文件元数据
        await files_service.update_metadata(user_id, file_id, {
            "indexed": True,
            "indexed_chunks": indexed_chunks,
            "skipped_chunks": skipped_chunks,
            "indexing_time": time.time()
        })
        
        return {
            "success": True,
            "message": "文档成功索引",
            "indexed_chunks": indexed_chunks,
            "total_chunks": total_chunks,
            "skipped_chunks": skipped_chunks
        }
    except Exception as e:
        logger.error(f"处理索引任务异常: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": f"处理异常: {str(e)}"
        }


async def process_all_task(
    task: FileTask,
    converter: ObservableConverter,
    files_service: FilesService,
    retriever: LanceRetriever
) -> Dict[str, Any]:
    """处理完整的文档流程"""
    user_id = task.user_id
    file_id = task.file_id
    
    # 1. 执行转换
    convert_result = await process_convert_task(task, converter, files_service)
    if not convert_result.get("success", False):
        return convert_result
    
    # 2. 执行切片
    chunk_result = await process_chunk_task(task, converter, files_service)
    if not chunk_result.get("success", False):
        return chunk_result
    
    # 3. 执行索引
    index_result = await process_index_task(task, files_service, retriever)
    return index_result
