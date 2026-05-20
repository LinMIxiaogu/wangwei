"""
事件队列管理模块
"""
import asyncio
import json
import logging
import traceback
import uuid
from typing import AsyncGenerator
from typing import Optional, Dict

from src.database.chat_message_service import chat_message_service
from ..state.types import State

logger = logging.getLogger("event-manager")


class EventQueueManager:
    """管理 SSE 事件推送队列"""

    def __init__(self):
        self.queues: Dict[str, asyncio.Queue] = {}
        self.workflow = None

    def create_queue(self, session_id: str) -> asyncio.Queue:
        """为会话创建事件队列"""
        queue = asyncio.Queue()
        self.queues[session_id] = queue
        logger.info(f"Session:{session_id} create event queue")
        return queue

    def get_queue(self, session_id: str) -> Optional[asyncio.Queue]:
        """获取指定会话的队列"""
        return self.queues.get(session_id)

    def cleanup(self, session_id: str):
        """清理会话队列"""
        if session_id in self.queues:
            self.queues.pop(session_id)
            logger.info(f"Session:{session_id} cleanup event queue")

    @property
    def active_sessions_count(self) -> int:
        """获取活跃会话数量"""
        return len(self.queues)

    async def send_event(self, state: dict, event: str = None, data: dict = None) -> bool:
        """向指定会话发送事件"""
        data["session_id"] = state.get("session_id")
        event_data = {
            "event": event,
            "data": data
        }
        session_id = state.get("session_id")
        if session_id is None:
            logger.error("No session_id found in state")
            return False

        # 保存聊天消息到数据库
        try:
            message_id = data.get("message_id") or state.get("message_id")
            if message_id and event:
                await chat_message_service.upsert_chat_message(
                    session_id=session_id,
                    message_id=message_id,
                    message_type="AI",
                    event=event,
                    event_data=data
                )
                logger.info(f"保存聊天消息到数据库: session_id={session_id}, message_id={message_id}, event={event}")
        except Exception as e:
            logger.error(f"保存聊天消息到数据库失败: {e}")
            # 不影响事件发送，继续执行

        queue = self.get_queue(session_id)
        if queue:
            try:
                queue.put_nowait(event_data)
                # 让出CPU时间，允许队列中的内容被处理
                # 使用极短的时间间隔，既能让出CPU又不会明显影响性能
                await asyncio.sleep(0.001)
                return True
            except Exception as e:
                logger.exception(f"EventQueueManager_send_event_error")
                return False
        else:
            logger.warning(f"Session:{session_id} not found")
            return False

    async def event_generator(self, state: State) -> AsyncGenerator[str, None]:
        """
        事件生成器 - 从队列中读取事件并推送

        Args:
            state (State): 包含会话ID的状态对象

        Returns:
            AsyncGenerator[str, None]: 异步事件生成器

        Yields:
            Iterator[AsyncGenerator[str, None]]: 事件字符串
        """
        session_id = state.get("session_id")
        if session_id is None:
            logger.error("No session_id found in state")
            return
        try:
            message_id = str(uuid.uuid4())
            state["message_id"] = message_id
            # 创建事件队列
            event_queue = self.create_queue(session_id)
            # 启动工作流（在后台运行）
            workflow_task = asyncio.create_task(
                self.run_workflow(state)
            )
            # 持续从队列读取事件并推送
            while True:
                try:
                    # 等待队列消息（超时避免无限阻塞）
                    event_data = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                    # 将字典格式的事件转换为 SSE 格式
                    yield f"event:{event_data['event']}\ndata: {json.dumps(event_data['data'], ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 检查工作流是否已完成
                    if workflow_task.done():
                        # 确保所有消息都已发送
                        if event_queue.empty():
                            await event_manager.send_event(state=state, event="done", data={"message": "工作流已完成"})
                            break

        except Exception as e:
            logger.exception(f"EventQueueManager_event_generator_error")
            await event_manager.send_event(state=state, event="error",
                                           data={"error": str(e), "traceback": traceback.format_exc()})
        finally:
            # 清理资源
            self.cleanup(session_id)

    async def run_workflow(self, state: State):
        """在后台执行工作流并推送事件"""
        try:
            # 延迟导入避免循环导入
            if self.workflow is None:
                from ..graph_builder import create_workflow
                self.workflow = create_workflow()
            config = {}
            # 执行工作流
            await self.workflow.ainvoke(state, config=config)

            # 更新视频工作流记录状态为成功
            try:
                session_id = state.get("session_id")
                if session_id:
                    # 延迟导入避免循环导入
                    from ...database import video_workflow_service
                    from ...database.models import VideoWorkflowStatus, VideoWorkflowRecordQuery

                    # 查找对应的工作流记录并更新状态
                    query_params = VideoWorkflowRecordQuery(
                        session_id=session_id,
                        limit=1
                    )
                    records, _ = await video_workflow_service.query_workflow_records(query_params)

                    if records:
                        record = records[0]
                        # 更新状态为SUCCESS
                        await video_workflow_service.update_workflow_status(
                            record.id,
                            VideoWorkflowStatus.SUCCESS
                        )
                        logger.info(
                            f"视频工作流记录状态已更新为SUCCESS: session_id={session_id}, record_id={record.id}")
                    else:
                        logger.warning(f"未找到对应的工作流记录: session_id={session_id}")
            except Exception as e:
                logger.error(f"更新视频工作流记录状态失败: {e}")

            # 发送完成信号
            await self.send_event(state=state, event="done", data={"message": "对话完成"})
        except Exception as e:
            logger.exception(f"EventQueueManager_run_workflow_error")

            # 更新视频工作流记录状态为失败（这里暂时不处理失败状态，因为新的状态常量中没有FAILED）
            try:
                session_id = state.get("session_id")
                if session_id:
                    logger.info(f"工作流执行失败: session_id={session_id}")
                    # 注意：新的状态常量中没有FAILED状态，保持当前状态不变
            except Exception as update_error:
                logger.error(f"处理工作流失败状态时出错: {update_error}")

            # 发送错误信号
            await self.send_event(state=state, event="error",
                                  data={"error": str(e), "traceback": traceback.format_exc()})


# 全局事件管理器实例
event_manager = EventQueueManager()
