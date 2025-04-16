#!/bin/bash
# 诊断模式运行测试，只显示警告和错误，方便查看问题

# 设置环境变量
# 1. 过滤第三方库警告
source .env.test
# 2. 设置日志级别
export PYTHONWARNINGS=default
# 3. 设置Python日志环境变量，强制所有日志为WARNING级别
export PYTHONLOG=WARNING

echo "诊断模式：运行测试并只显示警告和错误..."

# 运行测试，使用-v参数增加测试输出详细程度
# --no-header 移除pytest标题
# -v 显示每个测试名称
# --no-summary 移除最后的摘要
poetry run python -m pytest tests/ -v --no-header $@

echo "诊断完成" 