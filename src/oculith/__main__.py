#!/usr/bin/env python
"""
文档处理服务的主入口点
"""
import sys
import logging
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

from .__version__ import __version__

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("oculith")


def main():
    """启动Oculith文档处理服务"""
    # 使用原生argparse替代click，更简单直接
    parser = argparse.ArgumentParser(description="Oculith文档处理服务")
    parser.add_argument('--host', default="0.0.0.0", help="监听地址")
    parser.add_argument('--port', type=int, default=31573, help="监听端口")
    parser.add_argument('--prefix', default="", help="API前缀")
    parser.add_argument('--output-dir', default=None, help="结果输出目录")
    parser.add_argument('--allowed-formats', help="允许处理的文档格式，用逗号分隔")
    
    args = parser.parse_args()
    
    try:
        import uvicorn
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        
        # 创建FastAPI应用
        app = FastAPI(
            title="Oculith 文档处理服务",
            description="提供文件上传、文档转换、检索等功能",
            version=__version__
        )
        
        # 处理CORS配置
        cors_origins_env = os.environ.get("DOCLING_CORS_ORIGINS", "*")
        if cors_origins_env == "*":
            cors_origins = ["*"]
        else:
            cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
            if not cors_origins:
                cors_origins = ["*"]
        
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # 处理格式选项
        formatted_formats = None
        if args.allowed_formats:
            formatted_formats = [fmt.strip() for fmt in args.allowed_formats.split(",") if fmt.strip()]
            if formatted_formats:
                logger.info(f"配置允许处理的格式: {', '.join(formatted_formats)}")
            
        # 处理输出目录
        output_dir = None
        if args.output_dir:
            output_dir = os.path.abspath(args.output_dir)
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"使用输出目录: {output_dir}")
        
        # 挂载API路由 - ChromaDB应该在endpoints模块内部初始化，而不是这里
        from .api.endpoints import mount_docling_service
        mount_docling_service(
            app=app,
            output_dir=output_dir,
            allowed_formats=formatted_formats,
            prefix=args.prefix
        )
        
        # 启动服务
        logger.info(f"启动服务于 {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        
    except Exception as e:
        logger.error(f"启动服务失败: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
