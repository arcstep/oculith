import pytest
import asyncio
import logging
import tempfile
from pathlib import Path

from tests.test_utils import upload_test_file, wait_for_task_completion

# 获取logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARN)

# 标记整个测试模块为异步
pytestmark = pytest.mark.asyncio

async def test_document_processor_initialization(async_client, auth_headers):
    """测试文档处理器组件是否正确初始化"""
    # 获取服务信息
    response = await async_client.get(
        "/oculith/info",
        headers=auth_headers
    )
    assert response.status_code == 200
    info = response.json()
    logger.info(f"服务信息: {info}")
    
    # 验证支持的格式
    response = await async_client.get(
        "/oculith/formats",
        headers=auth_headers
    )
    assert response.status_code == 200
    formats = response.json()
    logger.info(f"支持的格式: {formats}")
    
    # 确认有docx格式支持
    assert "docx" in formats["formats"], "应该支持docx格式"

async def test_document_processor_conversion(async_client, auth_headers, test_docx_path):
    """测试文档处理器能否正确处理和转换文档"""
    # 1. 上传文件并等待处理完成
    file_info = await upload_test_file(
        client=async_client,
        file_path=test_docx_path,
        headers=auth_headers,
        auto_process=True,  # 自动启动处理
        title="处理器测试文档"
    )
    
    file_id = file_info["file_id"]
    task_id = file_info["task_id"]
    logger.info(f"文件已上传并开始处理: file_id={file_id}, task_id={task_id}")
    
    # 2. 等待处理完成
    success, final_status = await wait_for_task_completion(
        async_client, task_id, auth_headers, 
        timeout=60  # 给足够的时间处理
    )
    
    logger.info(f"处理任务完成: success={success}, status={final_status}")
    
    # 3. 检查处理结果
    response = await async_client.get(
        f"/oculith/files/{file_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    file_info = response.json()
    logger.info(f"文件处理后状态: {file_info}")
    
    # 验证文件已被转换
    assert file_info.get("converted") is True, "文件应该已被转换"
    assert file_info.get("has_markdown") is True, "应该生成Markdown内容"
    
    # 4. 获取Markdown内容
    response = await async_client.get(
        f"/oculith/files/{file_id}/markdown",
        headers=auth_headers
    )
    assert response.status_code == 200
    markdown_result = response.json()
    
    # 检查Markdown内容
    assert "content" in markdown_result, "应该返回Markdown内容"
    assert len(markdown_result["content"]) > 0, "Markdown内容不应为空"
    logger.info(f"Markdown内容长度: {len(markdown_result['content'])}")
    
    # 简单确认内容看起来像Markdown
    content = markdown_result["content"]
    assert "#" in content or "*" in content or "-" in content, "内容应该像Markdown格式"

async def test_document_processor_components_availability(app):
    """测试应用中各处理组件是否可用"""
    # 检查应用状态中是否有所需组件
    assert hasattr(app.state, "converter"), "应用中应该有converter组件"
    assert hasattr(app.state, "files_service"), "应用中应该有files_service组件"
    assert hasattr(app.state, "retriever"), "应用中应该有retriever组件"
    assert hasattr(app.state, "queue_manager"), "应用中应该有queue_manager组件"
    
    # 检查queue_manager是否启动
    assert app.state.queue_manager.is_running, "队列管理器应该处于运行状态"
    
    # 日志输出组件信息
    logger.info(f"Converter: {app.state.converter}")
    logger.info(f"Files Service: {app.state.files_service}")
    logger.info(f"Retriever: {app.state.retriever}")
    logger.info(f"Queue Manager: {app.state.queue_manager}")
    
    # 检查允许的格式
    allowed_formats = [fmt.value for fmt in app.state.converter.allowed_formats]
    logger.info(f"允许的格式: {allowed_formats}")
    
    # 确认处理器注册
    assert hasattr(app.state.queue_manager, "_processors"), "队列管理器应有处理器字典"
    logger.info(f"已注册处理器: {list(app.state.queue_manager._processors.keys())}")
    
    # 确认有基本的处理器
    from oculith.core.queue_manager import TaskType
    assert TaskType.CONVERT in app.state.queue_manager._processors, "应该有转换处理器"
    assert TaskType.PROCESS_ALL in app.state.queue_manager._processors, "应该有全流程处理器" 