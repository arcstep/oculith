import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from httpx import AsyncClient

async def upload_test_file(
    client: AsyncClient, 
    file_path: Path, 
    headers: Dict[str, str], 
    auto_process: bool = False,
    title: str = "测试文档",
    description: str = "测试描述"
) -> Dict[str, Any]:
    """上传测试文件并返回响应信息"""
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        data = {
            "title": title,
            "description": description, 
            "auto_process": str(auto_process).lower()
        }
        response = await client.post(
            "/oculith/files/upload",
            files=files,
            data=data,
            headers=headers
        )
    
    assert response.status_code == 200, f"上传失败: {response.text}"
    return response.json()

async def wait_for_task_completion(
    client: AsyncClient, 
    task_id: str, 
    headers: Dict[str, str],
    timeout: int = 60
) -> Tuple[bool, str]:
    """等待任务完成"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = await client.get(f"/oculith/tasks/{task_id}", headers=headers)
        if response.status_code != 200:
            return False, "ERROR"
        
        task_info = response.json()
        status = task_info.get("status")
        print(f"任务状态: {status}")
        
        # 检查终止状态
        if status == "completed":
            return True, status  # 立即返回
        if status in ["failed", "error"]:
            return False, status
            
        await asyncio.sleep(1)
    
    return False, "TIMEOUT" 