"""
数据库模块
提供MySQL数据库集成和video_workflow_record表的CRUD操作
"""

from .config import db_config, connection_info, DatabaseConfig, ConnectionInfo
from .connection import db_manager, DatabaseConnectionManager
from .models import (
    VideoWorkflowRecord,
    VideoWorkflowRecordCreate,
    VideoWorkflowRecordUpdate,
    VideoWorkflowRecordQuery
)
from .video_workflow_record_dao import video_workflow_record_dao as video_workflow_dao, VideoWorkflowRecordDAO
from .video_workflow_record_service import video_workflow_record_service as video_workflow_service, \
    VideoWorkflowRecordService
from .ext_utils import parse_state_from_ext

__all__ = [
    # 配置
    "db_config",
    "connection_info",
    "DatabaseConfig",
    "ConnectionInfo",

    # 连接管理
    "db_manager",
    "DatabaseConnectionManager",

    # 模型
    "VideoWorkflowRecord",
    "VideoWorkflowRecordCreate",
    "VideoWorkflowRecordUpdate",
    "VideoWorkflowRecordQuery",

    # 数据访问层
    "video_workflow_dao",
    "VideoWorkflowRecordDAO",

    # 服务层
    "video_workflow_service",
    "VideoWorkflowRecordService",
    
    # 工具函数
    "parse_state_from_ext",
]
