import pandas as pd
from pathlib import Path
from docling.utils.utils import create_hash
from docling.utils.export import generate_multimodal_pages
from docling.datamodel.base_models import InputFormat

import logging

logger = logging.getLogger(__name__)

def save_to_parquet(res, output_path: str) -> None:
    """将文档数据保存为parquet格式"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    doc_hash = res.input.document_hash
    doc_name = Path(res.input.file).name
    
    # 检测文件格式
    file_format = getattr(res.input, "format", None)
    
    # 仅对PDF使用多模态处理
    if file_format == InputFormat.PDF:
        try:
            # 使用多模态页面生成（仅适用于PDF）
            for text, md, dt, cells, segs, page in generate_multimodal_pages(res):
                page_hash = create_hash(f"{doc_hash}:{page.page_no-1}")
                dpi = page._default_image_scale * 72
                
                rows.append({
                    "document": doc_name,
                    "hash": doc_hash,
                    "page_hash": page_hash,
                    "image": {
                        "width": page.image.width,
                        "height": page.image.height,
                        "bytes": page.image.tobytes(),
                    },
                    "cells": cells,
                    "contents": text,
                    "contents_md": md,
                    "contents_dt": dt,
                    "segments": segs,
                    "extra": {
                        "page_num": page.page_no + 1,
                        "width_pts": page.size.width,
                        "height_pts": page.size.height,
                        "dpi": dpi,
                    }
                })
        except Exception as e:
            logger.warning(f"多模态处理失败: {e}，降级为纯文本处理")
            rows = [] # 确保降级处理
    
    # 如果没有行数据（非PDF或处理失败），使用全文档处理
    if not rows:
        # 从文档中提取整体Markdown和纯文本
        md_full = res.document.export_to_markdown()
        txt_full = getattr(res.document, "export_to_text", lambda: "")()
        
        # 如果是图片，尝试提取OCR文本结果
        if file_format == InputFormat.IMAGE:
            logger.info(f"处理图片文件: {doc_name}")
            
        rows.append({
            "document": doc_name,
            "hash": doc_hash,
            "contents_md": md_full,
            "contents": txt_full,
            "image": None,  # 不保存图片数据
            "extra": {"page_num": 1}  # 所有非PDF视为单页
        })

    # 保存为Parquet
    df = pd.DataFrame(rows)
    df.to_parquet(output_path)
    logger.info(f"文档数据已保存: {output_path}")