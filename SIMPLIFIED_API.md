# 简化后的API结构

## 总体原则
- 简化冗余API，统一处理流程
- 提供一致的用户体验
- 支持文件上传、远程文件收藏、处理和状态监控的完整流程

## 核心API

### 1. 文件上传与处理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/oculith/files/upload` | POST | 上传文件并可选自动处理 |
| `/oculith/files/bookmark-remote` | POST | 收藏远程URL文件并可选自动处理 |
| `/oculith/files/{file_id}/process` | POST | 处理已上传文件，可指定步骤 |
| `/oculith/files/{file_id}/process/stream` | GET | 获取文件处理SSE实时状态更新 |

### 2. 文件管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/oculith/files` | GET | 获取用户文件列表 |
| `/oculith/files/{file_id}` | GET | 获取单个文件信息 |
| `/oculith/files/{file_id}` | PATCH | 更新文件元数据 |
| `/oculith/files/{file_id}` | DELETE | 删除文件 |
| `/oculith/files/{file_id}/markdown` | GET | 获取文件Markdown内容 |
| `/oculith/files/{file_id}/download` | GET | 下载原始文件 |
| `/oculith/files/storage/status` | GET | 获取用户存储状态 |

### 3. 检索功能

| 端点 | 方法 | 描述 |
|------|------|------|
| `/oculith/search/chunks` | POST | 检索与文本相似的切片 |
| `/oculith/search/documents` | POST | 检索与文本相似的文档 |

### 4. 任务管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/oculith/tasks/{task_id}` | GET | 获取任务状态 |
| `/oculith/tasks/{task_id}/cancel` | POST | 取消任务 |

### 5. 系统信息

| 端点 | 方法 | 描述 |
|------|------|------|
| `/oculith/info` | GET | 获取服务信息 |
| `/oculith/formats` | GET | 获取支持的文件格式 |

## 主要用户流程

### 1. 上传并处理文件
1. 调用 `/oculith/files/upload`，设置 `auto_process=true`
2. 连接 `/oculith/files/{file_id}/process/stream` 以SSE方式监控处理进度
3. 处理完成后，从 `/oculith/files/{file_id}/markdown` 获取内容

### 2. 分步处理文件
1. 调用 `/oculith/files/upload`，设置 `auto_process=false`
2. 调用 `/oculith/files/{file_id}/process` 指定步骤（转换、切片、索引）
3. 连接 `/oculith/files/{file_id}/process/stream` 监控进度

### 3. 处理远程URL
1. 调用 `/oculith/files/bookmark-remote`，设置 `auto_process=true`
2. 连接 `/oculith/files/{file_id}/process/stream` 监控进度

### 4. 搜索相似内容
1. 调用 `/oculith/search/chunks` 或 `/oculith/search/documents` 搜索相似内容 