# src/oculith/exporter.py
import base64
import logging
import asyncio
from pathlib import Path
import pandas as pd
from typing import Literal, List, Dict, Any, Optional

from .chunker import get_chunker

# 日志
logger = logging.getLogger(__name__)

def export_markdown(
    parquet_path: str,
    markdown_type: Literal["reference", "embedded"] = "reference"
) -> str:
    """
    从parquet文件导出markdown内容
    
    参数:
        parquet_path: parquet文件路径
        markdown_type: markdown类型 (reference/embedded)
    
    返回:
        markdown内容字符串
    """
    # 读取parquet文件
    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)
    
    # 提取markdown内容
    markdown_content = []
    
    # 对DataFrame进行排序处理，确保页面顺序正确
    if "extra.page_num" in df.columns:
        df = df.sort_values("extra.page_num")
    
    # 处理每一行
    for _, row in df.iterrows():
        page_content = row.get("contents_md", "")
        
        # 如果需要嵌入图像
        if markdown_type == "embedded" and "image.bytes" in row and row["image.bytes"]:
            try:
                # 提取图像数据并转换为base64
                image_bytes = row["image.bytes"]
                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                
                # 添加图像到markdown
                page_content += f"\n\n![页面 {row.get('extra.page_num', '')}](data:image/png;base64,{image_b64})\n\n"
            except Exception as e:
                logger.warning(f"无法嵌入图像: {e}")
        
        markdown_content.append(page_content)
    
    # 合并所有页面内容
    full_markdown = "\n\n".join(markdown_content)
    
    return full_markdown


def chunk_markdown(
    parquet_path: str, 
    max_chunk_size: int = 1000,
    overlap: int = 100,
    metadata: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    将parquet文件中的markdown内容切片
    
    参数:
        parquet_path: parquet文件路径
        max_chunk_size: 每个切片的最大token数
        overlap: 切片重叠token数
        metadata: 额外的元数据，将被传递给chunker
    
    返回:
        切片列表
    """
    # 获取纯文本版本的Markdown
    markdown_content = export_markdown(parquet_path, markdown_type="reference")
    
    # 创建Markdown切片器
    chunker = get_chunker(
        doc_type="markdown", 
        max_chunk_size=max_chunk_size, 
        overlap=overlap
    )
    
    # 由于chunker.chunk_document是异步方法，需要在同步环境中调用
    try:
        # 设置基础元数据
        base_metadata = {
            "source": str(parquet_path),
            "document_type": "markdown"
        }
        
        # 合并用户提供的元数据
        if metadata:
            base_metadata.update(metadata)
            
        # 异步调用切片器
        loop = asyncio.get_event_loop()
        chunks = loop.run_until_complete(chunker.chunk_document(markdown_content, base_metadata))
        
        return chunks
    except RuntimeError:
        # 如果没有事件循环，创建一个新的
        chunks = asyncio.run(chunker.chunk_document(markdown_content, metadata or {}))
        return chunks


def get_markdown_content(
    parquet_path: str,
    markdown_type: Literal["reference", "embedded"] = "reference"
) -> str:
    """
    从parquet文件获取markdown内容字符串，不写入文件
    
    参数:
        parquet_path: parquet文件路径
        markdown_type: markdown类型 (reference/embedded)
    
    返回:
        markdown内容字符串
    """
    _, content = export_markdown(
        parquet_path,
        markdown_type=markdown_type,
        output_path=None,  # 临时路径
        return_content=True
    )
    return content