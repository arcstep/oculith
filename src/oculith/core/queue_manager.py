"""任务队列管理器

提供简单的异步文件处理任务队列管理，支持以下功能：
1. 添加文件处理任务到队列
2. 按优先级处理任务
3. 限制并发处理数量
4. 提供任务状态查询
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Union, Callable, Awaitable
from enum import Enum
import traceback

from .schemas import FileProcessStatus

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型枚举"""
    CONVERT = "convert"  # 文档转换
    CHUNK = "chunk"      # 文档切片
    INDEX = "index"      # 向量索引
    PROCESS_ALL = "process_all"  # 完整处理流程


class FileTask:
    """文件处理任务"""
    def __init__(
        self,
        user_id: str,
        file_id: str,
        task_type: TaskType,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.user_id = user_id
        self.file_id = file_id
        self.task_id = f"{user_id}_{file_id}_{task_type.value}_{int(time.time())}"
        self.task_type = task_type
        self.priority = priority
        self.metadata = metadata or {}
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.status = FileProcessStatus.QUEUED
        self.error: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """将任务转换为字典"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "file_id": self.file_id,
            "task_type": self.task_type.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status.value,
            "error": self.error,
            "metadata": self.metadata
        }


class QueueManager:
    """任务队列管理器"""
    def __init__(self, max_concurrent_tasks: int = 3):
        self.task_queue = asyncio.PriorityQueue()  # 优先级队列
        self.active_tasks: Dict[str, asyncio.Task] = {}  # 正在执行的任务
        self.task_registry: Dict[str, FileTask] = {}  # 任务注册表，包括历史任务
        self.max_concurrent_tasks = max_concurrent_tasks
        self.is_running = False
        self.worker_task = None
        self.file_locks: Dict[str, asyncio.Lock] = {}  # 文件锁
        self._processors = {}  # 任务处理器字典
    
    async def start(self):
        """启动队列处理"""
        # 检查任务状态 - 如果已取消或已完成，重置标志
        if self.worker_task and (self.worker_task.done() or self.worker_task.cancelled()):
            self.is_running = False
            self.worker_task = None
            logger.info("检测到工作进程已取消或完成，重置状态")
        
        if self.is_running:
            logger.warning("任务队列管理器已经在运行中，不需要重复启动")
            return
        
        self.is_running = True
        # 验证事件循环
        try:
            loop = asyncio.get_running_loop()
            logger.info(f"启动队列管理器，使用事件循环: {id(loop)}")
        except RuntimeError:
            logger.error("启动队列管理器失败：无法获取运行中的事件循环")
            self.is_running = False
            return
        
        # 检验处理器
        logger.info(f"已注册的处理器: {[t.value for t in self._processors.keys()]}")
        
        self.worker_task = asyncio.create_task(self._worker())
        logger.info(f"任务队列管理器已启动，worker_task ID: {id(self.worker_task)}")
    
    async def stop(self):
        """停止队列处理"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.worker_task:
            # 取消任务
            self.worker_task.cancel()
            try:
                # 增加超时和错误处理
                await asyncio.wait_for(asyncio.shield(self.worker_task), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError, RuntimeError):
                # 忽略超时、取消和事件循环错误
                pass
            self.worker_task = None
        logger.info("任务队列管理器已停止")
    
    async def add_task(self, task: FileTask) -> str:
        """添加任务到队列"""
        # 增加诊断日志
        logger.info(f"准备添加任务: {task.task_id}, 类型: {task.task_type.value}")
        
        # 检查队列状态
        queue_size = self.task_queue.qsize()
        logger.info(f"当前队列状态: 大小={queue_size}, 活动任务={len(self.active_tasks)}")
        
        # 检查处理器是否已注册
        if task.task_type not in self._processors:
            logger.error(f"警告: 任务类型 {task.task_type.value} 的处理器尚未注册")
        
        # 检查是否已有相同任务在队列中
        for existing_task_id, existing_task in self.task_registry.items():
            if (existing_task.user_id == task.user_id and 
                existing_task.file_id == task.file_id and 
                existing_task.task_type == task.task_type and
                existing_task.status == FileProcessStatus.QUEUED):
                logger.info(f"相同任务已在队列中: {existing_task_id}")
                return existing_task_id
        
        # 添加任务到注册表
        self.task_registry[task.task_id] = task
        
        # 添加任务到队列，按优先级排序
        try:
            await self.task_queue.put((-task.priority, task.created_at, task.task_id))
            logger.info(f"已成功添加任务到队列: {task.task_id}, 优先级: {task.priority}")
            
            # 再次检查队列状态
            new_queue_size = self.task_queue.qsize()
            logger.info(f"添加后队列状态: 大小={new_queue_size}, 活动任务={len(self.active_tasks)}")
            
            # 检查worker是否运行
            if self.worker_task is None or self.worker_task.done():
                logger.error(f"警告: worker任务不在运行状态! 状态: {self.worker_task and self.worker_task.done()}")
        except Exception as e:
            logger.error(f"添加任务到队列时异常: {str(e)}")
            raise
        
        return task.task_id
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task = self.task_registry.get(task_id)
        if not task:
            return None
        return task.to_dict()
    
    async def get_file_tasks(self, user_id: str, file_id: str) -> List[Dict[str, Any]]:
        """获取文件相关的所有任务"""
        tasks = []
        for task in self.task_registry.values():
            if task.user_id == user_id and task.file_id == file_id:
                tasks.append(task.to_dict())
        return tasks
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        # 如果任务在活动任务中，取消执行
        if task_id in self.active_tasks:
            self.active_tasks[task_id].cancel()
            logger.info(f"已取消正在执行的任务: {task_id}")
            
            # 更新任务状态
            task = self.task_registry.get(task_id)
            if task:
                task.status = FileProcessStatus.FAILED
                task.error = "用户取消任务"
                task.completed_at = time.time()
                return True
        
        # 如果任务在队列中但尚未执行，则从注册表中更新状态
        task = self.task_registry.get(task_id)
        if task and task.status == FileProcessStatus.QUEUED:
            task.status = FileProcessStatus.FAILED
            task.error = "用户取消任务"
            task.completed_at = time.time()
            logger.info(f"已取消排队中的任务: {task_id}")
            return True
        
        return False
    
    async def get_file_status(self, user_id: str, file_id: str) -> Dict[str, Any]:
        """获取文件当前处理状态"""
        # 查找与文件相关的最近任务
        latest_task = None
        latest_time = 0
        
        for task in self.task_registry.values():
            if task.user_id == user_id and task.file_id == file_id:
                if task.created_at > latest_time:
                    latest_task = task
                    latest_time = task.created_at
        
        if not latest_task:
            return {
                "file_id": file_id,
                "status": FileProcessStatus.UPLOADED.value,
                "message": "文件已上传，尚未处理"
            }
        
        # 返回最近任务的状态
        return {
            "file_id": file_id,
            "status": latest_task.status.value,
            "task_id": latest_task.task_id,
            "task_type": latest_task.task_type.value,
            "created_at": latest_task.created_at,
            "started_at": latest_task.started_at,
            "completed_at": latest_task.completed_at,
            "error": latest_task.error
        }
    
    async def register_processor(
        self, 
        task_type: TaskType, 
        processor: Callable[[FileTask], Awaitable[Dict[str, Any]]]
    ) -> None:
        """注册任务处理器"""
        logger.info(f"注册处理器: {task_type.value}")
        
        # 保存处理器并验证
        self._processors[task_type] = processor
        
        # 验证是否成功注册
        if task_type in self._processors:
            logger.info(f"处理器注册成功: {task_type.value}")
        else:
            logger.error(f"处理器注册失败: {task_type.value}")
    
    async def _worker(self):
        """任务队列工作进程"""
        # 记录启动信息和事件循环ID，便于调试
        worker_loop = asyncio.get_running_loop()
        loop_id = id(worker_loop)
        logger.info(f"任务队列工作进程启动，循环ID={loop_id}，最大并发任务={self.max_concurrent_tasks}")
        
        worker_cycle = 0
        last_active_time = time.time()
        
        while self.is_running:
            worker_cycle += 1
            current_time = time.time()
            
            # 打印工作循环状态
            if worker_cycle % 10 == 1 or current_time - last_active_time > 5:
                # logger.info(f"工作进程循环 #{worker_cycle}, 上次活动: {current_time - last_active_time:.1f}秒前")
                last_active_time = current_time
            
            try:
                # 使用非阻塞方式检查队列
                if self.task_queue.empty():
                    if worker_cycle % 20 == 1:
                        logger.debug("任务队列为空，等待...")
                    await asyncio.sleep(0.2)
                    continue
                
                # 检查当前活跃任务数是否已达到最大限制
                current_active_tasks = len(self.active_tasks)
                if current_active_tasks >= self.max_concurrent_tasks:
                    # 已达到最大并发限制，暂停获取新任务
                    if worker_cycle % 10 == 1:
                        logger.info(f"当前活跃任务数({current_active_tasks})已达到最大限制({self.max_concurrent_tasks})，暂停获取新任务")
                    await asyncio.sleep(0.5)  # 等待一段时间再检查
                    continue
                
                # 非空队列，尝试获取任务
                queue_size = self.task_queue.qsize()
                if worker_cycle % 10 == 1:
                    logger.info(f"检测到队列中有{queue_size}个任务，当前活跃任务数: {current_active_tasks}/{self.max_concurrent_tasks}")
                
                # ！！！关键修改：使用get_nowait()和异常处理替代阻塞式get()！！！
                try:
                    # 首先尝试非阻塞获取
                    try:
                        priority, created_at, task_id = self.task_queue.get_nowait()
                        logger.info(f"成功从队列获取任务: {task_id}, 优先级: {-priority}")
                    except asyncio.QueueEmpty:
                        # 队列暂时为空，可能是并发访问导致的
                        if queue_size > 0:
                            logger.warning(f"队列报告有{queue_size}个任务，但获取失败")
                        await asyncio.sleep(0.2)
                        continue
                    
                    # 获取到任务，处理它
                    task = self.task_registry.get(task_id)
                    if not task:
                        logger.warning(f"任务未在注册表中找到: {task_id}")
                        self.task_queue.task_done()
                        continue
                    
                    # 更详细记录任务信息
                    logger.info(f"获取到任务详情: ID={task_id}, 类型={task.task_type.value}")
                    
                    # 检查处理器是否存在
                    if task.task_type not in self._processors:
                        logger.error(f"处理器未注册: {task.task_type.value}, 可用处理器: {[t.value for t in self._processors.keys()]}")
                        task.status = FileProcessStatus.FAILED
                        task.error = f"处理器未注册: {task.task_type.value}"
                        task.completed_at = time.time()
                        # 标记任务完成
                        self.task_queue.task_done()
                        continue
                    
                    # 检查文件锁
                    file_key = f"{task.user_id}_{task.file_id}"
                    if file_key not in self.file_locks:
                        self.file_locks[file_key] = asyncio.Lock()
                        logger.debug(f"为文件创建新锁: {file_key}")
                    
                    # 如果文件已被锁定，将任务重新加入队列
                    if self.file_locks[file_key].locked():
                        logger.info(f"文件已被锁定，任务重新入队: {task_id}")
                        await self.task_queue.put((priority, created_at, task_id))
                        # 标记当前任务完成
                        self.task_queue.task_done()
                        await asyncio.sleep(0.5)  # 避免立即重试
                        continue
                    
                    # 更新任务状态
                    task.started_at = time.time()
                    queued_time = task.started_at - task.created_at
                    logger.info(f"开始处理任务: {task_id}, 队列等待时间: {queued_time:.2f}秒")
                    
                    # 根据任务类型设置状态
                    if task.task_type == TaskType.CONVERT:
                        task.status = FileProcessStatus.CONVERTING
                    elif task.task_type == TaskType.CHUNK:
                        task.status = FileProcessStatus.CHUNKING
                    elif task.task_type == TaskType.INDEX:
                        task.status = FileProcessStatus.INDEXING
                    elif task.task_type == TaskType.PROCESS_ALL:
                        task.status = FileProcessStatus.CONVERTING
                    
                    # 创建任务处理协程
                    logger.info(f"创建任务处理协程: {task_id}")
                    try:
                        process_task = asyncio.create_task(
                            self._process_task(task)
                        )
                        process_task.add_done_callback(
                            lambda _: logger.info(f"任务处理完成回调: {task_id}")
                        )
                        
                        # 添加到活动任务
                        self.active_tasks[task_id] = process_task
                        logger.info(f"已添加任务到活动任务列表: {task_id}, 当前活动任务数: {len(self.active_tasks)}/{self.max_concurrent_tasks}")
                        
                        # 标记队列任务完成
                        self.task_queue.task_done()
                    except Exception as e:
                        logger.error(f"创建任务处理协程异常: {str(e)}")
                        # 重新加入队列
                        await self.task_queue.put((priority, created_at, task_id))
                        # 标记当前任务完成
                        self.task_queue.task_done()
                except Exception as e:
                    logger.error(f"任务获取或处理异常: {str(e)}")
                    logger.error(traceback.format_exc())
                    await asyncio.sleep(0.5)
                
            except asyncio.CancelledError:
                logger.info("工作进程被取消")
                break
            except Exception as e:
                logger.error(f"工作进程循环异常: {str(e)}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(0.5)  # 出错后短暂暂停
    
    async def _process_task(self, task: FileTask) -> None:
        """处理任务"""
        file_key = f"{task.user_id}_{task.file_id}"
        
        logger.info(f"准备获取文件锁并处理任务: {task.task_id}")
        
        # 获取文件锁
        try:
            # 检查锁状态
            lock = self.file_locks.get(file_key)
            if not lock:
                logger.error(f"错误: 文件锁不存在: {file_key}")
                lock = asyncio.Lock()
                self.file_locks[file_key] = lock
            
            logger.info(f"开始尝试获取文件锁: {file_key}, 锁状态: {'已锁定' if lock.locked() else '未锁定'}")
            
            # 标记任务完成函数，确保在各种情况下都会被调用
            def complete_task(success: bool, error_msg: Optional[str] = None):
                if error_msg:
                    task.status = FileProcessStatus.FAILED
                    task.error = error_msg
                    logger.error(f"任务失败: {task.task_id}, 错误: {error_msg}")
                elif not success:
                    task.status = FileProcessStatus.FAILED
                    task.error = "处理失败，未提供详细错误信息"
                    logger.error(f"任务失败: {task.task_id}, 未提供详细错误")
                
                # 设置完成时间（如果尚未设置）
                if not task.completed_at:
                    task.completed_at = time.time()
                
                # 从活动任务中移除
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]
                    logger.info(f"已从活动任务中移除: {task.task_id}")
            
            # 根据任务类型确定处理超时时间
            # OCR和处理复杂文档可能需要更长时间
            execution_timeout = 1800  # 默认30分钟
            if task.task_type == TaskType.CONVERT:
                # 复杂文档转换可能会耗时更长，特别是包含OCR的情况
                execution_timeout = 3600  # 1小时
            elif task.task_type == TaskType.CHUNK:
                # 切片一般较快
                execution_timeout = 300   # 5分钟
            elif task.task_type == TaskType.INDEX:
                # 索引中等耗时
                execution_timeout = 600   # 10分钟
            elif task.task_type == TaskType.PROCESS_ALL:
                # 全流程处理，可能包含OCR等耗时操作
                execution_timeout = 7200  # 2小时
            
            # 为复杂任务记录预期执行时间
            if execution_timeout > 600:
                logger.info(f"任务 {task.task_id} 预期执行时间较长: {execution_timeout/60:.1f}分钟")
            
            # 尝试获取锁，增加超时
            try:
                acquired = False
                # 获取锁的超时设置为2分钟 - 单独设置，与任务执行时间区分
                async with asyncio.timeout(120):  # 锁获取超时2分钟
                    async with lock:
                        acquired = True
                        logger.info(f"已获取文件锁，开始处理任务: {task.task_id}")
                        
                        # 检查是否有对应的处理器
                        processor = self._processors.get(task.task_type)
                        if not processor:
                            logger.error(f"未找到任务类型的处理器: {task.task_type.value}, 可用处理器: {[t.value for t in self._processors.keys()]}")
                            complete_task(False, f"未找到任务类型的处理器: {task.task_type.value}")
                            return
                        
                        # 执行处理器，使用任务类型对应的超时时间
                        logger.info(f"开始执行处理器: {task.task_type.value}, 任务ID: {task.task_id}, 超时设置: {execution_timeout}秒")
                        try:
                            # 使用单独的超时设置执行任务处理
                            async with asyncio.timeout(execution_timeout):
                                result = await processor(task)
                                logger.info(f"处理器执行完成: {task.task_id}, 结果: {result.get('success', False)}")
                        except asyncio.TimeoutError:
                            logger.error(f"任务处理超时: {task.task_id}, 设置的超时时间: {execution_timeout}秒")
                            complete_task(False, f"任务处理超时（超过{execution_timeout/60:.1f}分钟）")
                            return
                        except Exception as proc_e:
                            logger.error(f"处理器执行异常: {task.task_id}, 错误: {str(proc_e)}")
                            logger.error(traceback.format_exc())
                            complete_task(False, f"处理器执行异常: {str(proc_e)}")
                            return
                        
                        # 更新任务状态
                        task.result = result
                        task.completed_at = time.time()
                        
                        # 根据处理结果设置状态
                        if result.get("success", False):
                            if task.task_type == TaskType.CONVERT:
                                task.status = FileProcessStatus.CONVERTED
                            elif task.task_type == TaskType.CHUNK:
                                task.status = FileProcessStatus.CHUNKED
                            elif task.task_type == TaskType.INDEX:
                                task.status = FileProcessStatus.COMPLETED
                            elif task.task_type == TaskType.PROCESS_ALL:
                                task.status = FileProcessStatus.COMPLETED
                            complete_task(True)
                        else:
                            error_msg = result.get("error", "处理失败，未提供详细错误信息")
                            complete_task(False, error_msg)
                        
                        logger.info(f"任务处理完成: {task.task_id}, 状态: {task.status.value}")
                
                if not acquired:
                    complete_task(False, "无法获取文件锁，处理超时")
                    
            except asyncio.TimeoutError:
                logger.error(f"获取文件锁超时: {file_key}, 任务: {task.task_id}")
                complete_task(False, "获取文件锁超时（2分钟）")
                
        except asyncio.CancelledError:
            logger.info(f"任务被取消: {task.task_id}")
            complete_task(False, "任务被取消")
        except Exception as e:
            logger.error(f"任务处理异常: {task.task_id}, 错误: {str(e)}")
            logger.error(traceback.format_exc())
            complete_task(False, f"处理异常: {str(e)}")
        finally:
            # 确保任务从活动任务列表中移除，即使出现未捕获的异常
            if task.task_id in self.active_tasks:
                del self.active_tasks[task.task_id]
                logger.info(f"在finally块中确保任务从活动任务中移除: {task.task_id}")
    
    async def get_diagnostics(self) -> Dict[str, Any]:
        """获取队列管理器诊断信息"""
        # 计算各种状态任务的数量
        status_counts = {}
        for task in self.task_registry.values():
            status = task.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # 获取活动任务信息
        active_tasks = []
        for task_id, task in self.active_tasks.items():
            task_status = "running"
            if task.done():
                task_status = "done"
            elif task.cancelled():
                task_status = "cancelled"
            
            active_tasks.append({
                "task_id": task_id,
                "status": task_status,
                "task_obj": str(task)
            })
        
        # 获取文件锁状态
        file_locks = {}
        for file_key, lock in self.file_locks.items():
            file_locks[file_key] = lock.locked()
        
        return {
            "is_running": self.is_running,
            "worker_task_status": self.worker_task and (
                "running" if not self.worker_task.done() else "done"
            ),
            "queue_size": self.task_queue.qsize(),
            "active_tasks_count": len(self.active_tasks),
            "task_registry_count": len(self.task_registry),
            "status_counts": status_counts,
            "active_tasks": active_tasks,
            "file_locks": file_locks
        }
    
    async def check_stalled_tasks(self) -> List[str]:
        """检查可能陷入停滞的任务
        
        根据任务类型确定合理的超时阈值，避免误报
        """
        stalled_tasks = []
        current_time = time.time()
        
        # 检查长时间未完成的活动任务
        for task_id, file_task in self.task_registry.items():
            if file_task.status not in [FileProcessStatus.COMPLETED, FileProcessStatus.FAILED]:
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
                
                if file_task.started_at and (current_time - file_task.started_at > task_timeout):
                    stalled_tasks.append(task_id)
                    runtime_minutes = (current_time - file_task.started_at) / 60
                    expected_minutes = task_timeout / 60
                    logger.warning(
                        f"检测到停滞任务: {task_id}, 类型: {file_task.task_type.value}, " 
                        f"状态: {file_task.status.value}, 已运行: {runtime_minutes:.1f}分钟 "
                        f"(预期: {expected_minutes:.1f}分钟)"
                    )
                # 检查排队但长时间未开始的任务
                elif file_task.status == FileProcessStatus.QUEUED and (current_time - file_task.created_at > 3600):
                    stalled_tasks.append(task_id)
                    queue_minutes = (current_time - file_task.created_at) / 60
                    logger.warning(
                        f"检测到长时间排队任务: {task_id}, 类型: {file_task.task_type.value}, "
                        f"已排队: {queue_minutes:.1f}分钟"
                    )
        
        return stalled_tasks 