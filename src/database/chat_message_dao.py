"""
聊天消息数据访问对象(DAO)
提供chat_message表的CRUD操作
"""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from .connection import db_manager
from .models import (
    ChatMessage,
    ChatMessageCreate,
)

logger = logging.getLogger(__name__)


class ChatMessageDAO:
    """聊天消息数据访问对象"""

    def __init__(self):
        self.table_name = "chat_message"
        self.columns = [
            "id", "session_id", "message_id", "event",
            "event_data", "message_type", "create_time", "update_time"
        ]

    async def create_message(self, message_data: ChatMessageCreate) -> Optional[ChatMessage]:
        """
        创建新的聊天消息（使用 INSERT IGNORE 避免重复）
        
        Args:
            message_data: 创建消息的数据
            
        Returns:
            创建成功的消息对象，失败返回None
        """
        try:
            now = datetime.now()
            event_data_json = json.dumps(message_data.event_data,
                                         ensure_ascii=False) if message_data.event_data else None

            # 使用 INSERT IGNORE 避免唯一索引冲突
            sql = f"""
            INSERT IGNORE INTO {self.table_name} 
            (session_id, message_id, event, event_data, message_type, create_time, update_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            params = (
                message_data.session_id,
                message_data.message_id,
                message_data.event,
                event_data_json,
                message_data.message_type,
                now,
                now
            )

            async with db_manager.transaction() as conn:
                async with db_manager.get_cursor(conn) as cursor:
                    await cursor.execute(sql, params)
                    message_id = cursor.lastrowid

                    # 如果 lastrowid 为 0，说明是重复插入，尝试获取现有记录
                    if message_id == 0:
                        existing_message = await self.get_message_by_session_message_event(
                            message_data.session_id,
                            message_data.message_id,
                            message_data.event
                        )
                        if existing_message:
                            logger.info(
                                f"聊天消息已存在，返回现有记录: session_id={message_data.session_id}, message_id={message_data.message_id}, event={message_data.event}")
                            return existing_message

            if message_id > 0:
                logger.info(f"成功创建聊天消息，ID: {message_id}")
                return await self.get_message_by_id(message_id)
            else:
                logger.warning(
                    f"聊天消息可能已存在: session_id={message_data.session_id}, message_id={message_data.message_id}, event={message_data.event}")
                return None

        except Exception as e:
            logger.error(f"创建聊天消息失败: {e}")
            raise

    async def upsert_message(self, message_data: ChatMessageCreate) -> Optional[ChatMessage]:
        """
        插入或更新聊天消息（如果存在则更新）
        
        Args:
            message_data: 消息数据
            
        Returns:
            消息对象
        """
        try:
            now = datetime.now()
            event_data_json = json.dumps(message_data.event_data,
                                         ensure_ascii=False) if message_data.event_data else None

            # 使用 ON DUPLICATE KEY UPDATE 实现 upsert
            sql = f"""
            INSERT INTO {self.table_name} 
            (session_id, message_id, event, event_data, message_type, create_time, update_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                event_data = VALUES(event_data),
                message_type = VALUES(message_type),
                update_time = VALUES(update_time)
            """

            params = (
                message_data.session_id,
                message_data.message_id,
                message_data.event,
                event_data_json,
                message_data.message_type,
                now,
                now
            )

            async with db_manager.transaction() as conn:
                async with db_manager.get_cursor(conn) as cursor:
                    await cursor.execute(sql, params)
                    # 获取受影响的行数来判断是插入还是更新
                    affected_rows = cursor.rowcount

            if affected_rows > 0:
                action = "更新" if affected_rows == 2 else "创建"
                logger.info(
                    f"成功{action}聊天消息: session_id={message_data.session_id}, message_id={message_data.message_id}, event={message_data.event}")

                # 返回消息对象
                return await self.get_message_by_session_message_event(
                    message_data.session_id,
                    message_data.message_id,
                    message_data.event
                )
            else:
                logger.warning(
                    f"聊天消息操作失败: session_id={message_data.session_id}, message_id={message_data.message_id}, event={message_data.event}")
                return None

        except Exception as e:
            logger.error(f"插入或更新聊天消息失败: {e}")
            raise

    async def get_message_by_id(self, message_id: int) -> Optional[ChatMessage]:
        """根据ID查询单个消息"""
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE id = %s
            """

            row = await db_manager.execute_with_retry(sql, (message_id,), fetch_type="one")

            if row:
                message = ChatMessage.from_db_row(row)
                logger.info(f"成功获取聊天消息，ID: {message_id}")
                return message
            else:
                logger.warning(f"聊天消息不存在，ID: {message_id}")
                return None

        except Exception as e:
            logger.error(f"根据ID查询聊天消息失败: {e}")
            raise

    async def get_messages_by_session_id(self, session_id: str, limit: int = 100) -> List[ChatMessage]:
        """根据会话ID查询消息列表"""
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE session_id = %s
            ORDER BY create_time ASC
            LIMIT %s
            """

            rows = await db_manager.execute_with_retry(sql, (session_id, limit), fetch_type="all")

            messages = [ChatMessage.from_db_row(row) for row in rows] if rows else []

            logger.info(f"根据会话ID查询返回 {len(messages)} 条消息")
            return messages

        except Exception as e:
            logger.error(f"根据会话ID查询消息失败: {e}")
            raise

    async def get_message_by_session_message_event(self, session_id: str, message_id: str, event: str) -> Optional[
        ChatMessage]:
        """根据会话ID、消息ID和事件类型查询消息"""
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE session_id = %s AND message_id = %s AND event = %s
            """

            row = await db_manager.execute_with_retry(sql, (session_id, message_id, event), fetch_type="one")

            if row:
                message = ChatMessage.from_db_row(row)
                logger.info(f"成功获取聊天消息: session_id={session_id}, message_id={message_id}, event={event}")
                return message
            else:
                logger.warning(f"聊天消息不存在: session_id={session_id}, message_id={message_id}, event={event}")
                return None

        except Exception as e:
            logger.error(f"根据会话ID、消息ID和事件查询消息失败: {e}")
            raise

    async def update_message(self, session_id: str, message_id: str, event: str, event_data: Dict[str, Any]) -> \
            Optional[ChatMessage]:
        """更新聊天消息的事件数据"""
        try:
            now = datetime.now()
            event_data_json = json.dumps(event_data, ensure_ascii=False) if event_data else None

            sql = f"""
            UPDATE {self.table_name} 
            SET event_data = %s, update_time = %s
            WHERE session_id = %s AND message_id = %s AND event = %s
            """

            params = (event_data_json, now, session_id, message_id, event)

            async with db_manager.transaction() as conn:
                rows_affected = await db_manager.execute_with_retry(sql, params, connection=conn)

            if rows_affected > 0:
                logger.info(f"成功更新聊天消息: session_id={session_id}, message_id={message_id}, event={event}")
                return await self.get_message_by_session_message_event(session_id, message_id, event)
            else:
                logger.warning(
                    f"聊天消息不存在或未更新: session_id={session_id}, message_id={message_id}, event={event}")
                return None

        except Exception as e:
            logger.error(f"更新聊天消息失败: {e}")
            raise


# 全局DAO实例
chat_message_dao = ChatMessageDAO()
