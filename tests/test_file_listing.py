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
                    task_info = response.json()
                    status = task_info.get("status", "").lower()  # 转为小写进行比较
                    print(f"任务 {task_id} 状态: {status}, 尝试 {attempt+1}/{max_attempts}")
                    if status in ["completed", "failed", "error"]:
                        return status
                else:
                    print(f"获取任务状态失败: HTTP {response.status_code}")
                    if attempt >= max_attempts // 2:  # 如果已经尝试了一半以上次数还无法获取状态，提前退出
                        return "error"
            except Exception as e:
                print(f"获取任务状态时出错: {e}")
                if attempt >= max_attempts // 2:  # 连续错误超过一半最大尝试次数，提前退出
                    return "error"
            await asyncio.sleep(1)
        
        # 达到最大尝试次数，获取最后状态并返回
        try:
            response = await async_client.get(
                f"/oculith/tasks/{task_id}",
                headers=auth_headers
            )
            if response.status_code == 200:
                final_status = response.json().get("status", "").lower()
                print(f"达到最大尝试次数，最终状态: {final_status}")
                return final_status
        except Exception:
            pass
        
        print(f"任务 {task_id} 达到最大尝试次数，但未完成")
        return "timeout"
    
    # 等待两个任务完成
    task1_future = asyncio.create_task(wait_for_task_completion(task1_id))
    task2_future = asyncio.create_task(wait_for_task_completion(task2_id))
    
    # 设置总超时，避免无限等待
    try:
        # 等待任务，最多30秒
        status1, status2 = await asyncio.wait_for(
            asyncio.gather(
                task1_future, 
                task2_future,
                return_exceptions=True
            ),
            timeout=30  # 最多等待30秒
        )
        
        # 处理异常情况
        if isinstance(status1, Exception):
            print(f"等待任务1出错: {status1}")
            status1 = "error"
        if isinstance(status2, Exception):
            print(f"等待任务2出错: {status2}")
            status2 = "error"
    except asyncio.TimeoutError:
        print("等待任务超时")
        # 取消未完成的任务
        if not task1_future.done():
            task1_future.cancel()
        if not task2_future.done():
            task2_future.cancel()
        status1 = status1 if 'status1' in locals() else "timeout"
        status2 = status2 if 'status2' in locals() else "timeout"
    
    print(f"最终状态 - 任务1: {status1}, 任务2: {status2}")
    
    # 9. 最终检查文件列表，不管任务是否完成都检查当前状态
    response = await async_client.get(
        "/oculith/files",
        headers=auth_headers
    )
    assert response.status_code == 200, "获取文件列表应成功"
    final_files_list = response.json()
    
    final_file1 = next((f for f in final_files_list if f["id"] == file1_id), None)
    final_file2 = next((f for f in final_files_list if f["id"] == file2_id), None)
    
    assert final_file1 is not None, "文件1应在最终列表中"
    assert final_file2 is not None, "文件2应在最终列表中"
    
    print(f"最终文件1状态: converted={final_file1.get('converted')}, has_markdown={final_file1.get('has_markdown')}")
    print(f"最终文件2状态: converted={final_file2.get('converted')}, has_markdown={final_file2.get('has_markdown')}")
    
    # 检查加工进度，如果任务成功完成，文件应已转换
    if status1 == "completed":
        assert final_file1.get("has_markdown") is True, "任务成功时文件1应已转换为Markdown"
    if status2 == "completed":
        assert final_file2.get("has_markdown") is True, "任务成功时文件2应已转换为Markdown"
    
    # 只要有一个文件状态变化，就认为测试成功（不一定完全转换）
    file1_processed = final_file1.get("has_markdown", False) or final_file1.get("converted", False)
    file2_processed = final_file2.get("has_markdown", False) or final_file2.get("converted", False)
    
    # 至少有文件状态应该有变化
    assert file1_processed or file2_processed, "至少一个文件应该有处理进度" 