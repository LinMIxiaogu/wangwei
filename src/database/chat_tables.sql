-- 聊天记录表
CREATE TABLE IF NOT EXISTS chat_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL COMMENT '会话ID',
    username VARCHAR(255) DEFAULT NULL COMMENT '用户名',
    video_name VARCHAR(500) DEFAULT NULL COMMENT '视频名称',
    status ENUM('INIT', 'SUCCESS', 'FAILED') DEFAULT 'INIT' COMMENT '状态：INIT-初始化，SUCCESS-成功，FAILED-失败',
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_session_id (session_id),
    INDEX idx_username (username),
    INDEX idx_status (status),
    INDEX idx_create_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天记录表';

-- 聊天消息表
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
