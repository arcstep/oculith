# Oculith API 结构修改

## 修改概述

为提高系统灵活性、健壮性和用户体验，API结构进行了以下修改：

1. **将上传和处理逻辑分离**：文件上传与处理步骤分离，用户可以先上传文件，再决定何时处理
2. **增加处理状态流式获取**：提供实时查看文件处理进度的流式API
3. **增加任务队列系统**：处理任务进入队列，有序执行，避免资源争用
4. **提供细粒度控制**：用户可选择只执行特定处理步骤，如仅转换、仅切片或仅向量化
5. **完善错误恢复机制**：处理失败可从失败点重试，不需重新开始整个流程

## 新的API端点

### 文件管理

- `POST /oculith/files/upload` - 仅上传文件，不处理
- `POST /oculith/files/register-remote` - 仅注册远程文件，不处理
- `GET /oculith/files/{file_id}/status` - 获取文件处理状态
- `GET /oculith/files/{file_id}/process/stream` - 以SSE流获取实时处理状态

### 任务管理

- `POST /oculith/files/{file_id}/process` - 添加文件处理任务，支持步骤选择
- `GET /oculith/tasks/{task_id}` - 查询任务状态
- `POST /oculith/tasks/{task_id}/cancel` - 取消任务

## 文件处理状态

文件处理流程分为以下步骤，对应`FileProcessStatus`枚举：

1. `UPLOADED` - 已上传/注册，尚未处理
2. `CONVERTING` - 正在转换为Markdown
3. `CONVERTED` - 转换完成，尚未切片
4. `CHUNKING` - 正在切片
5. `CHUNKED` - 切片完成，尚未向量化
6. `INDEXING` - 正在向量化索引
7. `COMPLETED` - 所有处理完成
8. `FAILED` - 处理失败
9. `QUEUED` - 在队列中等待处理

## 任务队列系统

通过简单的内存队列系统实现以下功能：

1. 任务优先级排序
2. 限制并发处理数量（防止资源耗尽）
3. 提供任务取消功能
4. 保证单个文件处理线程安全（文件锁）
5. 支持任务状态查询和历史记录

## 使用实例

### 上传文件后分开处理

```bash
# 1. 上传文件
curl -X POST /oculith/files/upload -F "file=@document.pdf"
# 返回file_id

# 2. 启动处理
curl -X POST /oculith/files/{file_id}/process -F "step=all"

# 3. 监控处理状态
curl /oculith/files/{file_id}/status

# 或使用SSE流实时监控
# 前端使用 EventSource API 监听 /oculith/files/{file_id}/process/stream
```

### 分步处理

```bash
# 1. 仅转换为Markdown
curl -X POST /oculith/files/{file_id}/process -F "step=convert"

# 2. 等待转换完成后，仅执行切片
curl -X POST /oculith/files/{file_id}/process -F "step=chunk"

# 3. 等待切片完成后，仅执行向量化
curl -X POST /oculith/files/{file_id}/process -F "step=index"
```

## 前端实现建议

前端可使用以下方式与新API交互：

1. 上传文件时，使用`/oculith/files/upload`，获取`file_id`
2. 启动处理时，调用`/oculith/files/{file_id}/process`，获取`task_id`
3. 使用EventSource监听`/oculith/files/{file_id}/process/stream`获取实时处理进度
4. 根据状态更新UI，显示当前处理阶段和进度
5. 提供取消按钮，调用`/oculith/tasks/{task_id}/cancel`取消处理

## 未来扩展

该架构易于扩展，可考虑：

1. 使用Redis替代内存队列，实现分布式任务队列
2. 添加更多错误恢复机制和日志记录
3. 实现更细粒度的任务监控和控制
4. 增加系统资源使用监控和限制 