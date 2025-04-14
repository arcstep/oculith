# Oculith 文档处理工具

## 简介

Oculith 是一个强大的文档处理工具，可以将多种格式的文档（如PDF、Word、HTML等）转换为Markdown等结构化格式。它既可以作为独立服务运行，也可以集成到你的应用中。

## 功能特点

- 支持多种文档格式（PDF、Word、HTML、图片等）
- 文档转换为Markdown、文本等格式
- 支持OCR文字识别和表格检测
- 可通过API接口集成到其他应用
- 简单易用的文件管理功能

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

#### 1. 上传并转换文档

```
POST /oculith/upload/convert
```

使用表单提交：
- `file`: 要上传的文件
- `title`: 可选的文档标题
- `description`: 可选的文档描述
- `tags`: 可选的标签列表

#### 2. 转换本地文件

```
POST /oculith/local/convert
```

提交参数：
- `path`: 本地文件的完整路径

#### 3. 转换远程URL文件

```
POST /oculith/remote/convert
```

提交参数：
- `url`: 远程文件的URL地址

#### 4. 获取支持的格式

```
GET /oculith/formats
```

#### 5. 获取文件列表

```
GET /oculith/files
```

## 文件管理功能

Oculith 还提供了简单的文件管理功能：

- 上传文件：`POST /oculith/local/upload`
- 获取文件信息：`GET /oculith/files/{file_id}`
- 获取文件内容：`GET /oculith/files/{file_id}/content`
- 更新文件元数据：`PATCH /oculith/files/{file_id}`
- 删除文件：`DELETE /oculith/files/{file_id}`
- 下载文件：`GET /oculith/files/{file_id}/download`

## 使用示例

### 使用curl上传并转换文档

```bash
curl -X POST "http://localhost:31573/oculith/upload/convert" \
  -H "Authorization: Bearer 你的令牌" \
  -F "file=@/路径/文档.pdf" \
  -F "title=测试文档" \
  -F "description=这是一个测试文档"
```

### 转换本地文件

```bash
curl -X POST "http://localhost:31573/oculith/local/convert" \
  -H "Authorization: Bearer 你的令牌" \
  -F "path=/绝对路径/文档.pdf"
```

## 注意事项

- 第一次使用时需要设置环境变量 `FASTAPI_SECRET_KEY` 作为认证密钥
- 对于大文件处理，可能需要更长的处理时间
- 默认情况下，每个用户的存储限制为200MB
- 临时文件会存储在系统临时目录中

## 更多帮助

启动服务后，你可以访问 `http://localhost:31573/docs` 获取完整的API文档。
