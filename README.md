# Oculith 文档处理工具

## 简介

Oculith 是一个强大的文档处理工具，可以将多种格式的文档（如PDF、Word、HTML等）转换为Markdown等结构化格式。它既可以作为独立服务运行，也可以集成到你的应用中。

## 功能特点

- 支持多种文档格式（PDF、Word、HTML、图片等）
- 文档转换为Markdown、文本等格式
- 文档自动分块与向量化处理
- 基于语义相似度的文档搜索
- 异步处理和任务队列管理
- 实时处理状态监控
- RESTful API接口便于集成

## 安装方法

```bash
pip install oculith
```

## 视觉语言模型配置

本项目支持多种视觉语言模型用于文档处理。通过环境变量配置模型参数：

### 环境变量

| 变量名 | 描述 | 示例 |
|--------|------|------|
| VLM_PROVIDER | 模型提供商 | openai, ollama, gemini |
| VLM_API_URL | API端点URL | https://api.openai.com/v1/chat/completions |
| VLM_API_KEY | API密钥 | sk-your-api-key |
| VLM_MODEL_NAME | 模型名称 | gpt-4-vision-preview |
| VLM_PROMPT_TEMPLATE | 提示语模板 | OCR the full page to markdown |
| VLM_TIMEOUT | 超时时间(秒) | 90 |
| VLM_ADDITIONAL_PARAMS | 额外参数(JSON格式) | {"temperature": 0.2} |

### 示例用法

```bash
# OpenAI
export VLM_PROVIDER=openai
export VLM_API_KEY=sk-your-key
python -m your_application

# Ollama本地模型
export VLM_PROVIDER=ollama
export VLM_MODEL_NAME=llava:latest
python -m your_application

# Google Gemini
export VLM_PROVIDER=gemini
export VLM_API_KEY=your-gemini-key
python -m your_application
```
```

这种分离的方式使代码更加整洁，职责更加明确，也便于后续扩展新的模型提供商。