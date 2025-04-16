import pytest
import asyncio
import logging
from typing import List, Dict, Any
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

from oculith.api.endpoints import format_sse

# 获取logger
logger = logging.getLogger(__name__)

# 标记整个测试模块为异步
pytestmark = pytest.mark.asyncio

# 创建测试用的SSE生成器
async def mock_sse_generator():
    """模拟SSE事件流生成器，用于验证SSE格式是否正确"""
    # 发送初始化事件
    yield format_sse({"type": "init", "message": "测试开始"}, event="init")
    await asyncio.sleep(0.1)
    
    # 发送进度事件
    for i in range(1, 6):
        yield format_sse({"type": "progress", "progress": i * 20}, event="progress")
        await asyncio.sleep(0.1)
    
    # 发送完成事件
    yield format_sse({"type": "complete", "success": True}, event="complete")

async def test_format_sse():
    """测试SSE格式化函数是否正确工作"""
    # 测试基本的格式化
    test_data = {"message": "测试消息", "value": 123}
    formatted = format_sse(test_data, event="test")
    
    # 验证格式
    assert "event: test" in formatted
    assert "data: {" in formatted
    assert "\"message\": \"测试消息\"" in formatted
    assert "\"value\": 123" in formatted
    
    # 验证结尾空行（SSE规范要求）
    assert formatted.endswith("\n\n")
    
    logger.info(f"格式化的SSE消息: {formatted!r}")

async def test_sse_generator():
    """测试SSE生成器是否能够正确生成事件流"""
    # 创建一个临时应用来测试SSE流
    app = FastAPI()
    
    @app.get("/test-sse")
    async def test_sse_endpoint():
        return StreamingResponse(
            mock_sse_generator(),
            media_type="text/event-stream"
        )
    
    # 使用TestClient进行测试
    client = TestClient(app)
    response = client.get("/test-sse")
    
    # 验证响应状态码和内容类型
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    
    # 解析SSE响应
    events = []
    current_event = {"event": None, "data": ""}
    
    for line in response.iter_lines():
        # 只有在line是bytes类型时才需要解码
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line:
            if current_event["event"]:
                # 尝试解析JSON数据
                try:
                    current_event["data"] = json.loads(current_event["data"])
                except:
                    pass
                events.append(current_event.copy())
                current_event = {"event": None, "data": ""}
        elif line.startswith("event:"):
            current_event["event"] = line.replace("event:", "").strip()
        elif line.startswith("data:"):
            current_event["data"] = line.replace("data:", "").strip()
    
    # 验证是否收到了所有预期的事件
    assert len(events) >= 7, f"应该收到7个事件，但只收到了{len(events)}个"
    
    # 验证事件类型是否符合预期
    event_types = [e["event"] for e in events]
    assert event_types[0] == "init", "第一个事件应该是init"
    assert "progress" in event_types, "应该有progress事件"
    assert "complete" in event_types, "应该有complete事件"
    
    logger.info(f"收到的SSE事件: {events}")
    
    # 验证每个事件是否有正确的数据
    for event in events:
        assert "data" in event, f"事件缺少data字段: {event}"
        if event["event"] == "progress":
            assert "progress" in event["data"], f"progress事件缺少进度信息: {event}" 