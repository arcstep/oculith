#!/usr/bin/env python
"""
文档处理服务的主入口点
"""
import sys
import logging
import click
import os

from typing import Optional, List
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("illufly_docling")

@click.group()
def cli():
    """Illufly Docling 命令行工具"""
    pass

@cli.command()
@click.option("--host", default="0.0.0.0", help="服务监听地址")
@click.option("--port", default=31573, help="服务监听端口")
@click.option("--prefix", default="", help="API前缀")
@click.option("--allowed-formats", multiple=True, help="允许处理的文档格式，多个格式用逗号分隔")
@click.option("--output-dir", default=None, help="结果输出目录")
def serve(host, port, prefix, allowed_formats, output_dir):
    """启动简化版文档处理服务 (直接FastAPI接口)"""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    
    # 创建FastAPI应用
    app = FastAPI(
        title="Illufly Docling服务",
        description="高质量文档处理服务",
        version="0.1.0"
    )
    
    # 从环境变量读取CORS配置
    cors_origins_env = os.environ.get("DOCLING_CORS_ORIGINS", "*")
    if cors_origins_env == "*":
        cors_origins = ["*"]
    else:
        # 将逗号分隔的字符串转换为列表
        cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
        if not cors_origins:  # 如果为空，添加一个默认值
            cors_origins = ["http://localhost:3000"]
        logger.info(f"使用自定义CORS源: {cors_origins}")
    
    # 添加CORS支持
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 格式化允许的格式列表
    formatted_allowed_formats = []
    for fmt_group in allowed_formats:
        for fmt in fmt_group.split(","):
            if fmt.strip():
                formatted_allowed_formats.append(fmt.strip())
    
    if formatted_allowed_formats:
        logger.info(f"配置允许处理的格式: {', '.join(formatted_allowed_formats)}")
    else:
        logger.info("未限制处理格式，将支持所有可用格式")
    
    # 处理output_dir参数
    output_dir_param = output_dir
    if output_dir:
        output_dir_param = os.path.abspath(output_dir)
        os.makedirs(output_dir_param, exist_ok=True)
        logger.info(f"使用指定的输出目录: {output_dir_param}")
    
    # 挂载文档处理服务到FastAPI应用
    from .api.endpoints import mount_docling_service
    logger.info(f"启动文档处理服务")
    mount_docling_service(
        app=app,
        output_dir=output_dir_param,
        allowed_formats=formatted_allowed_formats if formatted_allowed_formats else None,
        prefix=prefix
    )
    
    # 启动uvicorn服务
    logger.info(f"启动FastAPI服务 - 监听: {host}:{port}")
    uvicorn.run(app, host=host, port=port)

# 默认没有子命令时，使用serve命令
def main():
    if len(sys.argv) == 1:
        # 如果没有参数，默认使用serve模式
        sys.argv.append("serve")
    cli()

if __name__ == "__main__":
    main()
