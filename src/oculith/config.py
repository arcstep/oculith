import os
from pathlib import Path

# 默认输出路径配置
DEFAULT_OUTPUT_DIR = os.environ.get("DOCLING_OUTPUT_DIR", "./docling/markdown")

# 确保输出目录存在
def ensure_output_dir(path=None):
    output_dir = Path(path or DEFAULT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

# 根据document_id创建层次化目录
def get_document_path(document_id):
    if not document_id:
        return Path(DEFAULT_OUTPUT_DIR)
    
    # 如果包含点号，按层次创建目录
    if "." in document_id:
        parts = document_id.split(".")
        path = Path(DEFAULT_OUTPUT_DIR).joinpath(*parts[:-1])
        path.mkdir(parents=True, exist_ok=True)
        return path / parts[-1]
    
    return Path(DEFAULT_OUTPUT_DIR) / document_id
