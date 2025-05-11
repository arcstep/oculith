"""
视觉语言模型(VLM)配置管理模块

此模块负责从环境变量读取VLM配置，并为不同模型提供商生成相应的配置选项。
支持的提供商包括OpenAI及其兼容API、Ollama和Google Gemini。
"""

import os
import json
import logging
from typing import Dict, Any, Optional

from docling.datamodel.pipeline_options import (
    ApiVlmOptions,
    HuggingFaceVlmOptions,
    ResponseFormat,  # 导入枚举
    VlmPipelineOptions,
    InferenceFramework,
)
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

logger = logging.getLogger(__name__)


def configure_openai(config: Dict[str, Any]) -> ApiVlmOptions:
    """配置OpenAI及兼容接口的视觉模型"""
    # OpenAI默认配置
    DEFAULT_CONFIG = {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model_name": "gpt-4o",
        "prompt_template": "Extract and transcribe all text content from this image, preserving the layout as much as possible. Format the output in markdown."
    }
        
    # 获取配置，优先使用环境变量，否则使用默认值
    api_url = config.get("api_url") or DEFAULT_CONFIG["api_url"]
    api_key = config.get("api_key")
    model_name = config.get("model_name") or DEFAULT_CONFIG["model_name"]
    prompt_template = config.get("prompt_template") or DEFAULT_CONFIG["prompt_template"]
    
    # 检查API密钥
    if not api_key and config.get("auth_type") != "none":
        raise ValueError(f"使用视觉模型需要设置环境变量VLM_API_KEY")
    
    # 构建请求头
    headers = dict(config.get("headers", {}))
    
    # 根据认证类型添加认证信息
    auth_type = config.get("auth_type", "bearer").lower()
    if auth_type == "bearer":
        auth_header = config.get("auth_header", "Authorization")
        auth_prefix = config.get("auth_prefix", "Bearer")
        auth_value = config.get("auth_value", f"{auth_prefix} {api_key}")
        headers[auth_header] = auth_value
    elif auth_type == "api_key":
        auth_header = config.get("auth_header", "api-key")
        headers[auth_header] = api_key
    elif auth_type == "custom":
        auth_header = config.get("auth_header", "Authorization")
        auth_value = config.get("auth_value")
        if auth_value:
            headers[auth_header] = auth_value
    
    # 构建请求参数
    params = {
        "model": model_name,
        **config.get("additional_params", {})
    }
        
    return ApiVlmOptions(
        url=api_url,
        params=params,
        headers=headers,
        prompt=prompt_template,
        timeout=config.get("timeout", 90),
        scale=1.0,  # 添加缺失的scale参数
        response_format=ResponseFormat.MARKDOWN  # 使用枚举而非字符串
    )

def configure_ollama(config: Dict[str, Any]) -> ApiVlmOptions:
    """配置Ollama本地视觉模型"""
    # Ollama默认配置
    DEFAULT_OLLAMA = {
        "api_url": "http://localhost:11434/v1/chat/completions",
        "model_name": "granite3.2-vision:2b",
        "prompt_template": "OCR the full page to markdown."
    }
    
    # 获取配置，优先使用环境变量，否则使用默认值
    api_url = config.get("api_url") or DEFAULT_OLLAMA["api_url"]
    model_name = config.get("model_name") or DEFAULT_OLLAMA["model_name"]
    prompt_template = config.get("prompt_template") or DEFAULT_OLLAMA["prompt_template"]
    
    return ApiVlmOptions(
        url=api_url,
        params={
            "model": model_name,
            **config.get("additional_params", {})
        },
        headers=config.get("headers", {}),
        prompt=prompt_template,
        timeout=config.get("timeout", 90),
        response_format=ResponseFormat.MARKDOWN
    )

def configure_gemini(config: Dict[str, Any]) -> ApiVlmOptions:
    """配置Google Gemini视觉模型"""
    # Google Gemini默认配置
    DEFAULT_GEMINI = {
        "api_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent",
        "model_name": "gemini-pro-vision",
        "prompt_template": "OCR and transcribe the contents of this document to markdown."
    }
    
    # 获取配置，优先使用环境变量，否则使用默认值
    api_url = config.get("api_url") or DEFAULT_GEMINI["api_url"]
    api_key = config.get("api_key")
    model_name = config.get("model_name") or DEFAULT_GEMINI["model_name"]
    prompt_template = config.get("prompt_template") or DEFAULT_GEMINI["prompt_template"]
    
    # 检查必要的配置
    if not api_key:
        raise ValueError("使用Gemini视觉模型需要设置环境变量VLM_API_KEY")
    
    # 为Gemini模型构建URL (包含API密钥)
    if "?" not in api_url:
        api_url = f"{api_url}?key={api_key}"
    
    return ApiVlmOptions(
        url=api_url,
        params={
            "model": model_name,
            **config.get("additional_params", {})
        },
        headers=config.get("headers", {}),
        prompt=prompt_template,
        timeout=config.get("timeout", 90),
        response_format=ResponseFormat.MARKDOWN
    )

def dashscope_vlm_options(
    api_key: str,
    model: str = "qwen-vl-plus",
    prompt: str = "提取并转录图像中的所有文本内容，尽可能保留原始布局，使用markdown格式输出。直接输出markdown内容，不要添加任何其他内容。"
) -> ApiVlmOptions:
    """配置通义千问视觉模型"""
    if not api_key:
        raise ValueError("使用通义千问需要提供API密钥")
    
    return ApiVlmOptions(
        url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        params=dict(model=model),
        headers={"Authorization": f"Bearer {api_key}"},
        prompt=prompt,
        timeout=90,
        scale=1.0,
        response_format=ResponseFormat.MARKDOWN,
    )

def openai_vlm_options(
    api_key: str,
    model: str = "gpt-4o",
    prompt: str = "Extract and transcribe all text content from this image, preserving the layout as much as possible."
) -> ApiVlmOptions:
    """配置OpenAI视觉模型"""
    if not api_key:
        raise ValueError("使用OpenAI需要提供API密钥")
    
    return ApiVlmOptions(
        url="https://api.openai.com/v1/chat/completions",
        params=dict(model=model),
        headers={"Authorization": f"Bearer {api_key}"},
        prompt=prompt,
        timeout=90,
        scale=1.0,
        response_format=ResponseFormat.MARKDOWN,
    )

def ollama_vlm_options(
    model: str = "granite3.2-vision:2b",
    prompt: str = "OCR the full page to markdown."
) -> ApiVlmOptions:
    """配置Ollama本地视觉模型"""
    return ApiVlmOptions(
        url="http://localhost:11434/v1/chat/completions",
        params=dict(model=model),
        prompt=prompt,
        timeout=90,
        scale=1.0,
        response_format=ResponseFormat.MARKDOWN,
    )

def huggingface_vlm_options(
    repo_id: str = "ibm-granite/granite-vision-3.1-2b-preview",
    prompt: str = "OCR this image.",
    inference_framework: str = "transformers"
) -> HuggingFaceVlmOptions:
    """配置HuggingFace本地模型"""
    if not repo_id:
        raise ValueError("使用HuggingFace需要提供模型ID")
    
    # 转换框架字符串为枚举值
    if inference_framework.lower() == "mlx":
        framework = InferenceFramework.MLX
    elif inference_framework.lower() == "openai":
        framework = InferenceFramework.OPENAI
    else:
        framework = InferenceFramework.TRANSFORMERS
    
    # 简化：直接使用MARKDOWN格式，移除不必要的条件判断
    return HuggingFaceVlmOptions(
        repo_id=repo_id,
        prompt=prompt,
        response_format=ResponseFormat.MARKDOWN,
        inference_framework=framework,
    )

def get_vlm_pipeline_options(
    provider: str = None,
    model: str = None,
    prompt: str = None,
    api_key: str = None
) -> VlmPipelineOptions:
    """获取VLM管道选项
    
    参数:
        provider: 模型提供商 (dashscope, ollama, openai, huggingface)
        model: 模型名称或仓库ID
        prompt: 提示词
        api_key: API密钥
    """
    # 从环境变量获取默认值，默认使用ollama
    provider = provider or os.environ.get("VLM_PROVIDER", "ollama").lower()
    api_key = api_key or os.environ.get("VLM_API_KEY", "")
    model = model or os.environ.get("VLM_MODEL_NAME", "")
    prompt = prompt or os.environ.get("VLM_PROMPT", "")
    
    pipeline_options = VlmPipelineOptions(enable_remote_services=True)
    
    if provider == "huggingface":
        # 从环境变量获取HuggingFace特定配置
        inference_framework = os.environ.get("VLM_INFERENCE_FRAMEWORK", "transformers")
        kwargs = {}
        if model:
            kwargs["repo_id"] = model
        if prompt:
            kwargs["prompt"] = prompt
        if inference_framework:
            kwargs["inference_framework"] = inference_framework
        pipeline_options.vlm_options = huggingface_vlm_options(**kwargs)
        # HuggingFace本地模型不需要远程服务
        pipeline_options.enable_remote_services = False
    else:
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        if prompt:
            kwargs["prompt"] = prompt

        if provider == "dashscope":
            pipeline_options.vlm_options = dashscope_vlm_options(**kwargs)
        elif provider == "openai":
            pipeline_options.vlm_options = openai_vlm_options(**kwargs)
        elif provider == "ollama":
            pipeline_options.vlm_options = ollama_vlm_options(**kwargs)
        else:
            raise ValueError(f"不支持的视觉模型提供商: {provider}")
    
    return pipeline_options
