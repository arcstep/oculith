#!/usr/bin/env python
"""
队列管理器诊断工具

用于检测和修复队列管理问题，包括：
1. 检查陷入停滞的任务
2. 重置卡住的文件锁
3. 清理长时间未完成的任务
4. 重启队列工作进程

使用方法:
python tools/queue_diagnostics.py [--reset] [--force]

参数:
--reset: 重置卡住的任务和锁
--force: 强制重启队列工作进程
"""

import os
import sys
import asyncio
import logging
import time
from pathlib import Path

# 添加项目根目录到系统路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("queue_diagnostics")

# 导入队列管理器
from src.oculith.core.queue_manager import QueueManager, TaskType, FileProcessStatus

async def diagnose_queue(reset: bool = False, force: bool = False):
    """诊断队列状态并可选择重置问题"""
    # 创建一个临时的队列管理器实例用于诊断
    logger.info("创建队列管理器实例...")
    queue_manager = QueueManager(max_concurrent_tasks=3)
    
    # 检查任务注册表文件
    tasks_dir = Path("./.db/tasks")
    if not tasks_dir.exists():
        logger.warning(f"任务注册表目录不存在: {tasks_dir}")
        return
    
    # 获取诊断信息
    diagnostics = await queue_manager.get_diagnostics()
    logger.info(f"队列状态: 运行={diagnostics['is_running']}, 队列大小={diagnostics['queue_size']}, " +
                f"活动任务={diagnostics['active_tasks_count']}")
    
    # 检查陷入停滞的任务
    stalled_tasks = []
    for task_id, file_task in queue_manager.task_registry.items():
        if file_task.status not in [FileProcessStatus.COMPLETED, FileProcessStatus.FAILED]:
            current_time = time.time()
            if file_task.started_at:
                # 根据任务类型确定合理超时阈值
                task_timeout = 300  # 默认5分钟
                if file_task.task_type == TaskType.CONVERT:
                    task_timeout = 3600  # 1小时
                elif file_task.task_type == TaskType.CHUNK:
                    task_timeout = 600   # 10分钟
                elif file_task.task_type == TaskType.INDEX:
                    task_timeout = 900   # 15分钟
                elif file_task.task_type == TaskType.PROCESS_ALL:
                    task_timeout = 7200  # 2小时
                
                task_runtime = current_time - file_task.started_at
                # 任务运行时间超过类型对应的阈值才视为停滞
                if task_runtime > task_timeout:
                    stalled_tasks.append(task_id)
                    runtime_minutes = task_runtime / 60
                    expected_minutes = task_timeout / 60
                    logger.warning(f"检测到潜在停滞任务: {task_id}, 类型: {file_task.task_type.value}, " 
                                 f"状态: {file_task.status.value}, 已运行: {runtime_minutes:.1f}分钟 "
                                 f"(预期阈值: {expected_minutes:.1f}分钟)")
            
            if reset:
                # 强制将任务标记为失败
                task = queue_manager.task_registry.get(task_id)
                if task:
                    task.status = FileProcessStatus.FAILED
                    task.error = "诊断工具自动取消"
                    task.completed_at = time.time()
                    logger.info(f"已重置任务状态: {task_id}")
    
    # 检查文件锁
    locked_files = []
    for file_key, is_locked in diagnostics.get("file_locks", {}).items():
        if is_locked:
            locked_files.append(file_key)
            logger.warning(f"文件已被锁定: {file_key}")
            
            if reset:
                # 重新创建锁对象以强制释放
                queue_manager.file_locks[file_key] = asyncio.Lock()
                logger.info(f"已重置文件锁: {file_key}")
    
    # 重启队列
    if force or (reset and (stalled_tasks or locked_files)):
        logger.info("准备重启队列工作进程...")
        # 停止当前工作进程
        await queue_manager.stop()
        # 启动新的工作进程
        await queue_manager.start()
        logger.info("队列工作进程已重启")

async def main():
    """主函数"""
    # 解析命令行参数
    reset = "--reset" in sys.argv
    force = "--force" in sys.argv
    
    # 运行诊断
    await diagnose_queue(reset=reset, force=force)
    
    logger.info("诊断完成")

if __name__ == "__main__":
    asyncio.run(main()) 