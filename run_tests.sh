#!/bin/bash
# 运行测试的脚本，提供不同级别的警告控制

# 检查参数
if [ "$1" == "--no-warnings" ]; then
    echo "运行测试 - 完全禁用所有警告"
    export PYTHONWARNINGS=ignore
    PYTEST_ARGS="-p no:warnings"
    shift
elif [ "$1" == "--filter-warnings" ]; then
    echo "运行测试 - 仅过滤第三方库的已知警告"
    # 使用.env.test中配置的过滤规则
    source .env.test
    PYTEST_ARGS=""
    shift
elif [ "$1" == "--diagnostic" ]; then
    echo "运行测试 - 诊断模式：只显示警告和错误"
    source .env.test
    # 设置环境变量强制日志级别为WARNING
    export PYTHONLOG=WARNING
    # 添加pytest参数来控制日志级别
    PYTEST_ARGS="-v --no-header --log-cli-level=WARNING"
    shift
else
    echo "运行测试 - 显示所有警告（默认）"
    # 清除任何预先设置的警告过滤
    unset PYTHONWARNINGS
    PYTEST_ARGS=""
fi

# 运行测试
poetry run python -m pytest tests/ ${PYTEST_ARGS} $@

echo "测试完成" 