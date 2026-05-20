"""
视频工作流相关API接口
"""
import logging
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from src.database.models import VideoWorkflowRecordQuery
from src.database.video_workflow_record_service import video_workflow_record_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/work", tags=["work"])


class VideoWorkflowRecordResponse(BaseModel):
    """视频工作流记录响应模型（不包含ext字段）"""
    id: Optional[int]
    session_id: str
    workflow_id: str
    task_name: Optional[str]
    video_url: Optional[str]
    username: Optional[str]
    status: str
    create_time: Optional[str]
    update_time: Optional[str]

    @classmethod
    def from_record(cls, record) -> 'VideoWorkflowRecordResponse':
        """从数据库记录创建响应对象，排除ext字段"""
        return cls(
            id=record.id,
            session_id=record.session_id,
            workflow_id=record.workflow_id,
            task_name=record.task_name,
            video_url=record.video_url,
            username=record.username,
            status=record.status,
            create_time=record.create_time.isoformat() if record.create_time else None,
            update_time=record.update_time.isoformat() if record.update_time else None
        )


class VideoWorkflowSessionsResponse(BaseModel):
    """用户会话列表响应模型"""
    success: bool
    message: str
    data: Dict[str, Any] = None


@router.get("/list", response_model=VideoWorkflowSessionsResponse)
async def get_sessions_by_username(
        username: str = Query(..., description="用户名"),
        limit: int = Query(100, ge=1, le=1000, description="每页记录数，范围1-1000"),
        offset: int = Query(0, ge=0, description="偏移量，从0开始")
):
    """
    根据用户名查询所有会话
    
    Args:
        username: 用户名，必填
        limit: 每页记录数，默认100，范围1-1000
        offset: 偏移量，默认0
        
    Returns:
        VideoWorkflowSessionsResponse: 包含会话列表的响应
    """
    try:
        # 构建查询参数
        query_params = VideoWorkflowRecordQuery(
            username=username,
            limit=limit,
            offset=offset
        )

        # 查询记录
        records, total_count = await video_workflow_record_service.query_workflow_records(query_params)

        # 转换为响应格式（排除ext字段）
        session_list = [VideoWorkflowRecordResponse.from_record(record) for record in records]

        response_data = {
            "username": username,
            "total_records": total_count,
            "limit": limit,
            "offset": offset,
            "records": session_list,
        }

        return VideoWorkflowSessionsResponse(
            success=True,
            message=f"成功查询到用户 {username} 的 {len(session_list)} 个会话，共 {total_count} 条记录",
            data=response_data
        )

    except Exception as e:
        logger.error(f"根据用户名查询会话失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/query/{session_id}", response_model=VideoWorkflowSessionsResponse)
async def get_session_detail(
        session_id: str,
        username: Optional[str] = Query(None, description="用户名过滤（可选）")
):
    """
    根据会话ID查询会话详情
    
    Args:
        session_id: 会话ID
        username: 用户名过滤，可选
        
    Returns:
        VideoWorkflowSessionsResponse: 包含会话详情的响应
    """
    try:
        # 构建查询参数
        query_params = VideoWorkflowRecordQuery(
            session_id=session_id,
            username=username,
            limit=1000,  # 单个会话通常不会有太多记录
            offset=0
        )

        # 查询记录
        records, total_count = await video_workflow_record_service.query_workflow_records(query_params)

        if not records:
            return VideoWorkflowSessionsResponse(
                success=False,
                message=f"未找到会话ID为 {session_id} 的记录",
                data=None
            )

        # 转换为响应格式（排除ext字段）
        session_records = [VideoWorkflowRecordResponse.from_record(record) for record in records]

        # 统计会话信息
        session_info = {
            "session_id": session_id,
            "username": records[0].username,
            "workflow_count": len(records),
            "workflows": {},
            "records": [record.dict() for record in session_records]
        }

        # 按workflow_id分组
        for record in session_records:
            workflow_id = record.workflow_id
            if workflow_id not in session_info["workflows"]:
                session_info["workflows"][workflow_id] = {
                    "workflow_id": workflow_id,
                    "record_count": 0,
                    "latest_status": None,
                    "latest_update_time": None,
                    "records": []
                }

            workflow_info = session_info["workflows"][workflow_id]
            workflow_info["record_count"] += 1
            workflow_info["records"].append(record.dict())

            # 更新最新状态
            if (workflow_info["latest_update_time"] is None or
                    (record.update_time and record.update_time > workflow_info["latest_update_time"])):
                workflow_info["latest_status"] = record.status
                workflow_info["latest_update_time"] = record.update_time

        return VideoWorkflowSessionsResponse(
            success=True,
            message=f"成功查询到会话 {session_id} 的详情，共 {total_count} 条记录",
            data=session_info
        )

    except Exception as e:
        logger.error(f"根据会话ID查询详情失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get("/records", response_model=VideoWorkflowSessionsResponse)
async def query_workflow_records(
        username: Optional[str] = Query(None, description="用户名过滤"),
        session_id: Optional[str] = Query(None, description="会话ID过滤"),
        workflow_id: Optional[str] = Query(None, description="工作流ID过滤"),
        task_name: Optional[str] = Query(None, description="任务名称过滤（模糊匹配）"),
        status: Optional[str] = Query(None, description="状态过滤"),
        limit: int = Query(50, ge=1, le=1000, description="每页记录数，范围1-1000"),
        offset: int = Query(0, ge=0, description="偏移量，从0开始")
):
    """
    条件查询视频工作流记录
    
    Args:
        username: 用户名过滤，可选
        session_id: 会话ID过滤，可选
        workflow_id: 工作流ID过滤，可选
        task_name: 任务名称过滤（模糊匹配），可选
        status: 状态过滤，可选
        limit: 每页记录数，默认50，范围1-1000
        offset: 偏移量，默认0
        
    Returns:
        VideoWorkflowSessionsResponse: 包含查询结果的响应
    """
    try:
        # 构建查询参数
        query_params = VideoWorkflowRecordQuery(
            username=username,
            session_id=session_id,
            workflow_id=workflow_id,
            task_name=task_name,
            status=status,
            limit=limit,
            offset=offset
        )

        # 查询记录
        records, total_count = await video_workflow_record_service.query_workflow_records(query_params)

        # 转换为响应格式（排除ext字段）
        record_list = [VideoWorkflowRecordResponse.from_record(record) for record in records]

        response_data = {
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "filters": {
                "username": username,
                "session_id": session_id,
                "workflow_id": workflow_id,
                "task_name": task_name,
                "status": status
            },
            "records": [record.dict() for record in record_list]
        }

        return VideoWorkflowSessionsResponse(
            success=True,
            message=f"成功查询到 {len(record_list)} 条记录，总数: {total_count}",
            data=response_data
        )

    except Exception as e:
        logger.error(f"条件查询工作流记录失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


class UpdateNoteContentRequest(BaseModel):
    """更新笔记内容请求模型"""
    session_id: str = Field(..., description="会话ID")
    username: Optional[str] = Field(None, description="用户名，如果为空则为global")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容")
    tag_list: List[str] = Field(..., description="标签列表")
    image_list: List[str] = Field(..., description="图片列表")


class UpdateNoteContentResponse(BaseModel):
    """更新笔记内容响应模型"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


@router.post("/update-note", response_model=UpdateNoteContentResponse)
async def update_note_content(
        request: UpdateNoteContentRequest = Body(...)
):
    """
    更新笔记内容
    
    Args:
        request: 更新请求，包含：
            - session_id: 会话ID
            - username: 用户名（可选，默认为"global"）
            - title: 标题
            - content: 内容
            - tag_list: 标签列表
            - image_list: 图片列表
            
    Returns:
        UpdateNoteContentResponse: 更新结果响应
    """
    try:
        # 调用服务层方法处理业务逻辑
        success, message, data = await video_workflow_record_service.update_note_content(
            session_id=request.session_id,
            username=request.username,
            title=request.title,
            content=request.content,
            tag_list=request.tag_list,
            image_list=request.image_list
        )
        
        # 根据结果返回响应
        if not success:
            return UpdateNoteContentResponse(
                success=False,
                message=message,
                data=data
            )
        
        return UpdateNoteContentResponse(
            success=True,
            message=message,
            data=data
        )
        
    except Exception as e:
        logger.error(f"更新笔记内容API调用失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"更新失败: {str(e)}"
        )
