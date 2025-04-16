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

## 快速开始

### 作为服务启动

最简单的方式是直接运行Oculith服务：

```bash
python -m oculith
```

这将在默认端口(31573)启动服务。你可以通过以下选项自定义：

```bash
# 指定端口
python -m oculith --port 8080

# 指定允许的文档格式
python -m oculith --allowed-formats pdf,docx,html

# 指定输出目录
python -m oculith --output-dir ./文档输出
```

### API使用方法

服务启动后，你可以通过以下API进行文档处理：

#### 1. 上传并处理文档

```
POST /oculith/files/upload
```

使用表单提交：
- `file`: 要上传的文件
- `title`: 可选的文档标题
- `description`: 可选的文档描述
- `tags`: 可选的标签列表
- `auto_process`: 是否自动处理(true/false)

#### 2. 收藏远程URL文件

```
POST /oculith/files/bookmark-remote
```

提交参数：
- `url`: 远程文件的URL地址
- `filename`: 可选的文件名
- `title`: 可选的文档标题
- `description`: 可选的文档描述
- `tags`: 可选的标签列表
- `auto_process`: 是否自动处理(true/false)

#### 3. 手动启动文件处理

```
POST /oculith/files/{file_id}/process
```

提交参数：
- `step`: 处理步骤(convert/chunk/index/all)
- `priority`: 任务优先级(数字)

#### 4. 获取支持的格式

```
GET /oculith/formats
```

#### 5. 获取文件列表

```
GET /oculith/files
```

## 文件管理功能

Oculith 提供了完整的文件管理功能：

- 获取文件列表：`GET /oculith/files`
- 获取文件信息：`GET /oculith/files/{file_id}`
- 获取Markdown内容：`GET /oculith/files/{file_id}/markdown`
- 更新文件元数据：`PATCH /oculith/files/{file_id}`
- 删除文件：`DELETE /oculith/files/{file_id}`
- 下载文件：`GET /oculith/files/{file_id}/download`
- 监控处理状态：`GET /oculith/files/{file_id}/process/stream` (SSE流)
- 获取存储状态：`GET /oculith/files/storage/status`

## 任务管理

Oculith 支持异步任务管理：

- 获取任务状态：`GET /oculith/tasks/{task_id}`
- 取消任务：`POST /oculith/tasks/{task_id}/cancel`
- 队列诊断：`GET /oculith/queue/diagnostics`

## 搜索功能

Oculith 支持基于向量相似度的语义检索：

- 检索内容片段：`POST /oculith/search/chunks`
- 检索相似文档：`POST /oculith/search/documents`

## 使用示例

### 使用curl上传并处理文档

```bash
curl -X POST "http://localhost:31573/oculith/files/upload" \
  -F "file=@/路径/文档.pdf" \
  -F "title=测试文档" \
  -F "description=这是一个测试文档" \
  -F "auto_process=true"
```

### 收藏远程URL

```bash
curl -X POST "http://localhost:31573/oculith/files/bookmark-remote" \
  -F "url=https://example.com/document.pdf" \
  -F "title=远程文档" \
  -F "auto_process=true"
```

### 监控处理状态（前端代码）

```javascript
// 使用EventSource监听处理状态
const eventSource = new EventSource(
  'http://localhost:31573/oculith/files/FILE_ID/process/stream',
  { headers: { 'Authorization': 'Bearer 你的令牌' } }
);

eventSource.addEventListener('status', (event) => {
  const data = JSON.parse(event.data);
  console.log(`处理状态: ${data.status}`);
});

eventSource.addEventListener('complete', (event) => {
  console.log('处理完成');
  eventSource.close();
});
```

### 检索相似内容

```bash
curl -X POST "http://localhost:31573/oculith/search/chunks" \
  -F "query=关键词搜索" \
  -F "threshold=0.7" \
  -F "limit=5"
```

## 集成到其他应用

Oculith可以轻松集成到现有的FastAPI应用中：

```python
from fastapi import FastAPI
from oculith.api.endpoints import mount_docling_service

app = FastAPI()

# 挂载Oculith服务
mount_docling_service(
    app=app,
    output_dir="./data/oculith",
    allowed_formats=["pdf", "docx", "html", "md"],
    prefix="/api"  # API端点前缀
)
```

## 注意事项

- 第一次使用时需要设置环境变量 `FASTAPI_SECRET_KEY` 作为认证密钥
- 对于大文件处理，可能需要更长的处理时间
- 默认情况下，每个用户的存储限制为200MB
- 任务队列默认最大并发数为3，可根据服务器资源调整
- 服务重启后任务队列会重置，请妥善管理任务状态

## 更多帮助

启动服务后，你可以访问 `http://localhost:31573/docs` 获取完整的API文档。