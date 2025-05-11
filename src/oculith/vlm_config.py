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
    ResponseFormat,  # 导入枚举
    VlmPipelineOptions,
)
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

logger = logging.getLogger(__name__)

def read_env_configs() -> Dict[str, Any]:
    """从环境变量读取VLM配置参数"""
    # 基础配置
    config = {
        # 默认提供商为空，必须显式指定
        "provider": os.environ.get("VLM_PROVIDER", "").lower(),
        # 核心配置，不提供默认值
        "api_url": os.environ.get("VLM_API_URL", ""),
        "api_key": os.environ.get("VLM_API_KEY", ""),
        "model_name": os.environ.get("VLM_MODEL_NAME", ""),
        "prompt_template": os.environ.get("VLM_PROMPT_TEMPLATE", ""),
        # 非关键配置，提供默认值
        "timeout": int(os.environ.get("VLM_TIMEOUT", "90")),
    }
    
    # OpenAI兼容接口特定配置
    config.update({
        # 认证方式: bearer, api_key, custom, none
        "auth_type": os.environ.get("VLM_AUTH_TYPE", "bearer").lower(),
        # 认证头名称，默认为Authorization
        "auth_header": os.environ.get("VLM_AUTH_HEADER", "Authorization"),
        # 认证值前缀，默认为Bearer
        "auth_prefix": os.environ.get("VLM_AUTH_PREFIX", "Bearer"),
        # 完整认证值，如果提供则优先使用
        "auth_value": os.environ.get("VLM_AUTH_VALUE", ""),
    })
    
    # 读取响应格式配置
    config["response_format"] = os.environ.get("VLM_RESPONSE_FORMAT", "")
    
    # 解析额外参数
    additional_params_str = os.environ.get("VLM_ADDITIONAL_PARAMS", "{}")
    try:
        config["additional_params"] = json.loads(additional_params_str)
    except json.JSONDecodeError:
        logger.warning(f"无法解析VLM_ADDITIONAL_PARAMS: {additional_params_str}，使用空字典")
        config["additional_params"] = {}
    
    # 解析完整的请求头
    headers_str = os.environ.get("VLM_HEADERS", "{}")
    try:
        config["headers"] = json.loads(headers_str)
    except json.JSONDecodeError:
        logger.warning(f"无法解析VLM_HEADERS: {headers_str}，使用空字典")
        config["headers"] = {}
    
    return config

def configure_openai(config: Dict[str, Any]) -> ApiVlmOptions:
    """配置OpenAI及兼容接口的视觉模型"""
    # OpenAI默认配置
    DEFAULT_OPENAI = {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model_name": "gpt-4o",
        "prompt_template": "Extract and transcribe all text content from this image, preserving the layout as much as possible. Format the output in markdown."
    }
    
    # 通义千问的默认配置
    DEFAULT_DASHSCOPE = {
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model_name": "qwen-vl-plus",
        "prompt_template": "提取并转录图像中的所有文本内容，尽可能保留原始布局，使用markdown格式输出。"
    }
    
    # 判断是否为通义千问
    is_dashscope = "dashscope" in config.get("api_url", "").lower()
    
    # 选择默认配置
    DEFAULT_CONFIG = DEFAULT_DASHSCOPE if is_dashscope else DEFAULT_OPENAI
    
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
    prompt: str = "提取并转录图像中的所有文本内容，尽可能保留原始布局，使用markdown格式输出。"
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

def get_vlm_pipeline_options(
    provider: str = None,
    model: str = None,
    prompt: str = None,
    api_key: str = None
) -> VlmPipelineOptions:
    """获取VLM管道选项
    
    参数:
        provider: 模型提供商 (dashscope, ollama, openai)
        model: 模型名称
        prompt: 提示词
        api_key: API密钥
    """
    # 从环境变量获取默认值
    provider = provider or os.environ.get("VLM_PROVIDER", "ollama").lower()
    api_key = api_key or os.environ.get("VLM_API_KEY", "")
    model = model or os.environ.get("VLM_MODEL_NAME", "")
    prompt = prompt or os.environ.get("VLM_PROMPT", "")
    
    pipeline_options = VlmPipelineOptions(enable_remote_services=True)
    
    if provider == "dashscope":
        pipeline_options.vlm_options = dashscope_vlm_options(api_key, model, prompt)
    elif provider == "openai":
        pipeline_options.vlm_options = openai_vlm_options(api_key, model, prompt)
    elif provider == "ollama":
        pipeline_options.vlm_options = ollama_vlm_options(model, prompt)
    else:
        raise ValueError(f"不支持的视觉模型提供商: {provider}")
    
    return pipeline_options
