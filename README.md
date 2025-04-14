# illufly-docling

## 简介

illufly-docling是一个强大的文档处理服务，基于docling技术实现，提供了文档转换、处理和分析功能。支持PDF、Word、HTML等多种格式的文档处理，并可作为独立服务或集成到其他应用中使用。

## 特点

- 支持多种文档格式（PDF、Word、HTML等）
- 提供命令行工具、MCP服务和API接口
- 支持OCR文字识别、表格检测、公式识别
- 可观测的转换过程，实时获取处理进度
- 易于集成到现有应用中

## 安装

### 通过pip安装

```bash
pip install illufly-docling
```

### 从源码安装

```bash
git clone https://github.com/your-org/illufly-docling.git
cd illufly-docling
pip install -e .
```

## 使用方法

### 命令行工具

illufly-docling提供了三种运行模式：

#### 1. 处理文档模式

直接处理文档文件或URL，转换为指定格式：

```bash
# 基本用法
python -m illufly_docling process 文档路径.pdf -f markdown

# 指定输出文件
python -m illufly_docling process 文档路径.docx -f html -o 输出路径.html

# 启用高级功能
python -m illufly_docling process 文档路径.pdf -f markdown --ocr --tables --formulas
```

#### 2. 服务器模式

以MCP服务器模式运行：

```bash
# 使用stdio传输（默认）
python -m illufly_docling server

# 使用SSE传输（HTTP）
python -m illufly_docling server --transport sse --port 8000
```

#### 3. API模式

启动FastAPI测试服务，提供Web API接口：

```bash
python -m illufly_docling api --port 8080
```

API服务启动后，可通过浏览器访问`http://localhost:8080/docs`查看API文档。

### 在应用中集成

#### 使用异步客户端

```python
from illufly_docling.mcp_client import DoclingMcpClient

async def process_document():
    # 创建客户端（默认使用子进程方式）
    client = DoclingMcpClient(user_id="my_user")
    
    try:
        # 处理本地文件
        result = await client.process_document_binary(
            file_path="文档路径.pdf",
            output_format="markdown"
        )
        
        # 处理URL
        result = await client.process_document_url(
            url="https://example.com/document.pdf",
            output_format="html"
        )
        
        # 获取支持的格式
        formats = await client.get_supported_formats()
        
    finally:
        # 关闭客户端
        await client.close()
```

#### 使用同步客户端

```python
from illufly_docling.mcp_client import SyncDoclingMcpClient

# 使用上下文管理器自动关闭连接
with SyncDoclingMcpClient(user_id="my_user") as client:
    # 处理本地文件
    result = client.process_document_binary(
        file_path="文档路径.pdf",
        output_format="markdown"
    )
    
    # 获取支持的格式
    formats = client.get_supported_formats()
```

#### 集成到FastAPI应用

```python
from fastapi import FastAPI, Depends
from illufly_docling.endpoints import mount_docling_service

app = FastAPI()

# 定义获取用户的函数
async def get_current_user():
    # 这里应该是您的用户认证逻辑
    return {"user_id": "default_user"}

# 挂载文档处理服务 - 使用子进程方式（推荐）
client = mount_docling_service(
    app=app,
    require_user=get_current_user,
    use_stdio=True,
    prefix="/api/docs"
)

# 或者连接到已运行的MCP服务
client = mount_docling_service(
    app=app,
    require_user=get_current_user,
    use_stdio=False,
    host="localhost",
    port=8000,
    prefix="/api/docs"
)
```

集成后，您的FastAPI应用将拥有以下端点：
- `POST /api/docs/process` - 处理上传的文档
- `POST /api/docs/process-url` - 处理URL指向的文档
- `GET /api/docs/formats` - 获取支持的文档格式

## 配置选项

### 文档处理选项

- `output_format` - 输出格式 (markdown, text, html, json)
- `enable_remote_services` - 是否启用远程服务
- `do_ocr` - 是否启用OCR
- `do_table_detection` - 是否启用表格检测
- `do_formula_detection` - 是否启用公式检测
- `enable_pic_description` - 是否启用图片描述
- `backend_choice` - 后端选择 (stable, standard, auto)
- `use_original_converter` - 是否使用原始转换器

### 日志选项

- `verbose` - 是否输出详细日志
- `quiet` - 是否仅输出错误日志

## 示例

### 处理PDF文档并提取为Markdown

```python
import asyncio
from illufly_docling.mcp_client import DoclingMcpClient

async def process_pdf():
    client = DoclingMcpClient()
    try:
        result = await client.process_document_binary(
            file_path="sample.pdf",
            output_format="markdown"
        )
        
        if result["success"]:
            print("处理成功!")
            # 获取处理结果
            content = result["result"].get("content", "")
            print(f"提取内容: {content[:200]}...")
        else:
            print(f"处理失败: {result.get('error', '未知错误')}")
            
    finally:
        await client.close()

# 运行异步函数
asyncio.run(process_pdf())
```

### 启动MCP服务器并连接客户端

```python
# 启动服务器 (在单独的终端运行)
# python -m illufly_docling server --transport sse --port 8000

# 客户端连接
from illufly_docling.mcp_client import SyncDoclingMcpClient

# 连接到SSE服务器
client = SyncDoclingMcpClient(
    use_stdio=False,
    host="localhost",
    port=8000
)

try:
    # 获取支持的格式
    formats = client.get_supported_formats()
    print(f"支持的格式: {formats}")
    
    # 处理文件
    result = client.process_document_path(
        file_path="document.docx",
        output_format="text"
    )
    print(result)
    
finally:
    client.close()
```

## 注意事项

- 确保已安装所有依赖，包括mcp包和docling相关组件
- 使用SSE模式需要确保网络端口可访问
- 处理大型文档时可能需要更多内存和处理时间
- 临时文件存储在`/tmp/illufly-docling-uploads`目录下
