"""可观测文档转换器

提供与官方DocumentConverter相同的功能，但增加异步处理和可观测能力。
"""

import logging
import time
import asyncio
import hashlib
import sys  # 添加sys导入，用于sys.maxsize
from typing import Dict, Any, Optional, AsyncGenerator, Union, List, Type, Tuple
from pathlib import Path
from datetime import datetime
from functools import partial

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

# 导入docling组件
from docling.pipeline.base_pipeline import BasePipeline
from docling.datamodel.document import ConversionResult, InputDocument
from docling.datamodel.base_models import (
    ConversionStatus, InputFormat, DocumentStream, ErrorItem, DoclingComponentType
)
from docling.document_converter import (
    DocumentConverter, FormatOption, _get_default_option
)
from docling.datamodel.settings import DocumentLimits, PageRange, DEFAULT_PAGE_RANGE
from docling.exceptions import ConversionError
from docling.chunking import HybridChunker

# 导入自定义组件
from .retriever import LanceRetriever
from .schemas import DocumentProcessStage, DocumentProcessStatus
from .pipeline import ObservablePipelineWrapper
from .file_service import FilesService

logger = logging.getLogger(__name__)


class ObservableConverter:
    """可观测文档转换器
    
    与官方DocumentConverter保持一致的接口和行为，同时提供异步处理和可观测能力。
    """
    
    def __init__(
        self,
        allowed_formats: Optional[List[InputFormat]] = None,
        format_options: Optional[Dict[InputFormat, FormatOption]] = None,
        files_service: Optional[FilesService] = None
    ):
        """初始化可观测转换器
        
        Args:
            allowed_formats: 允许处理的文档格式列表，为空表示允许所有支持的格式
            format_options: 各格式对应的处理选项
            files_service: 文件服务实例
        """
        # 与官方实现保持一致
        self.allowed_formats = (
            allowed_formats if allowed_formats is not None else [e for e in InputFormat]
        )
        
        # 为每种格式设置选项，与官方实现保持一致
        self.format_to_options = {
            format: (
                _get_default_option(format=format)
                if (custom_option := (format_options or {}).get(format)) is None
                else custom_option
            )
            for format in self.allowed_formats
        }
        
        # 缓存原始pipeline
        self.initialized_pipelines: Dict[
            Tuple[Type[BasePipeline], str], BasePipeline
        ] = {}
        
        # 缓存已包装的observable pipeline
        self.observable_pipelines: Dict[
            Tuple[Type[BasePipeline], str, str], ObservablePipelineWrapper
        ] = {}
        
        # 兼容旧代码，使converter指向自身
        self.converter = self
        
        self.files_service = files_service  # 保存FileService实例
    
    def _get_pipeline_options_hash(self, pipeline_options) -> str:
        """生成pipeline选项的哈希值，用于缓存"""
        # 与官方实现保持一致
        options_str = str(pipeline_options.model_dump())
        return hashlib.md5(options_str.encode("utf-8")).hexdigest()
    
    def _get_pipeline(self, doc_format: InputFormat) -> Optional[BasePipeline]:
        """获取用于处理特定格式的pipeline实例
        
        Args:
            doc_format: 文档格式
            
        Returns:
            对应的pipeline实例，如果不支持该格式则返回None
        """
        # 与官方实现保持一致
        fopt = self.format_to_options.get(doc_format)
        
        if fopt is None or fopt.pipeline_options is None:
            return None

        pipeline_class = fopt.pipeline_cls
        pipeline_options = fopt.pipeline_options
        options_hash = self._get_pipeline_options_hash(pipeline_options)

        # 使用复合键缓存pipeline
        cache_key = (pipeline_class, options_hash)

        if cache_key not in self.initialized_pipelines:
            logger.debug(
                f"初始化pipeline: {pipeline_class.__name__}, 选项哈希: {options_hash}"
            )
            self.initialized_pipelines[cache_key] = pipeline_class(
                pipeline_options=pipeline_options
            )
        else:
            logger.debug(
                f"复用已缓存pipeline: {pipeline_class.__name__}, 选项哈希: {options_hash}"
            )

        return self.initialized_pipelines[cache_key]
    
    def _get_observable_pipeline(
        self, 
        doc_format: InputFormat, 
        status_tracker: DocumentProcessStatus
    ) -> Optional[ObservablePipelineWrapper]:
        """获取可观测的pipeline实例
        
        Args:
            doc_format: 文档格式
            status_tracker: 状态跟踪器
            
        Returns:
            可观测的pipeline实例，如果不支持该格式则返回None
        """
        # 获取原始pipeline
        pipeline = self._get_pipeline(doc_format)
        if pipeline is None:
            return None
        
        # 获取pipeline类型和选项哈希
        pipeline_class = type(pipeline)
        options_hash = self._get_pipeline_options_hash(pipeline.pipeline_options)
        doc_id = status_tracker.doc_id
        
        # 复合缓存键
        cache_key = (pipeline_class, options_hash, doc_id)
        
        # 检查缓存
        if cache_key not in self.observable_pipelines:
            self.observable_pipelines[cache_key] = ObservablePipelineWrapper(
                pipeline=pipeline,
                status_tracker=status_tracker
            )
        
        return self.observable_pipelines[cache_key]
    
    def _wrap_pipeline(
        self, 
        pipeline: BasePipeline, 
        status_tracker: DocumentProcessStatus
    ) -> ObservablePipelineWrapper:
        """包装原始pipeline为可观测pipeline
        
        此方法用于兼容create_async_observable_converter函数，
        允许直接传入pipeline实例而非通过格式查找。
        
        Args:
            pipeline: 原始pipeline实例
            status_tracker: 状态跟踪器
            
        Returns:
            可观测的pipeline实例
        """
        # 获取pipeline类型和选项哈希
        pipeline_class = type(pipeline)
        options_hash = self._get_pipeline_options_hash(pipeline.pipeline_options)
        doc_id = status_tracker.doc_id
        
        # 复合缓存键
        cache_key = (pipeline_class, options_hash, doc_id)
        
        # 检查缓存
        if cache_key not in self.observable_pipelines:
            self.observable_pipelines[cache_key] = ObservablePipelineWrapper(
                pipeline=pipeline,
                status_tracker=status_tracker
            )
        
        return self.observable_pipelines[cache_key]
    
    def convert(
        self,
        source: Union[Path, str, DocumentStream],
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: int = sys.maxsize,
        max_file_size: int = sys.maxsize,
        page_range: PageRange = DEFAULT_PAGE_RANGE,
    ) -> ConversionResult:
        """同步转换文档
        
        与官方DocumentConverter.convert保持一致的接口
        
        Args:
            source: 文档来源（路径、URL或文档流）
            headers: HTTP头信息（用于URL请求）
            raises_on_error: 错误时是否抛出异常
            max_num_pages: 处理的最大页数限制
            max_file_size: 处理的最大文件大小限制
            page_range: 处理的页面范围
            
        Returns:
            转换结果
        """
        # 创建临时DocumentConverter实例，确保线程安全
        kwargs = {}
        if self.format_to_options:
            kwargs["format_options"] = self.format_to_options
        if self.allowed_formats:
            kwargs["allowed_formats"] = self.allowed_formats
        converter = DocumentConverter(**kwargs)
        
        # 调用其convert方法
        return converter.convert(
            source=source,
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
            page_range=page_range
        )
    
    async def convert_async(
        self,
        source: Union[Path, str, DocumentStream],
        doc_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: int = sys.maxsize,
        max_file_size: int = sys.maxsize,
        page_range: PageRange = DEFAULT_PAGE_RANGE,
        status_tracker: Optional[DocumentProcessStatus] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """异步转换文档，产生状态更新和结果
        
        Args:
            source: 文档来源（路径、URL或文档流）
            doc_id: 文档ID，为None时自动生成（如果未提供status_tracker）
            headers: HTTP头信息（用于URL请求）
            raises_on_error: 错误时是否抛出异常
            max_num_pages: 处理的最大页数限制
            max_file_size: 处理的最大文件大小限制
            page_range: 处理的页面范围
            status_tracker: 状态跟踪器，为None时自动创建
            
        Yields:
            状态更新和处理结果
        """
        # 创建状态跟踪器，如果未提供则创建
        if status_tracker is None:
            if doc_id is None:
                doc_id = f"doc_{int(time.time())}"
            status_tracker = DocumentProcessStatus(doc_id=doc_id)
        
        # 更新状态：初始化
        status_tracker.update(
            stage=DocumentProcessStage.INIT,
            progress=0.1,
            message="开始文档转换"
        )
        yield status_tracker.to_dict()
        
        try:
            # 获取输入文档（异步执行）
            loop = asyncio.get_running_loop()
            
            # 使用线程池执行文档准备
            in_doc = await loop.run_in_executor(
                None,
                partial(
                    self._prepare_input_document,
                    source=source,
                    headers=headers,
                    raises_on_error=raises_on_error,
                    max_num_pages=max_num_pages,
                    max_file_size=max_file_size,
                    page_range=page_range,
                    status_tracker=status_tracker
                )
            )
            
            if in_doc is None:
                status_tracker.update(
                    stage=DocumentProcessStage.ERROR,
                    progress=1.0,
                    message="准备文档失败",
                    error="无法创建输入文档"
                )
                yield status_tracker.to_dict()
                return
            
            # 更新状态：文档准备完成
            status_tracker.update(
                stage=DocumentProcessStage.PROCESSING,
                progress=0.2,
                message=f"文档已加载，格式: {in_doc.format.value if in_doc.format else 'unknown'}, 正在获取处理管道"
            )
            yield status_tracker.to_dict()
            
            # 获取可观测pipeline
            observable_pipeline = self._get_observable_pipeline(in_doc.format, status_tracker)
            if observable_pipeline is None:
                error_msg = f"无法获取文档格式 {in_doc.format.value if in_doc.format else 'unknown'} 的处理管道"
                status_tracker.update(
                    stage=DocumentProcessStage.ERROR,
                    progress=1.0,
                    message=error_msg,
                    error=error_msg
                )
                yield status_tracker.to_dict()
                return
            
            # 执行异步处理并产生更新
            pipeline_update_count = 0
            async for update in observable_pipeline.execute_async(in_doc, raises_on_error):
                pipeline_update_count += 1
                logger.debug(f"从pipeline获取第{pipeline_update_count}个更新: 类型={type(update)}, 键={list(update.keys())}")
                yield update
                
        except Exception as e:
            # 记录错误并更新状态
            error_msg = f"文档处理过程中出现异常: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            status_tracker.update(
                stage=DocumentProcessStage.ERROR,
                progress=1.0,
                message=error_msg,
                error=str(e)
            )
            yield status_tracker.to_dict()
            
            if raises_on_error:
                raise
    
    def _prepare_input_document(
        self,
        source: Union[Path, str, DocumentStream],
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: int = sys.maxsize,
        max_file_size: int = sys.maxsize,
        page_range: PageRange = DEFAULT_PAGE_RANGE,
        status_tracker: Optional[DocumentProcessStatus] = None
    ) -> Optional[InputDocument]:
        """准备输入文档
        
        Args:
            source: 文档来源
            headers: HTTP头信息
            raises_on_error: 错误时是否抛出异常
            max_num_pages: 最大页数限制
            max_file_size: 最大文件大小限制
            page_range: 页面范围
            status_tracker: 状态跟踪器(可选)
            
        Returns:
            准备好的InputDocument实例
        """
        try:
            # 创建文档限制
            limits = DocumentLimits(
                max_num_pages=max_num_pages,
                max_file_size=max_file_size,
                page_range=page_range
            )
            
            # 创建转换输入
            from docling.datamodel.document import _DocumentConversionInput
            conv_input = _DocumentConversionInput(
                path_or_stream_iterator=[source],
                limits=limits,
                headers=headers
            )
            
            # 创建临时DocumentConverter来处理文档准备
            # 这里仅仅为了获取InputDocument，不执行完整转换
            temp_converter = DocumentConverter(
                allowed_formats=self.allowed_formats,
                format_options=self.format_to_options
            )
            
            # 获取第一个输入文档
            for in_doc in conv_input.docs(temp_converter.format_to_options):
                # 只需要第一个文档
                return in_doc
                
            return None
            
        except Exception as e:
            logger.error(f"准备输入文档时出错: {str(e)}", exc_info=True)
            if status_tracker:
                status_tracker.update(
                    stage=DocumentProcessStage.ERROR,
                    progress=0.0,
                    message=f"准备文档失败: {str(e)}",
                    error=str(e)
                )
            if raises_on_error:
                raise
            return None

    async def convert_and_save(
        self,
        source: Union[Path, str, DocumentStream],
        user_id: str,
        file_id: str,
        doc_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: int = sys.maxsize,
        max_file_size: int = sys.maxsize,
        page_range: PageRange = DEFAULT_PAGE_RANGE,
        retriever: Optional[LanceRetriever] = None
    ) -> Dict[str, Any]:
        """转换文档并保存结果"""
        # 存储所有更新
        all_updates = []
        doc_result = None
        update_count = 0
        
        # 记录开始转换
        logger.debug(f"开始转换并保存文档: source={source}, user_id={user_id}, file_id={file_id}")
        
        async for update in self.convert_async(
            source=source,
            doc_id=doc_id,
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
            page_range=page_range
        ):
            update_count += 1
            # 记录每个更新的基本信息
            logger.debug(f"收到第{update_count}个更新: 类型={type(update)}, 包含键={list(update.keys())}")
            
            all_updates.append(update)
            # 特别寻找包含文档对象的更新
            if "document" in update:
                logger.debug(f"找到包含document的更新: stage={update.get('stage')}, type={type(update['document'])}")
                doc_result = update
        
        # 记录处理结果
        logger.debug(f"处理完成: 共收到{update_count}个更新, 找到document对象: {doc_result is not None}")
        
        if doc_result and "document" in doc_result:
            # 提取文档对象
            document = doc_result["document"]
            logger.debug(f"成功提取document对象，类型: {type(document)}")
            
            # 转换为markdown
            markdown_content = document.export_to_markdown()
            
            # 保存为markdown文件并更新元数据
            md_file = await self.files_service.save_markdown_file(
                user_id=user_id,
                file_id=file_id,
                markdown_content=markdown_content,
                metadata={
                    "conversion_status": doc_result.get("status", "SUCCESS")
                }
            )
            
            # 对文档进行切片
            chunks = self.chunk_document(document)
            
            # 保存切片
            chunks_info = await self.files_service.save_chunks(
                user_id=user_id,
                file_id=file_id,
                chunks=chunks
            )
            
            # 如果提供了检索器，则添加切片到向量库
            if retriever:
                # 遍历所有切片
                async for chunk_data in self.files_service.iter_chunks_content(user_id, file_id):
                    try:
                        # 添加到向量库
                        await retriever.add(
                            texts=chunk_data["content"],
                            user_id=user_id,
                            metadatas=chunk_data["metadata"]
                        )
                    except Exception as e:
                        logger.error(f"向量化切片失败: {str(e)}")
            
            # 返回成功结果
            return {
                "success": True,
                "file_id": file_id,
                "content": markdown_content,
                "chunks_count": len(chunks)
            }
        
        # 处理失败情况
        return {
            "success": False,
            "error": "转换失败" if doc_result else "未获得转换结果"
        }

    def chunk_document(self, document) -> List[Dict[str, Any]]:
        """对文档进行切片
        
        Args:
            document: docling 文档对象
            
        Returns:
            List[Dict[str, Any]]: 切片列表，每个切片包含原始文本和富集文本
        """
        chunker = HybridChunker()
        chunks = []
        
        # 对文档进行切片
        for i, chunk in enumerate(chunker.chunk(dl_doc=document)):
            enriched_text = chunker.serialize(chunk=chunk)
            chunks.append({
                "index": i,
                "text": chunk.text,
                "enriched_text": enriched_text
            })
        
        return chunks
