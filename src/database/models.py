"""
数据库模型定义
定义video_workflow_record表对应的Pydantic模型
"""
import json
from datetime import datetime
from functools import cached_property
from typing import Optional, Dict, Any, Union

from pydantic import BaseModel, validator, Field


# 常量定义
class WorkflowStatus:
    """工作流状态常量"""
    PENDING = 0  # 待处理
    PROCESSING = 1  # 处理中
    COMPLETED = 2  # 已完成
    FAILED = -1  # 失败

    @classmethod
    def get_status_name(cls, status: int) -> str:
        """获取状态名称"""
        status_map = {
            cls.PENDING: "待处理",
            cls.PROCESSING: "处理中",
            cls.COMPLETED: "已完成",
            cls.FAILED: "失败"
        }
        return status_map.get(status, "未知状态")

    @classmethod
    def is_valid_status(cls, status: int) -> bool:
        """验证状态是否有效"""
        return status in [cls.PENDING, cls.PROCESSING, cls.COMPLETED, cls.FAILED]


class ExtendData(BaseModel):
    """
    扩展数据模型
    
    用于存储视频工作流记录的扩展信息，包括状态、进度和元数据
    
    Attributes:
        state: 状态信息字典，包含当前处理状态和步骤
        progress: 处理进度，范围0-100
        metadata: 元数据字典，存储额外的信息
    """
    state: Optional[Dict[str, Any]] = Field(None, description="状态信息字典")
    progress: Optional[int] = Field(None, ge=0, le=100, description="处理进度(0-100)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据字典")
    note: Optional[Dict[str, Any]] = Field(None, description="笔记信息")


class ExtMixin:
    """
    扩展数据处理混入类
    
    提供通用的ext字段处理方法，包括JSON序列化/反序列化和缓存功能
    
    Methods:
        parse_ext_json: 验证器，处理ext字段的JSON序列化
        ext_data: 属性，获取解析后的ExtendData对象（带缓存）
        set_ext_data: 方法，设置扩展数据
    """

    @validator('ext', pre=True)
    def parse_ext_json(cls, v: Any) -> Optional[str]:
        """
        解析ext字段的JSON数据
        
        Args:
            v: 输入值，可以是ExtendData对象、字典、JSON字符串或None
            
        Returns:
            Optional[str]: JSON字符串或None
        """
        if v is None:
            return None
        if isinstance(v, (dict, ExtendData)):
            # 如果是字典或ExtendData对象，转换为JSON字符串
            try:
                if isinstance(v, ExtendData):
                    return json.dumps(v.model_dump(), ensure_ascii=False)
                return json.dumps(v, ensure_ascii=False)
            except (TypeError, ValueError):
                return None
        if isinstance(v, str):
            # 如果已经是字符串，验证是否为有效JSON
            try:
                json.loads(v)
                return v
            except json.JSONDecodeError:
                return None
        return None

    @cached_property
    def ext_data(self) -> Optional[ExtendData]:
        """
        获取解析后的扩展数据对象（带缓存）
        
        Returns:
            Optional[ExtendData]: 解析后的ExtendData对象，解析失败时返回None
        """
        if not hasattr(self, 'ext') or self.ext is None:
            return None
        try:
            data = json.loads(self.ext)
            return ExtendData(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def set_ext_data(self, data: Union[ExtendData, Dict[str, Any], None]) -> None:
        """
        设置扩展数据
        
        Args:
            data: 扩展数据，可以是ExtendData对象、字典或None
            
        Raises:
            ValueError: 当data类型不支持时抛出异常
        """
        if data is None:
            self.ext = None
        elif isinstance(data, ExtendData):
            self.ext = json.dumps(data.model_dump(), ensure_ascii=False)
        elif isinstance(data, dict):
            self.ext = json.dumps(data, ensure_ascii=False)
        else:
            raise ValueError("ext_data must be ExtendData, dict, or None")

        # 清除cached_property缓存，强制重新计算
        if hasattr(self, 'ext_data'):
            # 删除cached_property的缓存
            self.__dict__.pop('ext_data', None)


class VideoWorkflowRecord(BaseModel, ExtMixin):
    """
    视频工作流记录模型
    
    用于表示video_workflow_record表的数据结构，包含视频处理工作流的完整信息
    
    Attributes:
        id: 记录ID，主键
        session_id: 会话ID，用于关联用户会话
        workflow_id: 工作流ID，标识具体的工作流类型
        task_name: 任务名称，描述具体的任务内容
        video_url: 视频URL地址
        ext: 扩展数据的JSON字符串表示
        status: 处理状态，INIT=初始化，UPLOAD=上传完成，SUCCESS=处理成功
        create_time: 创建时间
        update_time: 更新时间
    """
    id: Optional[int] = Field(None, description="记录ID")
    session_id: str = Field(..., description="会话ID")
    workflow_id: str = Field(..., description="工作流ID")
    task_name: Optional[str] = Field(None, description="任务名称")
    video_url: Optional[str] = Field(None, description="视频URL地址")
    username: Optional[str] = Field(None, description="用户名")
    ext: Optional[str] = Field(None, description="JSON字符串格式的扩展数据")
    status: str = Field(None, description="处理状态：INIT=初始化，UPLOAD=上传完成，SUCCESS=处理成功")
    create_time: Optional[datetime] = Field(None, description="创建时间")
    update_time: Optional[datetime] = Field(None, description="更新时间")

    @validator('status')
    def validate_status(cls, v: str) -> str:
        """验证状态值是否有效"""
        if not VideoWorkflowStatus.is_valid_status(v):
            raise ValueError(f"无效的状态值: {v}")
        return v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式
        
        将模型实例转换为字典，并处理datetime字段的序列化
        
        Returns:
            Dict[str, Any]: 字典格式的数据
        """
        data = self.model_dump()
        # 处理datetime字段
        if data.get('create_time'):
            data['create_time'] = data['create_time'].isoformat()
        if data.get('update_time'):
            data['update_time'] = data['update_time'].isoformat()
        return data

    @classmethod
    def from_db_row(cls, row: dict) -> 'VideoWorkflowRecord':
        """
        从数据库行数据创建模型实例
        
        Args:
            row: 数据库查询返回的行数据字典
            
        Returns:
            VideoWorkflowRecord: 模型实例
        """
        data = dict(row)
        # ext字段已经是JSON字符串，直接使用
        return cls(**data)

    # 状态检查便捷方法
    def is_init(self) -> bool:
        """检查是否为初始化状态"""
        return self.status == VideoWorkflowStatus.INIT

    def is_upload(self) -> bool:
        """检查是否为上传完成状态"""
        return self.status == VideoWorkflowStatus.UPLOAD

    def is_success(self) -> bool:
        """检查是否为处理成功状态"""
        return self.status == VideoWorkflowStatus.SUCCESS

    def get_status_name(self) -> str:
        """获取状态名称"""
        return VideoWorkflowStatus.get_status_name(self.status)

    def can_update_status(self, new_status: str) -> bool:
        """检查是否可以更新到指定状态"""
        if not VideoWorkflowStatus.is_valid_status(new_status):
            return False

        # 状态转换规则
        if self.status == VideoWorkflowStatus.INIT:
            return new_status in [VideoWorkflowStatus.UPLOAD, VideoWorkflowStatus.SUCCESS]
        elif self.status == VideoWorkflowStatus.UPLOAD:
            return new_status == VideoWorkflowStatus.SUCCESS
        elif self.status == VideoWorkflowStatus.SUCCESS:
            # 已成功的记录不能再更改状态
            return False

        return False


class VideoWorkflowRecordCreate(BaseModel, ExtMixin):
    """
    创建视频工作流记录的数据模型
    
    用于创建新的视频工作流记录，包含必要的字段和验证规则
    
    Attributes:
        session_id: 会话ID，必填
        workflow_id: 工作流ID，必填
        task_name: 任务名称，可选
        video_url: 视频URL地址，可选
        ext: 扩展数据的JSON字符串表示，可选
        status: 初始状态，默认为INIT（初始化）
    """
    session_id: str = Field(..., description="会话ID")
    workflow_id: str = Field(..., description="工作流ID")
    task_name: Optional[str] = Field(None, description="任务名称")
    video_url: Optional[str] = Field(None, description="视频URL地址")
    username: Optional[str] = Field(None, description="用户名")
    ext: Optional[str] = Field(None, description="JSON字符串格式的扩展数据")
    status: str = Field(None, description="处理状态，默认为INIT（初始化）")

    @validator('status')
    def validate_status(cls, v: str) -> str:
        """验证状态值是否有效"""
        if not VideoWorkflowStatus.is_valid_status(v):
            raise ValueError(f"无效的状态值: {v}")
        return v

    @classmethod
    def create_with_extend_data(
            cls,
            session_id: str,
            workflow_id: str,
            video_url: str,
            extend_data: Optional[ExtendData] = None,
            status: str = ""
    ) -> 'VideoWorkflowRecordCreate':
        """
        便捷的构造方法，直接传入ExtendData对象
        
        Args:
            session_id: 会话ID
            workflow_id: 工作流ID
            video_url: 视频URL地址
            extend_data: 扩展数据对象，可选
            status: 初始状态，默认为0
            
        Returns:
            VideoWorkflowRecordCreate: 创建的模型实例
        """
        return cls(
            session_id=session_id,
            workflow_id=workflow_id,
            video_url=video_url,
            ext=extend_data,  # validator会自动处理ExtendData对象
            status=status
        )


class VideoWorkflowRecordUpdate(BaseModel, ExtMixin):
    """
    更新视频工作流记录的数据模型
    
    用于更新现有的视频工作流记录，所有字段都是可选的
    
    Attributes:
        session_id: 会话ID，可选
        workflow_id: 工作流ID，可选
        task_name: 任务名称，可选
        video_url: 视频URL地址，可选
        ext: 扩展数据的JSON字符串表示，可选
        status: 处理状态，可选
    """
    session_id: Optional[str] = Field(None, description="会话ID")
    workflow_id: Optional[str] = Field(None, description="工作流ID")
    task_name: Optional[str] = Field(None, description="任务名称")
    video_url: Optional[str] = Field(None, description="视频URL地址")
    username: Optional[str] = Field(None, description="用户名")
    ext: Optional[str] = Field(None, description="JSON字符串格式的扩展数据")
    status: Optional[str] = Field(None, description="处理状态")

    @validator('status')
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """验证状态值是否有效"""
        if v is not None and not VideoWorkflowStatus.is_valid_status(v):
            raise ValueError(f"无效的状态值: {v}")
        return v

    @classmethod
    def update_with_extend_data(
            cls,
            extend_data: Optional[ExtendData] = None,
            **kwargs
    ) -> 'VideoWorkflowRecordUpdate':
        """
        便捷的构造方法，直接传入ExtendData对象
        
        Args:
            extend_data: 扩展数据对象，可选
            **kwargs: 其他字段的更新值
            
        Returns:
            VideoWorkflowRecordUpdate: 更新的模型实例
        """
        if extend_data is not None:
            kwargs['ext'] = extend_data  # validator会自动处理ExtendData对象
        return cls(**kwargs)


class VideoWorkflowRecordQuery(BaseModel):
    """
    查询视频工作流记录的参数模型
    
    用于构建查询条件，支持分页和多字段过滤
    
    Attributes:
        session_id: 会话ID过滤条件，可选
        workflow_id: 工作流ID过滤条件，可选
        task_name: 任务名称过滤条件，可选
        video_url: 视频URL过滤条件，可选
        status: 状态过滤条件，可选
        limit: 每页记录数，默认10
        offset: 偏移量，默认0
    """
    session_id: Optional[str] = Field(None, description="会话ID过滤条件")
    workflow_id: Optional[str] = Field(None, description="工作流ID过滤条件")
    task_name: Optional[str] = Field(None, description="任务名称过滤条件")
    username: Optional[str] = Field(None, description="用户名")
    video_url: Optional[str] = Field(None, description="视频URL过滤条件")
    status: Optional[str] = Field(None, description="状态过滤条件")
    limit: int = Field(10, ge=1, le=100, description="每页记录数，范围1-100")
    offset: int = Field(0, ge=0, description="偏移量，从0开始")

    @validator('status')
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """验证状态值是否有效"""
        if v is not None and not VideoWorkflowStatus.is_valid_status(v):
            raise ValueError(f"无效的状态值: {v}")
        return v

    def to_filter_dict(self) -> Dict[str, Any]:
        """
        转换为过滤条件字典
        
        将查询参数转换为字典格式，排除None值和分页参数
        
        Returns:
            Dict[str, Any]: 过滤条件字典
        """
        filters = {}
        for field, value in self.model_dump().items():
            if value is not None and field not in ('limit', 'offset'):
                filters[field] = value
        return filters


# 视频工作流状态常量
class VideoWorkflowStatus:
    """视频工作流状态常量"""
    INIT = "INIT"  # 初始化 - 刚创建记录
    UPLOAD = "UPLOAD"  # 上传完成 - 视频已上传到OSS
    SUCCESS = "SUCCESS"  # 处理成功 - 工作流执行完成

    @classmethod
    def get_status_name(cls, status: str) -> str:
        """获取状态名称"""
        status_map = {
            cls.INIT: "初始化",
            cls.UPLOAD: "上传完成",
            cls.SUCCESS: "处理成功"
        }
        return status_map.get(status, "未知状态")

    @classmethod
    def is_valid_status(cls, status: str) -> bool:
        """验证状态是否有效"""
        return status in [cls.INIT, cls.UPLOAD, cls.SUCCESS]


class ChatMessage(BaseModel):
    """
    聊天消息模型
    
    用于表示chat_message表的数据结构，记录聊天消息和事件
    
    Attributes:
        id: 消息ID，主键
        session_id: 会话ID，用于关联用户会话
        message_id: 消息ID，业务层面的消息标识
        event: 事件类型
        event_data: 事件数据，JSON格式
        message_type: 消息类型（user/assistant/system等）
        create_time: 创建时间
        update_time: 更新时间
    """
    id: Optional[int] = Field(None, description="消息ID")
    session_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    event: str = Field(..., description="事件类型")
    event_data: Optional[Dict[str, Any]] = Field(None, description="事件数据")
    message_type: Optional[str] = Field(None, description="消息类型（AI/HUMAN等）")
    create_time: Optional[datetime] = Field(None, description="创建时间")
    update_time: Optional[datetime] = Field(None, description="更新时间")

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }

    @classmethod
    def from_db_row(cls, row: dict) -> 'ChatMessage':
        """从数据库行数据创建模型实例"""
        data = dict(row)
        # 处理JSON字段
        if data.get('event_data') and isinstance(data['event_data'], str):
            try:
                data['event_data'] = json.loads(data['event_data'])
            except json.JSONDecodeError:
                data['event_data'] = None
        return cls(**data)


class ChatMessageCreate(BaseModel):
    """
    创建聊天消息的数据模型
    
    Attributes:
        session_id: 会话ID，必填
        message_id: 消息ID，必填
        event: 事件类型，必填
        event_data: 事件数据，可选
        message_type: 消息类型（user/assistant/system等），可选
    """
    session_id: str = Field(..., description="会话ID")
    message_id: str = Field(..., description="消息ID")
    event: str = Field(..., description="事件类型")
    event_data: Optional[Dict[str, Any]] = Field(None, description="事件数据")
    message_type: Optional[str] = Field(None, description="消息类型（user/assistant/system等）")

