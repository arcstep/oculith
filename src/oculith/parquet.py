
import pandas as pd
from pathlib import Path
from docling.utils.utils import create_hash
from docling.utils.export import generate_multimodal_pages

import logging

logger = logging.getLogger(__name__)

def save_to_parquet(res, output_path: str) -> None:
    """将多模态页面数据保存为parquet格式"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    doc_hash = res.input.document_hash
    doc_name = Path(res.input.file).name
    
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

    df = pd.DataFrame(rows)
    df.to_parquet(output_path)
    logger.info(f"多模态数据已保存: {output_path}")