"""
初始化聊天相关数据库表的脚本
"""
import asyncio
import logging

from .connection import db_manager

logger = logging.getLogger(__name__)


async def create_chat_tables():
    """创建聊天相关的数据库表"""

    # 聊天消息表
    chat_message_sql = """
    CREATE TABLE IF NOT EXISTS chat_message (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(255) NOT NULL COMMENT '会话ID',
        message_id VARCHAR(255) NOT NULL COMMENT '消息ID',
        event VARCHAR(100) NOT NULL COMMENT '事件类型',
        event_data JSON DEFAULT NULL COMMENT '事件数据',
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_session_id (session_id),
        INDEX idx_message_id (message_id),
        INDEX idx_event (event),
        INDEX idx_create_time (create_time),
        INDEX idx_update_time (update_time),
        UNIQUE KEY uk_session_message_event (session_id, message_id, event)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天消息表';
    """
    
    try:
        await db_manager.initialize()

        # 创建聊天消息表
        await db_manager.execute_with_retry(chat_message_sql)
        logger.info("聊天消息表创建成功")

        logger.info("所有相关表创建完成")

    except Exception as e:
        logger.error(f"创建聊天表失败: {e}")
        raise
    finally:
        await db_manager.close()


async def main():
    """主函数"""
    logging.basicConfig(level=logging.INFO)
    await create_chat_tables()


if __name__ == "__main__":
    asyncio.run(main())
