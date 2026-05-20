"""
聊天消息服务层
提供事务支持和业务逻辑封装
"""
import logging
from typing import Optional, List, Dict, Any

from .chat_message_dao import chat_message_dao
from .connection import db_manager
from .models import (
    ChatMessage,
    ChatMessageCreate,
)

logger = logging.getLogger(__name__)


class ChatMessageService:
    """聊天消息服务类"""

    def __init__(self):
        self.dao = chat_message_dao

    async def initialize(self) -> None:
        """初始化服务（初始化数据库连接池）"""
        await db_manager.initialize()
        logger.info("聊天消息服务初始化完成")

    async def create_chat_message(self, session_id: str, message_id: str, event: str,
                                  event_data: Dict[str, Any] = None) -> Optional[ChatMessage]:
        """
        创建聊天消息（如果已存在则忽略）
        
        Args:
            session_id: 会话ID
            message_id: 消息ID
            event: 事件类型
            event_data: 事件数据
            
        Returns:
            创建的消息对象
        """
        try:
            message_data = ChatMessageCreate(
                session_id=session_id,
                message_id=message_id,
                event=event,
                event_data=event_data or {}
            )
            message = await self.dao.create_message(message_data)
            if message:
                logger.info(f"成功创建聊天消息: {message.id}")
            return message

        except Exception as e:
            logger.error(f"创建聊天消息失败: {e}")
            raise

    async def upsert_chat_message(self, session_id: str, message_id: str, message_type: str, event: str,
                                  event_data: Dict[str, Any] = None) -> Optional[ChatMessage]:
        """
        插入或更新聊天消息
        
        Args:
            session_id: 会话ID
            message_id: 消息ID
            event: 事件类型
            event_data: 事件数据
            
        Returns:
            消息对象
        """
        try:
            message_data = ChatMessageCreate(
                session_id=session_id,
                message_id=message_id,
                event=event,
                message_type=message_type,
                event_data=event_data or {}
            )
            message = await self.dao.upsert_message(message_data)
            if message:
                logger.info(f"成功插入或更新聊天消息: {message.id}")
            return message

        except Exception as e:
            logger.error(f"插入或更新聊天消息失败: {e}")
            raise

    async def get_messages_by_session_id(self, session_id: str, limit: int = 100) -> List[ChatMessage]:
        """
        根据会话ID获取消息列表
        
        Args:
            session_id: 会话ID
            limit: 限制数量
            
        Returns:
            消息列表
        """
        try:
            return await self.dao.get_messages_by_session_id(session_id, limit)
        except Exception as e:
            logger.error(f"根据会话ID获取消息列表失败: {e}")
            raise

    async def close(self) -> None:
        """关闭服务"""
        await db_manager.close()
        logger.info("聊天消息服务已关闭")


# 全局服务实例
chat_message_service = ChatMessageService()
