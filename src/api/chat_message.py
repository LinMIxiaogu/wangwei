"""
聊天消息相关API接口
"""
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.database.chat_message_dao import chat_message_dao
from src.database.models import ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessageResponse(BaseModel):
    """聊天消息响应模型"""
    id: Optional[int]
    session_id: str
    message_id: str
    event: str
    event_data: Optional[Dict[str, Any]]
    create_time: Optional[str]
    update_time: Optional[str]
    message_type: Optional[str]

    @classmethod
    def from_message(cls, message: ChatMessage) -> 'ChatMessageResponse':
        """从数据库消息对象创建响应对象"""
        return cls(
            id=message.id,
            session_id=message.session_id,
            message_id=message.message_id,
            message_type=message.message_type,
            event=message.event,
            event_data=message.event_data,
            create_time=message.create_time.isoformat() if message.create_time else None,
            update_time=message.update_time.isoformat() if message.update_time else None
        )


class ChatMessagesListResponse(BaseModel):
    """聊天消息列表响应模型"""
    success: bool
    message: str
    data: Dict[str, Any] = None


@router.get("/session/{session_id}", response_model=ChatMessagesListResponse)
async def get_messages_by_session_id(
        session_id: str,
        limit: int = Query(100, ge=1, le=1000, description="每页记录数，范围1-1000")
):
    """
    根据会话ID查询所有聊天消息
    
    Args:
        session_id: 会话ID
        limit: 每页记录数，默认100，范围1-1000
        
    Returns:
        ChatMessagesListResponse: 包含消息列表的响应
    """
    try:
        # 查询消息
        messages = await chat_message_dao.get_messages_by_session_id(session_id, limit)

        if not messages:
            return ChatMessagesListResponse(
                success=True,
                message=f"会话 {session_id} 暂无消息记录",
                data={
                    "session_id": session_id,
                    "total_count": 0,
                    "messages": []
                }
            )

        # 转换为响应格式
        message_list = [ChatMessageResponse.from_message(msg) for msg in messages]

        response_data = {
            "session_id": session_id,
            "total_count": len(messages),
            "limit": limit,
            "messages": [msg.dict() for msg in message_list]
        }

        return ChatMessagesListResponse(
            success=True,
            message=f"成功查询到会话 {session_id} 的 {len(messages)} 条消息",
            data=response_data
        )

    except Exception as e:
        logger.error(f"根据会话ID查询消息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/session/{session_id}/events/{event}", response_model=ChatMessagesListResponse)
async def get_messages_by_session_and_event(
        session_id: str,
        event: str,
        limit: int = Query(100, ge=1, le=1000, description="每页记录数，范围1-1000")
):
    """
    根据会话ID和事件类型查询聊天消息
    
    Args:
        session_id: 会话ID
        event: 事件类型
        limit: 每页记录数，默认100，范围1-1000
        
    Returns:
        ChatMessagesListResponse: 包含消息列表的响应
    """
    try:
        # 先获取所有消息，然后过滤（这里可以优化为在DAO层直接过滤）
        all_messages = await chat_message_dao.get_messages_by_session_id(session_id, limit * 2)  # 获取更多以便过滤

        # 过滤指定事件类型的消息
        filtered_messages = [msg for msg in all_messages if msg.event == event][:limit]

        if not filtered_messages:
            return ChatMessagesListResponse(
                success=True,
                message=f"会话 {session_id} 中暂无 {event} 类型的消息",
                data={
                    "session_id": session_id,
                    "event": event,
                    "total_count": 0,
                    "messages": []
                }
            )

        # 转换为响应格式
        message_list = [ChatMessageResponse.from_message(msg) for msg in filtered_messages]

        response_data = {
            "session_id": session_id,
            "event": event,
            "total_count": len(filtered_messages),
            "limit": limit,
            "messages": [msg.dict() for msg in message_list]
        }

        return ChatMessagesListResponse(
            success=True,
            message=f"成功查询到会话 {session_id} 中 {len(filtered_messages)} 条 {event} 类型的消息",
            data=response_data
        )

    except Exception as e:
        logger.error(f"根据会话ID和事件类型查询消息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/message/{message_id}", response_model=ChatMessagesListResponse)
async def get_message_by_id(message_id: int):
    """
    根据消息ID查询单条消息
    
    Args:
        message_id: 消息ID
        
    Returns:
        ChatMessagesListResponse: 包含消息详情的响应
    """
    try:
        # 查询消息
        message = await chat_message_dao.get_message_by_id(message_id)

        if not message:
            return ChatMessagesListResponse(
                success=False,
                message=f"未找到ID为 {message_id} 的消息",
                data=None
            )

        # 转换为响应格式
        message_response = ChatMessageResponse.from_message(message)

        response_data = {
            "message": message_response.dict()
        }

        return ChatMessagesListResponse(
            success=True,
            message=f"成功查询到消息 {message_id}",
            data=response_data
        )

    except Exception as e:
        logger.error(f"根据消息ID查询消息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/message/unique/{session_id}/{message_id}/{event}", response_model=ChatMessagesListResponse)
async def get_message_by_unique_key(
        session_id: str,
        message_id: str,
        event: str
):
    """
    根据唯一键（会话ID + 消息ID + 事件类型）查询消息
    
    Args:
        session_id: 会话ID
        message_id: 消息ID
        event: 事件类型
        
    Returns:
        ChatMessagesListResponse: 包含消息详情的响应
    """
    try:
        # 查询消息
        message = await chat_message_dao.get_message_by_session_message_event(
            session_id, message_id, event
        )

        if not message:
            return ChatMessagesListResponse(
                success=False,
                message=f"未找到消息: session_id={session_id}, message_id={message_id}, event={event}",
                data=None
            )

        # 转换为响应格式
        message_response = ChatMessageResponse.from_message(message)

        response_data = {
            "message": message_response.dict()
        }

        return ChatMessagesListResponse(
            success=True,
            message=f"成功查询到消息",
            data=response_data
        )

    except Exception as e:
        logger.error(f"根据唯一键查询消息失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/sessions", response_model=ChatMessagesListResponse)
async def get_all_sessions(
        limit: int = Query(50, ge=1, le=500, description="每页记录数，范围1-500")
):
    """
    获取所有有消息的会话列表
    
    Args:
        limit: 每页记录数，默认50，范围1-500
        
    Returns:
        ChatMessagesListResponse: 包含会话列表的响应
    """
    try:
        # 这里需要在DAO层添加一个方法来获取所有会话，暂时通过查询实现
        # 由于当前DAO没有直接的方法，我们可以通过一个简单的查询来获取会话列表

        # 注意：这个实现可能需要优化，特别是在数据量大的情况下
        sql = f"""
        SELECT DISTINCT session_id, 
               COUNT(*) as message_count,
               MAX(create_time) as latest_message_time,
               MIN(create_time) as first_message_time
        FROM chat_message 
        GROUP BY session_id 
        ORDER BY latest_message_time DESC 
        LIMIT %s
        """

        from src.database.connection import db_manager

        rows = await db_manager.execute_with_retry(sql, (limit,), fetch_type="all")

        if not rows:
            return ChatMessagesListResponse(
                success=True,
                message="暂无会话记录",
                data={
                    "total_count": 0,
                    "sessions": []
                }
            )

        # 转换为响应格式
        sessions = []
        for row in rows:
            session_info = {
                "session_id": row["session_id"],
                "message_count": row["message_count"],
                "latest_message_time": row["latest_message_time"].isoformat() if row["latest_message_time"] else None,
                "first_message_time": row["first_message_time"].isoformat() if row["first_message_time"] else None
            }
            sessions.append(session_info)

        response_data = {
            "total_count": len(sessions),
            "limit": limit,
            "sessions": sessions
        }

        return ChatMessagesListResponse(
            success=True,
            message=f"成功查询到 {len(sessions)} 个会话",
            data=response_data
        )

    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )
