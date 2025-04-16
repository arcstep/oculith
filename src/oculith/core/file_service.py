from typing import List, Dict, Any, Optional, AsyncGenerator
from pathlib import Path
import os
import shutil
import uuid
import time
import aiofiles
import logging
import mimetypes
import asyncio
import json
from fastapi import UploadFile, HTTPException, Depends, APIRouter, File, Form

logger = logging.getLogger(__name__)

class FileStatus:
    """文件状态枚举"""
    ACTIVE = "active"      # 活跃文件
    DELETED = "deleted"    # 已删除文件
    PROCESSING = "processing"  # 处理中的文件

class FilesService:
    """文件管理服务
    
    基于约定的文件组织结构：
    - {user_id}/raw/{file_id} - 原始文件
    - {user_id}/md/{file_id} - Markdown文件
    - {user_id}/chunks/{file_id}/ - 切片目录
    """
    
    def __init__(
        self, 
        base_dir: str, 
        max_file_size: int = 50 * 1024 * 1024,  # 默认50MB 
        max_total_size_per_user: int = 200 * 1024 * 1024,  # 默认200MB
        allowed_extensions: List[str] = None
    ):
        """初始化文件管理服务"""
        self.base_dir = Path(base_dir)
        self.meta_dir = self.base_dir / "meta"
        self.temp_dir = self.base_dir / "temp"
        
        # 创建基础目录
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_file_size = max_file_size
        self.max_total_size_per_user = max_total_size_per_user
        self.allowed_extensions = allowed_extensions or [
            '.pptx',
            '.md', '.markdown',
            '.pdf', '.docx', '.txt',
            '.jpg', '.jpeg', '.png', '.gif', '.webp'
        ]
        
        # 文件MIME类型映射
        self._mime_types = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.markdown': 'text/markdown',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
    
    # 新的目录管理函数
    def get_user_raw_dir(self, user_id: str) -> Path:
        """获取用户原始文件目录"""
        user_dir = self.base_dir / user_id / "raw"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def get_user_md_dir(self, user_id: str) -> Path:
        """获取用户Markdown文件目录"""
        user_dir = self.base_dir / user_id / "md"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def get_user_chunks_dir(self, user_id: str) -> Path:
        """获取用户切片目录"""
        user_dir = self.base_dir / user_id / "chunks"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def get_user_meta_dir(self, user_id: str) -> Path:
        """获取用户元数据目录"""
        user_meta_dir = self.base_dir / user_id / "meta"
        user_meta_dir.mkdir(parents=True, exist_ok=True)
        return user_meta_dir
    
    def get_user_temp_dir(self, user_id: str) -> Path:
        """获取用户临时文件目录"""
        user_temp_dir = self.temp_dir / user_id
        user_temp_dir.mkdir(parents=True, exist_ok=True)
        return user_temp_dir
    
    # 根据类型获取文件路径
    def get_raw_file_path(self, user_id: str, file_id: str) -> Path:
        """获取原始文件路径"""
        return self.get_user_raw_dir(user_id) / file_id
    
    def get_md_file_path(self, user_id: str, file_id: str) -> Path:
        """获取Markdown文件路径"""
        return self.get_user_md_dir(user_id) / f"{file_id}.md"
    
    def get_chunks_dir_path(self, user_id: str, file_id: str) -> Path:
        """获取切片目录路径"""
        chunks_dir = self.get_user_chunks_dir(user_id) / file_id
        chunks_dir.mkdir(exist_ok=True)
        return chunks_dir
    
    def get_metadata_path(self, user_id: str, file_id: str) -> Path:
        """获取文件元数据路径"""
        return self.get_user_meta_dir(user_id) / f"{file_id}.json"
    
    def generate_file_id(self, original_filename: str = None) -> str:
        """生成文件ID"""
        if original_filename:
            _, ext = os.path.splitext(original_filename)
            return f"{uuid.uuid4().hex}{ext.lower()}"
        return uuid.uuid4().hex
    
    # 修改保存文件方法以适应新结构
    async def save_file(
        self, 
        user_id: str, 
        file: UploadFile,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """保存上传的文件到原始文件目录"""
        # 检查文件类型
        if not self.is_valid_file_type(file.filename):
            raise ValueError(f"不支持的文件类型: {file.filename}")
        
        # 检查用户存储空间
        current_usage = await self.calculate_user_storage_usage(user_id)
        
        # 生成文件ID和路径
        file_id = self.generate_file_id(file.filename)
        file_path = self.get_raw_file_path(user_id, file_id)
        meta_path = self.get_metadata_path(user_id, file_id)
        
        # 保存文件
        file_size = 0
        async with aiofiles.open(file_path, 'wb') as out_file:
            # 分块读取并写入文件
            while content := await file.read(1024 * 1024):  # 每次读取1MB
                file_size += len(content)
                if file_size > self.max_file_size:
                    await out_file.close()
                    os.remove(file_path)
                    raise ValueError(f"文件大小超过限制: {self.max_file_size} bytes")
                await out_file.write(content)
        
        # 检查总存储空间
        if current_usage + file_size > self.max_total_size_per_user:
            os.remove(file_path)
            raise ValueError(f"用户存储空间不足，已使用 {current_usage} bytes，限制 {self.max_total_size_per_user} bytes")
        
        # 生成文件信息
        file_info = {
            "id": file_id,
            "original_name": file.filename,
            "size": file_size,
            "type": self.get_file_type(file.filename),
            "extension": self.get_file_extension(file.filename),
            "source_type": "local",  # 标记为本地上传文件
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": FileStatus.ACTIVE,
            "converted": False,
            "has_markdown": False,
            "has_chunks": False
        }
        
        # 添加额外元数据
        if metadata:
            file_info.update(metadata)
        
        # 保存元数据
        async with aiofiles.open(meta_path, 'w') as meta_file:
            await meta_file.write(json.dumps(file_info, ensure_ascii=False))
        
        return file_info
    
    # 添加新方法用于远程URL资源
    async def create_remote_file_record(
        self,
        user_id: str,
        url: str,
        filename: str,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """为远程URL创建文件记录"""
        # 生成文件ID
        file_id = self.generate_file_id(filename)
        meta_path = self.get_metadata_path(user_id, file_id)
        
        # 生成文件信息
        file_info = {
            "id": file_id,
            "original_name": filename,
            "size": 0,  # 未知
            "type": self.get_file_type(filename),
            "extension": self.get_file_extension(filename),
            "source_type": "remote",  # 标记为远程URL
            "source_url": url,  # 记录源URL
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": FileStatus.ACTIVE,
            "converted": False,
            "has_markdown": False,
            "has_chunks": False
        }
        
        # 添加额外元数据
        if metadata:
            file_info.update(metadata)
        
        # 保存元数据
        async with aiofiles.open(meta_path, 'w') as meta_file:
            await meta_file.write(json.dumps(file_info, ensure_ascii=False))
        
        return file_info
    
    # 修改保存Markdown方法
    async def save_markdown_file(
        self, 
        user_id: str, 
        file_id: str, 
        markdown_content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """保存Markdown文件"""
        try:
            # 获取markdown文件路径
            md_file_path = self.get_md_file_path(user_id, file_id)
            os.makedirs(md_file_path.parent, exist_ok=True)
            
            # 保存markdown文件
            async with aiofiles.open(md_file_path, 'w', encoding='utf-8') as f:
                await f.write(markdown_content)
            
            # 更新元数据 - 核心状态字段放在顶层
            file_updates = {
                "has_markdown": True,
                "converted": True,
                "conversion_time": time.time()
            }
            
            # 添加额外元数据，也放在顶层保持一致性
            if metadata:
                file_updates.update(metadata)
                
            # 更新文件元数据
            await self.update_metadata(user_id, file_id, file_updates)
            
            return await self.get_file_meta(user_id, file_id)
        except Exception as e:
            logger.error(f"保存Markdown文件失败: {str(e)}")
            raise
    
    # 修改保存切片方法
    async def save_chunks(self, user_id: str, file_id: str, chunks: List[Dict[str, Any]]) -> bool:
        """保存文档切片，使用连续编号"""
        try:
            # 创建目录
            chunks_dir = self.get_chunks_dir_path(user_id, file_id)
            os.makedirs(chunks_dir, exist_ok=True)
            
            # 保存每个切片，确保连续编号
            chunks_meta = []
            for i, chunk in enumerate(chunks):
                # 使用连续的数字编号
                chunk_index = i
                
                # 构建文件路径，使用固定位数便于排序
                chunk_filename = f"chunk_{chunk_index:06d}.txt"
                chunk_path = chunks_dir / chunk_filename
                
                # 获取内容
                content = chunk.get("text", None) or chunk.get("content", None)
                if content is None:
                    logger.error(f"切片内容缺失: {chunk}")
                    continue
                    
                # 保存内容
                async with aiofiles.open(chunk_path, 'w', encoding='utf-8') as f:
                    await f.write(content)
                
                # 记录切片元数据，包括前后切片索引信息
                chunk_metadata = {
                    "index": chunk_index,
                    "path": str(chunk_path),
                    "prev_index": chunk_index - 1 if chunk_index > 0 else None,
                    "next_index": chunk_index + 1 if chunk_index < len(chunks) - 1 else None,
                    "filename": chunk_filename
                }
                
                # 添加原始元数据
                if "metadata" in chunk:
                    chunk_metadata.update(chunk["metadata"])
                    
                chunks_meta.append(chunk_metadata)
            
            # 更新文件元数据
            await self.update_metadata(user_id, file_id, {
                "has_chunks": True, 
                "chunks_count": len(chunks), 
                "chunking_time": time.time(),
                "chunks": chunks_meta  # 存储完整的切片元数据
            })
            
            return True
        except Exception as e:
            logger.error(f"保存切片失败: {str(e)}")
            return False
    
    # 修改获取Markdown内容的方法
    async def get_markdown_content(self, user_id: str, file_id: str) -> str:
        """获取Markdown内容"""
        # 获取文件元数据
        file_info = await self.get_file_meta(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise FileNotFoundError(f"文件不存在: {file_id}")
        
        if not file_info.get("has_markdown", False):
            raise FileNotFoundError(f"该文件没有Markdown内容: {file_id}")
        
        # 使用与save_markdown_file一致的路径
        md_file_path = self.get_md_file_path(user_id, file_id)
        
        # 文件存在性检查
        if not md_file_path.exists():
            raise FileNotFoundError(f"Markdown文件不存在: {md_file_path}")
        
        # 读取Markdown文件内容
        try:
            async with aiofiles.open(md_file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        except Exception as e:
            logger.error(f"读取Markdown内容失败: {md_file_path}, 错误: {e}")
            raise FileNotFoundError(f"无法读取Markdown内容: {str(e)}")
    
    # 修改获取切片内容的迭代器
    async def iter_chunks_content(
        self, 
        user_id: str,
        file_id: str = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """生成文档切片内容"""
        if file_id:
            # 指定文件的切片
            file_info = await self.get_file_meta(user_id, file_id)
            if not file_info or not file_info.get("has_chunks", False):
                return
            
            # 获取切片目录
            chunks_dir = self.get_chunks_dir_path(user_id, file_id)
            
            # 读取切片
            for i, chunk_info in enumerate(file_info.get("chunks", [])):
                chunk_path = Path(chunk_info["path"])
                try:
                    async with aiofiles.open(chunk_path, 'r', encoding='utf-8') as f:
                        content = await f.read()
                        
                        yield {
                            "file_id": file_id,
                            "chunk_index": i,
                            "content": content,
                            "metadata": {
                                "user_id": user_id,
                                "file_id": file_id,
                                "original_name": file_info.get("original_name", ""),
                                "source_type": file_info.get("source_type", "local"),
                                "source_url": file_info.get("source_url", "")
                            }
                        }
                except Exception as e:
                    logger.error(f"读取切片内容失败: {chunk_path}, 错误: {e}")
        else:
            # 所有文件的切片
            all_files = await self.list_files(user_id)
            for file_info in all_files:
                if file_info.get("has_chunks", False):
                    async for chunk in self.iter_chunks_content(user_id, file_info["id"]):
                        yield chunk
    
    # 计算用户存储使用量的方法需要修改
    async def calculate_user_storage_usage(self, user_id: str) -> int:
        """计算用户已使用的存储空间"""
        total_size = 0
        
        # 原始文件目录
        raw_dir = self.get_user_raw_dir(user_id)
        for file_path in raw_dir.glob("*"):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        
        # Markdown文件目录
        md_dir = self.get_user_md_dir(user_id)
        for file_path in md_dir.glob("*"):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        
        # 切片目录
        chunks_dir = self.get_user_chunks_dir(user_id)
        for dir_path in chunks_dir.glob("*"):
            if dir_path.is_dir():
                for file_path in dir_path.glob("*"):
                    if file_path.is_file():
                        total_size += file_path.stat().st_size
        
        return total_size
    
    # 删除文件的方法需要修改
    async def delete_file(self, user_id: str, file_id: str) -> bool:
        """删除文件及其所有关联数据"""
        file_info = await self.get_file_meta(user_id, file_id)
        if not file_info:
            logger.warning(f"尝试删除不存在的文件: {file_id}")
            return False
        
        success = True
        
        # 删除所有可能存在的文件，不进行条件判断
        # 1. 删除原始文件
        raw_file_path = self.get_raw_file_path(user_id, file_id)
        logger.info(f"删除原始文件: {raw_file_path}, 存在: {raw_file_path.exists()}")
        if raw_file_path.exists():
            try:
                os.remove(raw_file_path)
            except Exception as e:
                logger.error(f"删除原始文件失败: {raw_file_path}, 错误: {e}")
                success = False
        
        # 2. 删除Markdown文件
        md_file_path = self.get_md_file_path(user_id, file_id)
        logger.info(f"删除Markdown文件: {md_file_path}, 存在: {md_file_path.exists()}")
        if md_file_path.exists():
            try:
                os.remove(md_file_path)
            except Exception as e:
                logger.error(f"删除Markdown文件失败: {md_file_path}, 错误: {e}")
                success = False
        
        # 3. 删除切片目录及内容
        chunks_dir = self.get_chunks_dir_path(user_id, file_id)
        logger.info(f"删除切片目录: {chunks_dir}, 存在: {chunks_dir.exists()}")
        if chunks_dir.exists():
            try:
                shutil.rmtree(chunks_dir)
            except Exception as e:
                logger.error(f"删除切片目录失败: {chunks_dir}, 错误: {e}")
                success = False
        
        # 4. 最后才删除元数据，保证即使前面步骤失败也能重试
        meta_path = self.get_metadata_path(user_id, file_id)
        logger.info(f"删除元数据文件: {meta_path}, 存在: {meta_path.exists()}")
        if meta_path.exists():
            try:
                os.remove(meta_path)
            except Exception as e:
                logger.error(f"删除元数据失败: {meta_path}, 错误: {e}")
                success = False
        
        return success

    async def list_files(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户所有文件"""
        user_meta_dir = self.get_user_meta_dir(user_id)
        files = []
        
        # 查找所有元数据文件
        for meta_path in user_meta_dir.glob("*.json"):
            try:
                async with aiofiles.open(meta_path, 'r') as meta_file:
                    meta_content = await meta_file.read()
                    file_info = json.loads(meta_content)
                    
                    # 只返回活跃状态的文件
                    if file_info.get("status") == FileStatus.ACTIVE:
                        files.append(file_info)
                        
            except Exception as e:
                logger.error(f"读取文件元数据失败: {meta_path}, 错误: {e}")
        
        # 按创建时间降序排序
        files.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return files

    def is_valid_file_type(self, file_name: str) -> bool:
        """检查文件类型是否有效"""
        _, ext = os.path.splitext(file_name)
        return ext.lower() in self.allowed_extensions

    def get_file_extension(self, file_name: str) -> str:
        """获取文件扩展名"""
        _, ext = os.path.splitext(file_name)
        return ext.lower()

    def get_file_type(self, file_name: str) -> str:
        """获取文件类型"""
        _, ext = os.path.splitext(file_name)
        return ext.lower()[1:]  # 去掉点号

    def get_file_mimetype(self, file_name: str) -> str:
        """获取文件MIME类型"""
        _, ext = os.path.splitext(file_name)
        mime_type = self._mime_types.get(ext.lower())
        if not mime_type:
            # 使用系统mimetypes库猜测
            mime_type = mimetypes.guess_type(file_name)[0]
        return mime_type or 'application/octet-stream'

    async def get_file_meta(self, user_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        """获取文件元数据
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件元数据，不存在则返回None
        """
        meta_path = self.get_metadata_path(user_id, file_id)
        
        if not meta_path.exists():
            return None
        
        # 读取元数据
        try:
            async with aiofiles.open(meta_path, 'r') as meta_file:
                meta_content = await meta_file.read()
                return json.loads(meta_content)
        except Exception as e:
            logger.error(f"读取文件元数据失败: {meta_path}, 错误: {e}")
            return None

    async def update_metadata(self, user_id: str, file_id: str, metadata: Dict[str, Any]) -> bool:
        """更新文件元数据"""
        try:
            # 获取元数据文件路径
            meta_path = self.get_metadata_path(user_id, file_id)
            
            # 读取现有元数据
            meta = {}
            if os.path.exists(meta_path):
                async with aiofiles.open(meta_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content:
                        meta = json.loads(content)
            
            # 直接更新顶层元数据
            meta.update(metadata)  # 扁平化结构
            
            # 写入更新后的元数据
            async with aiofiles.open(meta_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(meta, ensure_ascii=False))
            
            return True
        except Exception as e:
            logger.error(f"更新元数据失败: {str(e)}")
            return False

    async def get_adjacent_chunks(self, user_id: str, file_id: str, chunk_index: int, 
                                  window: int = 1) -> Dict[str, Any]:
        """获取指定切片的相邻切片
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            chunk_index: 当前切片索引
            window: 获取前后多少个切片
            
        Returns:
            包含前后切片内容的字典
        """
        try:
            # 获取文件元数据
            file_info = await self.get_file_meta(user_id, file_id)
            if not file_info or not file_info.get("has_chunks", False):
                return {"error": "文件没有切片"}
            
            chunks_meta = file_info.get("chunks", [])
            if not chunks_meta:
                return {"error": "切片元数据不存在"}
            
            # 查找当前切片
            current_chunk = None
            for chunk in chunks_meta:
                if chunk["index"] == chunk_index:
                    current_chunk = chunk
                    break
                
            if not current_chunk:
                return {"error": f"切片索引不存在: {chunk_index}"}
            
            # 获取相邻切片索引
            prev_indices = []
            next_indices = []
            
            for i in range(1, window + 1):
                prev_idx = chunk_index - i
                if prev_idx >= 0:
                    prev_indices.append(prev_idx)
                    
                next_idx = chunk_index + i
                if next_idx < len(chunks_meta):
                    next_indices.append(next_idx)
                    
            # 读取切片内容
            result = {
                "current": {"index": chunk_index, "content": ""},
                "previous": [],
                "next": []
            }
            
            # 读取当前切片
            current_path = Path(current_chunk["path"])
            if current_path.exists():
                async with aiofiles.open(current_path, 'r', encoding='utf-8') as f:
                    result["current"]["content"] = await f.read()
            
            # 读取前向切片
            for idx in prev_indices:
                for chunk in chunks_meta:
                    if chunk["index"] == idx:
                        chunk_path = Path(chunk["path"])
                        if chunk_path.exists():
                            async with aiofiles.open(chunk_path, 'r', encoding='utf-8') as f:
                                result["previous"].append({
                                    "index": idx,
                                    "content": await f.read()
                                })
                        break
            
            # 读取后向切片
            for idx in next_indices:
                for chunk in chunks_meta:
                    if chunk["index"] == idx:
                        chunk_path = Path(chunk["path"])
                        if chunk_path.exists():
                            async with aiofiles.open(chunk_path, 'r', encoding='utf-8') as f:
                                result["next"].append({
                                    "index": idx,
                                    "content": await f.read()
                                })
                        break
            
            # 按索引排序
            result["previous"].sort(key=lambda x: x["index"], reverse=True)
            result["next"].sort(key=lambda x: x["index"])
            
            return result
        except Exception as e:
            logger.error(f"获取相邻切片失败: {str(e)}")
            return {"error": str(e)}

