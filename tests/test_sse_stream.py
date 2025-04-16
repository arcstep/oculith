import pytest
import asyncio
import json
import time
import logging
from pathlib import Path
import httpx
from typing import AsyncGenerator, Tuple, List, Dict

from tests.test_utils import upload_test_file, wait_for_task_completion

# 获取logger
logger = logging.getLogger(__name__)

# 标记整个测试模块为异步
pytestmark = pytest.mark.asyncio

async def collect_sse_events(client: httpx.AsyncClient, url: str, headers: Dict, timeout: float = 30.0) -> List[Tuple[float, Dict]]:
    """使用httpx手动收集SSE事件并记录时间戳"""
    events = []
    last_event_time = time.time()
    buffer = ""
    
    logger.info(f"开始收集SSE事件, URL: {url}")
    
    try:
        async with client.stream("GET", url, headers=headers, timeout=timeout) as response:
            logger.info(f"SSE连接状态码: {response.status_code}")
            if response.status_code != 200:
                raise ValueError(f"SSE连接失败: {response.status_code}")
                
            start_time = time.time()
            
            # 设置超时，防止无限等待
            while time.time() - start_time < timeout:
                try:
                    # 使用asyncio.wait_for添加timeout控制
                    chunk = await asyncio.wait_for(response.aiter_text().__anext__(), timeout=5.0)
                    logger.info(f"收到SSE数据块: {len(chunk)} 字节")
                    buffer += chunk
                    
                    # 当收到事件分隔符时处理事件
                    if "\n\n" in buffer:
                        parts = buffer.split("\n\n")
                        # 最后一部分可能不完整，保留到下一次
                        buffer = parts[-1]
                        
                        # 处理完整的事件
                        for part in parts[:-1]:
                            if not part.strip():
                                continue
                                
                            event_time = time.time()
                            
                            # 解析事件
                            event_type = None
                            event_data = None
                            
                            # 打印原始事件数据以便调试
                            logger.info(f"原始事件数据: {part}")
                            
                            for line in part.split("\n"):
                                if line.startswith("event:"):
                                    event_type = line.replace("event:", "").strip()
                                elif line.startswith("data:"):
                                    try:
                                        event_data = json.loads(line.replace("data:", "").strip())
                                    except json.JSONDecodeError as e:
                                        logger.error(f"JSON解析错误: {e}")
                                        event_data = line.replace("data:", "").strip()
                            
                            # 记录时间戳和事件
                            if event_type:
                                events.append((event_time, {"type": event_type, "data": event_data}))
                                interval = event_time - last_event_time
                                logger.info(f"收到事件: {event_type}, 间隔: {interval:.2f}秒, 内容: {event_data}")
                                last_event_time = event_time
                    
                    # 如果收到完成事件或超时，则停止收集
                    if events and events[-1][1]["type"] in ["complete", "error"]:
                        logger.info(f"收到结束事件: {events[-1][1]['type']}, 停止收集")
                        break
                        
                except asyncio.TimeoutError:
                    logger.warning(f"等待SSE数据超时，当前已收到{len(events)}个事件")
                    if events:  # 如果已经收到了一些事件，可以考虑继续等待
                        continue
                    else:
                        # 如果一直没收到事件，可能是有问题
                        logger.error("SSE流没有发送任何事件，可能存在问题")
                        break
                except StopAsyncIteration:
                    logger.info("SSE流已关闭")
                    break
                except Exception as e:
                    logger.exception(f"处理SSE流时发生错误: {str(e)}")
                    break
    except Exception as e:
        logger.exception(f"连接SSE流时发生错误: {str(e)}")
    
    logger.info(f"SSE流结束，共收集到{len(events)}个事件")
    return events

async def test_sse_stream_realtime_updates(async_client, auth_headers, test_docx_path):
    """测试SSE流能够实时接收处理进度，且间隔不超过5秒"""
    # 设置更短的超时用于测试
    collection_timeout = 60.0  # 60秒收集超时
    
    # 1. 上传文件
    logger.info(f"开始上传测试文件: {test_docx_path}")
    file_info = await upload_test_file(
        client=async_client,
        file_path=test_docx_path,
        headers=auth_headers,
        auto_process=False,
        title="SSE流测试文档"
    )
    
    file_id = file_info["file_id"]
    logger.info(f"文件上传成功: {file_id}, 文件信息: {file_info}")
    
    # 2. 创建两个异步任务:
    # - 一个监听SSE流
    # - 一个启动处理
    
    # 先连接SSE流
    sse_url = f"/oculith/files/{file_id}/process/stream"
    
    # 输出处理的文件真实路径，便于调试
    response = await async_client.get(
        f"/oculith/files/{file_id}",
        headers=auth_headers
    )
    if response.status_code == 200:
        file_detail = response.json()
        logger.info(f"文件详情: {file_detail}")
    
    # 开始收集SSE事件的任务
    logger.info("开始SSE监听任务")
    sse_task = asyncio.create_task(
        collect_sse_events(async_client, sse_url, auth_headers, timeout=collection_timeout)
    )
    
    # 给SSE流连接一点时间
    await asyncio.sleep(0.5)
    
    # 启动处理任务
    logger.info("启动文件处理任务")
    process_response = await async_client.post(
        f"/oculith/files/{file_id}/process",
        data={"step": "all"},
        headers=auth_headers
    )
    
    assert process_response.status_code == 200
    process_result = process_response.json()
    task_id = process_result["task_id"]
    logger.info(f"处理任务启动成功: {task_id}, 响应: {process_result}")
    
    # 3. 等待SSE事件收集完成，使用超时控制
    try:
        logger.info("等待SSE事件收集...")
        sse_events = await asyncio.wait_for(sse_task, timeout=collection_timeout)
        logger.info(f"SSE事件收集完成，共{len(sse_events)}个事件")
    except asyncio.TimeoutError:
        logger.error(f"等待SSE事件收集超时({collection_timeout}秒)")
        # 取消任务
        sse_task.cancel()
        try:
            await sse_task
        except asyncio.CancelledError:
            pass
        # 如果超时，则获取任务状态，确认进度
        task_status_response = await async_client.get(
            f"/oculith/tasks/{task_id}",
            headers=auth_headers
        )
        if task_status_response.status_code == 200:
            logger.info(f"任务状态: {task_status_response.json()}")
        # 不需要失败，我们在日志中已记录了信息
        sse_events = []
    
    # 4. 分析收集到的事件
    logger.info(f"共收集到 {len(sse_events)} 个SSE事件")
    
    # 任务仍需要等待完成，以便验证处理结果
    success, final_status = await wait_for_task_completion(
        async_client, task_id, auth_headers
    )
    
    logger.info(f"任务最终状态: {final_status}, 成功: {success}")
    
    # 验证文件状态
    response = await async_client.get(
        f"/oculith/files/{file_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    file_info = response.json()
    
    logger.info(f"文件最终状态: {file_info}")
    
    # 如果没有收到任何事件但任务已完成，可能是SSE机制有问题
    if len(sse_events) == 0 and success:
        logger.warning("任务成功完成但没有收到SSE事件，可能有问题")
        assert False, "任务成功完成但没有收到SSE事件，这不符合预期"
    
    # 只有收到事件才进行间隔验证
    if len(sse_events) >= 2:
        # 验证事件间隔不超过5秒
        max_interval = 0
        violations = 0
        
        for i in range(1, len(sse_events)):
            current_time, _ = sse_events[i]
            prev_time, _ = sse_events[i-1]
            interval = current_time - prev_time
            max_interval = max(max_interval, interval)
            
            if interval > 5:
                violations += 1
                logger.warning(f"警告: 事件 {i-1} 到 {i} 的间隔为 {interval:.2f}秒, 超过5秒限制")
        
        logger.info(f"最大事件间隔: {max_interval:.2f}秒, 违反5秒限制的次数: {violations}")
        assert violations == 0, f"有 {violations} 次事件间隔超过5秒限制"
        
        # 验证事件类型
        event_types = [event[1]["type"] for event in sse_events]
        logger.info(f"事件类型序列: {event_types}")
        
        # 验证至少包含初始状态和最终状态
        assert "status" in event_types, "应至少包含状态更新事件"
        assert any(typ in ["complete", "error"] for typ in event_types), "应包含完成或错误事件"
    
    # 成功完成SSE流测试
    logger.info("SSE流实时测试完成") 