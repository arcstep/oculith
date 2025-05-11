import pandas as pd
from pathlib import Path
from docling.utils.utils import create_hash
from docling.utils.export import generate_multimodal_pages
from docling.datamodel.base_models import InputFormat
import io

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
    
    # 对PDF和图像使用多模态处理
    if file_format in [InputFormat.PDF, InputFormat.IMAGE]:
        try:
            # 使用多模态页面生成
            for text, md, dt, cells, segs, page in generate_multimodal_pages(res):
                page_hash = create_hash(f"{doc_hash}:{page.page_no-1}")
                dpi = page._default_image_scale * 72
                
                # 确保图像数据存在
                image_data = None
                if hasattr(page, 'image') and page.image is not None:
                    try:
                        # 检查获取图像的正确方法
                        image_bytes = None
                        # 尝试保存为PNG格式
                        with io.BytesIO() as buffer:
                            if hasattr(page.image, 'save'):
                                page.image.save(buffer, format="PNG")
                                image_bytes = buffer.getvalue()
                            elif hasattr(page.image, 'pil_image'):
                                page.image.pil_image.save(buffer, format="PNG")
                                image_bytes = buffer.getvalue()
                            else:
                                # 回退到原始方法
                                image_bytes = page.image.tobytes() if hasattr(page.image, 'tobytes') else None
                        
                        if image_bytes:
                            image_data = {
                                "width": getattr(page.image, 'width', 0),
                                "height": getattr(page.image, 'height', 0),
                                "bytes": image_bytes,
                            }
                    except Exception as e:
                        logger.warning(f"图像转换失败: {e}")
                        image_data = None
                
                rows.append({
                    "document": doc_name,
                    "hash": doc_hash,
                    "page_hash": page_hash,
                    "image": image_data,
                    "cells": cells,
                    "contents": text,
                    "contents_md": md,
                    "contents_dt": dt,
                    "segments": segs,
                    "extra": {
                        "page_num": page.page_no + 1,
                        "width_pts": page.size.width if page.size else None,
                        "height_pts": page.size.height if page.size else None,
                        "dpi": dpi,
                        "format": str(file_format),
                    }
                })
            
            logger.info(f"成功提取{len(rows)}页多模态内容")
            
        except Exception as e:
            logger.warning(f"多模态处理失败: {e}，降级为纯文本处理")
            rows = [] # 确保降级处理
    
    # 如果没有行数据（非PDF/图像或处理失败），使用基本文档处理
    if not rows:
        # 从文档中提取整体Markdown和纯文本
        md_full = res.document.export_to_markdown()
        txt_full = ""
        
        # 尝试提取纯文本（如果支持）
        if hasattr(res.document, "export_to_text"):
            txt_full = res.document.export_to_text()
        
        # 检查文档是否包含页面图像（极少数情况）
        image_data = None
        if (hasattr(res.document, 'pages') and 
            len(res.document.pages) > 0 and 
            hasattr(res.document.pages[1], 'image') and 
            res.document.pages[1].image is not None):
            
            try:
                page = res.document.pages[1]
                # 尝试多种方式获取图像
                image_bytes = None
                with io.BytesIO() as buffer:
                    if hasattr(page.image, 'save'):
                        page.image.save(buffer, format="PNG")
                        image_bytes = buffer.getvalue()
                    elif hasattr(page.image, 'to_bytes') or hasattr(page.image, 'tobytes'):
                        image_bytes = (page.image.to_bytes() if hasattr(page.image, 'to_bytes') 
                                      else page.image.tobytes())
                
                if image_bytes:
                    image_data = {
                        "width": getattr(page.image, 'width', 0),
                        "height": getattr(page.image, 'height', 0),
                        "bytes": image_bytes,
                    }
            except Exception as e:
                logger.warning(f"无法处理图像: {e}")
        
        rows.append({
            "document": doc_name,
            "hash": doc_hash,
            "contents_md": md_full,
            "contents": txt_full,
            "image": image_data,
            "extra": {
                "page_num": 1,
                "format": str(file_format),
                "is_multimodal": False
            }
        })
        
        logger.info(f"处理基本文档: {doc_name} (格式: {file_format})")

    # 保存为Parquet
    df = pd.DataFrame(rows)
    df.to_parquet(output_path)
    logger.info(f"文档数据已保存: {output_path}，共{len(rows)}行")