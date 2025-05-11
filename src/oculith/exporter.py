# src/oculith/exporter.py
import base64
import logging
import asyncio
from pathlib import Path
import pandas as pd
from typing import Literal, List, Dict, Any, Optional

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
        # 检查内容字段
        page_content = ""
        
        # 优先使用contents_md，然后是contents
        if "contents_md" in row and pd.notna(row["contents_md"]):
            page_content = row["contents_md"]
        elif "contents" in row and pd.notna(row["contents"]):
            page_content = row["contents"]
        
        # 如果内容为空，尝试进一步检查
        if not page_content and "cells" in row and pd.notna(row["cells"]).any():
            try:
                # 从单元格构建内容
                cells_text = [cell.get("text", "") for cell in row["cells"] if pd.notna(cell)]
                page_content = "\n".join(cells_text)
            except Exception as e:
                logger.warning(f"无法从单元格构建内容: {e}")
        
        # 如果需要嵌入图像
        if markdown_type == "embedded" and "image" in row:
            try:
                # 检查图像数据是否存在且不是None
                has_image = (
                    pd.notna(row["image"]) and 
                    isinstance(row["image"], dict) and
                    "bytes" in row["image"] and 
                    row["image"]["bytes"] is not None
                )
                
                if has_image:
                    # 提取图像数据并转换为base64
                    image_bytes = row["image"]["bytes"]
                    logger.debug(f"图像数据长度: {len(image_bytes)} 字节, 前10个字节: {image_bytes[:10]}")
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                    logger.debug(f"Base64长度: {len(image_b64)}, 前20个字符: {image_b64[:20]}")
                    
                    # 添加图像到markdown
                    page_content += f"\n\n![页面 {row.get('extra.page_num', '')}](data:image/png;base64,{image_b64})\n\n"
            except Exception as e:
                logger.warning(f"无法嵌入图像: {e}")
        
        markdown_content.append(page_content)
    
    # 合并所有页面内容
    full_markdown = "\n\n".join([content for content in markdown_content if content])
    
    if not full_markdown.strip():
        logger.warning(f"从 {parquet_path} 提取的内容为空")
    
    return full_markdown

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