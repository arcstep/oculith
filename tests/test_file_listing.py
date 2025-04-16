import pytest
import asyncio
import json
from pathlib import Path
from httpx import AsyncClient

# 标记整个测试模块为异步
pytestmark = pytest.mark.asyncio

async def test_file_listing_with_different_states(async_client, auth_headers, test_docx_path):
    """测试文件列表显示不同处理状态的文件"""
    # 1. 上传文件1: 仅上传，不处理
    with open(test_docx_path, "rb") as f:
        files = {"file": (f"no_process_{test_docx_path.name}", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        data = {
            "title": "不处理的文档",
            "auto_process": "false"
        }
        response = await async_client.post(
            "/oculith/files/upload",
            files=files,
            data=data,
            headers=auth_headers
        )
    
    assert response.status_code == 200
    file1_id = response.json()["file_id"]
    print(f"上传未处理文件: {file1_id}")
    
    # 2. 上传文件2: 自动启动处理
    with open(test_docx_path, "rb") as f:
        files = {"file": (f"auto_process_{test_docx_path.name}", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        data = {
            "title": "自动处理的文档",
            "auto_process": "true"
        }
        response = await async_client.post(
            "/oculith/files/upload",
            files=files,
            data=data,
            headers=auth_headers
        )
    
    assert response.status_code == 200
    result2 = response.json()
    file2_id = result2["file_id"]
    task2_id = result2["task_id"]
    print(f"上传自动处理文件: {file2_id}, 任务ID: {task2_id}")
    
    # 3. 获取文件列表并检查状态
    await asyncio.sleep(1)  # 等待一段时间以确保状态更新
    
    response = await async_client.get(
        "/oculith/files",
        headers=auth_headers
    )
    assert response.status_code == 200
    files_list = response.json()
    
    # 确保至少有两个文件
    assert len(files_list) >= 2, f"文件列表应该至少包含2个文件，但只有{len(files_list)}个"
    
    # 找到我们上传的文件
    file1_data = next((f for f in files_list if f["id"] == file1_id), None)
    file2_data = next((f for f in files_list if f["id"] == file2_id), None)
    
    assert file1_data is not None, "未能在列表中找到文件1"
    assert file2_data is not None, "未能在列表中找到文件2"
    
    # 4. 验证文件1状态：未处理
    assert file1_data["has_markdown"] is False, "文件1不应有Markdown内容"
    
    # 5. 手动启动文件1的处理
    response = await async_client.post(
        f"/oculith/files/{file1_id}/process",
        data={"step": "all"},
        headers=auth_headers
    )
    assert response.status_code == 200
    process_result = response.json()
    assert process_result["success"] is True
    assert process_result["file_id"] == file1_id
    task1_id = process_result["task_id"]
    print(f"文件1手动处理任务ID: {task1_id}")
    
    # 6. 等待处理进行一段时间
    await asyncio.sleep(3)  # 给任务处理留出时间
    
    # 7. 再次获取文件列表，验证状态变化
    response = await async_client.get(
        "/oculith/files",
        headers=auth_headers
    )
    assert response.status_code == 200
    updated_files_list = response.json()
    
    # 再次找到我们的文件
    updated_file1 = next((f for f in updated_files_list if f["id"] == file1_id), None)
    updated_file2 = next((f for f in updated_files_list if f["id"] == file2_id), None)
    
    assert updated_file1 is not None, "未能在更新列表中找到文件1"
    assert updated_file2 is not None, "未能在更新列表中找到文件2"
    
    # 打印状态进行验证
    print(f"文件1状态: converted={updated_file1.get('converted')}, has_markdown={updated_file1.get('has_markdown')}")
    print(f"文件2状态: converted={updated_file2.get('converted')}, has_markdown={updated_file2.get('has_markdown')}")
    
    # 8. 等待处理完成
    async def wait_for_task_completion(task_id, max_attempts=15):
        print(f"等待任务 {task_id} 完成...")
        for attempt in range(max_attempts):
            try:
                response = await async_client.get(
                    f"/oculith/tasks/{task_id}",
                    headers=auth_headers
                )
                if response.status_code == 200:
                    status = response.json().get("status")
                    print(f"任务 {task_id} 状态: {status}, 尝试 {attempt+1}/{max_attempts}")
                    if status in ["COMPLETED", "FAILED"]:
                        return status
            except Exception as e:
                print(f"获取任务状态时出错: {e}")
            await asyncio.sleep(1)
        return None
    
    # 等待两个任务完成
    status1 = await wait_for_task_completion(task1_id)
    status2 = await wait_for_task_completion(task2_id)
    
    print(f"最终状态 - 任务1: {status1}, 任务2: {status2}")
    
    # 9. 最终检查文件列表
    response = await async_client.get(
        "/oculith/files",
        headers=auth_headers
    )
    final_files_list = response.json()
    
    final_file1 = next((f for f in final_files_list if f["id"] == file1_id), None)
    final_file2 = next((f for f in final_files_list if f["id"] == file2_id), None)
    
    print(f"最终文件1状态: converted={final_file1.get('converted')}, has_markdown={final_file1.get('has_markdown')}")
    print(f"最终文件2状态: converted={final_file2.get('converted')}, has_markdown={final_file2.get('has_markdown')}")
    
    # 至少一个文件应该成功转换
    assert (final_file1.get("has_markdown") is True or final_file2.get("has_markdown") is True), \
           "至少一个文件应该已转换为Markdown" 