import os
import pytest
import asyncio
import json
from pathlib import Path
from httpx import AsyncClient

# 标记整个测试模块为异步
pytestmark = pytest.mark.asyncio

# 直接在文件中定义函数
def parse_sse_events(content):
    """解析SSE格式的响应内容为事件列表"""
    events = []
    current_event = {"event": None, "data": []}
    
    for line in content.split("\n"):
        if not line.strip():
            if current_event["data"]:
                data_str = "".join(current_event["data"])
                try:
                    current_event["data"] = json.loads(data_str)
                except:
                    pass
                events.append(current_event)
                current_event = {"event": None, "data": []}
        elif line.startswith("event:"):
            current_event["event"] = line.replace("event:", "").strip()
        elif line.startswith("data:"):
            current_event["data"].append(line.replace("data:", "").strip())
    
    return events

async def test_upload_convert_process_flow(async_client, auth_headers, test_docx_path):
    """测试上传、转换和监控进度的完整流程"""
    # 1. 上传文件并开始处理
    with open(test_docx_path, "rb") as f:
        files = {"file": (test_docx_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        data = {
            "title": "测试文档",
            "description": "用于测试的文档",
            "tags": json.dumps(["测试", "API"]),
            "auto_process": "true"  # 上传后自动处理
        }
        response = await async_client.post(
            "/oculith/files/upload",
            files=files,
            data=data,
            headers=auth_headers
        )
    
    # 验证上传成功
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "file_id" in result
    assert "task_id" in result
    assert result["auto_process"] is True
    
    file_id = result["file_id"]
    task_id = result["task_id"]
    process_stream_url = result["process_stream_url"]

    print(f"文件已上传: file_id={file_id}, task_id={task_id}")

    # 2. 监控处理进度
    # 注意：在测试环境中，我们不能直接使用StreamingResponse的流式特性
    # 但可以验证接口返回成功，并通过获取任务状态间接验证进度
    response = await async_client.get(
        f"/oculith/files/{file_id}/process/stream",
        headers=auth_headers
    )
    assert response.status_code == 200
    
    # 3. 轮询检查任务状态，直到完成或失败
    max_attempts = 20
    final_status = None
    
    for attempt in range(max_attempts):
        response = await async_client.get(
            f"/oculith/tasks/{task_id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        task_status = response.json()
        status = task_status["status"]
        
        print(f"任务状态 (尝试 {attempt+1}/{max_attempts}): {status}")
        
        # 检查任务是否已完成或失败
        if status in ["COMPLETED", "FAILED"]:
            final_status = status
            break
            
        # 等待一段时间后再次检查
        await asyncio.sleep(1)
    
    # 断言任务最终完成
    assert final_status == "COMPLETED", f"任务应当成功完成，但状态是: {final_status}"
    
    # 4. 验证文件已被转换并有Markdown内容
    response = await async_client.get(
        f"/oculith/files/{file_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    file_info = response.json()
    
    assert file_info["converted"] is True, "文件应该已被转换"
    assert file_info["has_markdown"] is True, "文件应该有Markdown内容"
    
    # 5. 获取转换后的Markdown内容
    response = await async_client.get(
        f"/oculith/files/{file_id}/markdown",
        headers=auth_headers
    )
    assert response.status_code == 200
    markdown_result = response.json()
    
    assert markdown_result["success"] is True
    assert "content" in markdown_result
    assert len(markdown_result["content"]) > 0, "Markdown内容不应为空"
    
    # 打印部分内容作为验证
    print(f"Markdown内容 (前100字符): {markdown_result['content'][:100]}...")

async def test_remote_bookmark_convert(async_client, auth_headers):
    """测试收藏远程URL并转换的流程"""
    # 使用公开可访问的URL (GitHub上的一个Markdown文件)
    test_url = "https://raw.githubusercontent.com/docling-project/docling/main/README.md"
    
    # 1. 收藏远程URL并启动处理
    data = {
        "url": test_url,
        "title": "远程URL测试",
        "description": "测试远程URL收藏和处理",
        "auto_process": "true"
    }
    
    response = await async_client.post(
        "/oculith/files/bookmark-remote",
        data=data,
        headers=auth_headers
    )
    
    # 验证收藏成功
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "file_id" in result
    assert "task_id" in result
    assert result["auto_process"] is True
    
    file_id = result["file_id"]
    task_id = result["task_id"]
    
    print(f"远程URL已收藏: file_id={file_id}, task_id={task_id}")
    
    # 2. 检查任务状态并等待完成
    max_attempts = 20
    final_status = None
    
    for attempt in range(max_attempts):
        response = await async_client.get(
            f"/oculith/tasks/{task_id}",
            headers=auth_headers
        )
        if response.status_code != 200:
            print(f"获取任务状态失败: {response.status_code}")
            await asyncio.sleep(1)
            continue
            
        task_status = response.json()
        status = task_status["status"]
        
        print(f"远程URL任务状态 (尝试 {attempt+1}/{max_attempts}): {status}")
        
        if status in ["COMPLETED", "FAILED"]:
            final_status = status
            break
            
        await asyncio.sleep(1)
    
    # 验证任务状态
    # 注意：远程URL处理可能会失败，取决于URL可访问性
    print(f"远程URL处理最终状态: {final_status}")
    
    # 3. 检查文件信息
    response = await async_client.get(
        f"/oculith/files/{file_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    file_info = response.json()
    
    # 打印文件信息进行验证
    print(f"远程URL文件信息: source_type={file_info.get('source_type')}, has_markdown={file_info.get('has_markdown')}")
    
    # 确保是远程来源的文件
    assert file_info["source_type"] == "remote"
    assert file_info["source_url"] == test_url 