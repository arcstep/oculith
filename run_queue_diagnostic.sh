#!/bin/bash
# 队列问题诊断专用脚本，只显示队列相关的警告和错误

# 设置环境变量
# 1. 过滤第三方库警告，但保留队列相关的警告
source .env.test
# 2. 设置日志级别，WARNING, ERROR和CRITICAL级别
export PYTHONLOG=WARNING

echo "队列诊断模式：查看队列管理相关警告和错误..."

# 使用grep过滤，只显示queue_manager相关的日志
poetry run python -m pytest tests/test_document_processor.py -v | grep -E "queue_manager|worker|task|ERROR|WARN"

echo "队列诊断完成" 