import os
import shutil
import tempfile
import pytest
import pytest_asyncio
import asyncio
import logging
from pathlib import Path
from typing import Dict, Generator
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import AsyncClient
import httpx
import types
import time

# 获取logger
logger = logging.getLogger(__name__)

# 配置日志
logging.basicConfig(
    level=logging.WARN,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 导入应用组件
from oculith.api.endpoints import mount_docling_service, verify_token
from oculith.api.endpoints import token_sdk

# 更直接的模拟方法 - 直接替换verify_token函数
@pytest.fixture(scope="session", autouse=True)
def mock_auth():
    """简单直接地替换verify_token函数，总是返回测试用户"""
    # 保存原始函数以便恢复
    original_verify_token = verify_token
    
    # 创建一个简单的异步函数，始终返回测试用户
    async def mock_verify_token():
        return {"user_id": "test_user_id", "username": "test_user"}
    
    # 直接替换模块中的verify_token
    from oculith.api import endpoints
    endpoints.verify_token = mock_verify_token
    
    yield
    
    # 恢复原始函数
    endpoints.verify_token = original_verify_token

@pytest.fixture(scope="session")
def temp_test_dir():
    """创建临时测试目录"""
    test_dir = tempfile.mkdtemp()
    yield test_dir
    # 测试结束后清理
    shutil.rmtree(test_dir)

@pytest.fixture(scope="session")
async def app(temp_test_dir):
    """创建测试用的FastAPI应用并手动触发生命周期事件"""
    app = FastAPI()
    # 挂载oculith API
    mount_docling_service(app, output_dir=temp_test_dir, allowed_formats=["docx", "pdf"])
    
    # 手动触发FastAPI的启动事件，确保所有组件都被初始化
    # 由于on_event已被弃用，我们直接获取所有startup事件处理程序并运行它们
    for handler in app.router.on_startup:
        if asyncio.iscoroutinefunction(handler):
            await handler()
        else:
            handler()
    
    # 在测试结束时运行清理
    yield app
    
    # 运行关闭事件处理程序
    for handler in app.router.on_shutdown:
        if asyncio.iscoroutinefunction(handler):
            await handler()
        else:
            handler()

@pytest_asyncio.fixture(scope="session")
async def test_client(app):
    """创建同步测试客户端"""
    with TestClient(app) as client:
        yield client

@pytest_asyncio.fixture
async def async_client(app):
    """创建异步测试客户端"""
    # 使用ASGI传输与FastAPI应用连接
    async with AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client

@pytest.fixture
def test_user():
    """创建测试用户信息"""
    return {"user_id": "test_user_id", "username": "test_user"}

@pytest.fixture
def auth_token():
    """测试令牌（由于验证被模拟，内容不重要）"""
    return "test-token"

@pytest.fixture
def auth_headers(auth_token):
    """创建包含认证令牌的请求头"""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
def test_docx_path():
    """提供测试用的demo.docx文件路径"""
    return Path(__file__).parent / "data" / "demo.docx"

@pytest.fixture(scope="function")
def event_loop():
    """确保所有测试共享同一个事件循环"""
    # 获取或创建全局事件循环
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # 记录循环ID，便于调试
    loop_id = id(loop)
    logger.info(f"测试使用事件循环: {loop_id}")
    
    yield loop
    
    # 关闭时不真正关闭循环，只是清理待处理任务
    pending = asyncio.all_tasks(loop)
    if pending:
        logger.warning(f"测试结束时有{len(pending)}个未完成任务")
        
        # 取消所有未完成任务
        for task in pending:
            task_name = task.get_name()
            # 此处修改：提供loop参数给current_task()，避免"no running event loop"错误
            current = None
            try:
                current = asyncio.current_task(loop)
            except RuntimeError:
                # 忽略"no running event loop"错误
                pass
            
            if not task.done() and task != current:
                logger.info(f"取消任务: {task_name}")
                task.cancel()
        
        # 简单等待短暂时间，让任务有机会完成取消操作
        # 不使用事件循环的run_until_complete，因为在teardown可能已不可用
        # 最多等待0.5秒
        end_time = time.time() + 0.5
        while time.time() < end_time:
            still_pending = [t for t in pending if not t.done()]
            if not still_pending:
                break
            time.sleep(0.05)  # 使用同步sleep

