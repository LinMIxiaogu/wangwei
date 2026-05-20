"""
API路由模块
"""
import json
import logging
import logging.config
import os
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from typing import List

import uvicorn
from fastapi import FastAPI, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from src.api.chat_message import router as chat_message_router
from src.api.video_workflow import router as video_workflow_router
from src.database import video_workflow_service, VideoWorkflowRecordQuery, VideoWorkflowRecordCreate
from src.database.chat_message_dao import chat_message_dao
from src.database.models import ChatMessageCreate
from src.graph.event.manager import event_manager
from src.graph.node.data_for_xhs_content import xhs_note_from_style_map
from src.graph.state.types import Request
from src.graph.state.types import State
from src.service import xhs_detail_service
from src.service.chat_service import stream_updated_xhs_content, stream_xhs_post_score
from src.service.img2img_service import img2img_service
from src.service.obs_service import obs_service
from src.service.xhs_hot_keyword_service import get_default_xhs_hot_keyword_service

# 配置日志
current_dir = os.path.dirname(os.path.abspath(__file__))

# 确保日志目录存在。本地开发默认写到项目 logs/，服务器可通过 APP_LOG_DIR 覆盖。
log_dir = os.getenv("APP_LOG_DIR", os.path.abspath(os.path.join(current_dir, "../logs")))
os.makedirs(log_dir, exist_ok=True)

# 加载配置
try:
    logging.config.fileConfig(os.path.join(current_dir, "../conf/logging.conf"), disable_existing_loggers=False)
except Exception:
    logging.basicConfig(level=logging.INFO,
                        format='[%(asctime)s] %(levelname)s in %(filename)s:%(lineno)d - %(message)s', force=True)

logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(title="增强型 SSE 对话服务")

# 包含主流程和预览相关路由
app.include_router(video_workflow_router)
app.include_router(chat_message_router)


@app.get("/onlinecheck")
def onlinecheck_get():
    """ 上线时的监控检测 """
    return "当前时间:" + datetime.now().isoformat()


@app.head("/onlinecheck")
def onlinecheck_head():
    return Response(headers={"X-Dummy": "dummy"}, status_code=200)


@app.get("/healthcheck.html")
def healthcheck_get():
    """ healthcheck 机制 """
    return "当前时间:" + datetime.now().isoformat()


@app.head("/healthcheck.html")
def healthcheck_head():
    return Response(headers={"X-Dummy": "dummy"}, status_code=200)


@app.post("/chat/stream", response_class=StreamingResponse)
async def stream_chat(request: Request):
    """支持节点内部推送的 SSE 接口"""
    state_old = {}
    global_user_message = request.message

    # 保存用户输入的chat_message
    if request.chat_message:
        try:
            message_id = str(uuid.uuid4())
            # 解析chat_message字典，提取event和data
            event = request.chat_message.get("event")
            data = request.chat_message.get("data", {})

            # 根据event类型确定message_type
            message_type = "HUMAN"  # 默认为user类型

            # 创建ChatMessageCreate对象
            chat_message_create = ChatMessageCreate(
                session_id=request.session_id or "",
                message_id=message_id,
                event=event,
                event_data=data,
                message_type=message_type
            )

            # 保存到数据库
            await chat_message_dao.create_message(chat_message_create)
            logger.info(f"成功保存用户输入消息: session_id={request.session_id}, event={event}")
        except Exception as e:
            logger.error(f"保存用户输入消息失败: {e}")

    if request.state:
        # 先提取 JSON 内容为普通 dict
        state_data = json.loads(request.state)
        global_user_message = request.message if request.message else state_data.get(
            "global_user_message")
        # 如果不需要 messages，可以安全删除
        state_data.pop("messages", None)
        state_data.pop("session_id", None)
        state_data.pop("workflow_id", None)
        state_data.pop("video_url", None)
        state_data.pop("video_path", None)
        state_data.pop("status", None)
        state_data.pop("xhs_note_from_content", None)
        state_data.pop("xhs_note_from_style", None)
        state_data.pop("global_user_message", None)
        state_old = State(**state_data)

    # 初始化状态
    state = State(
        messages=[HumanMessage(content=request.message)] if request.message else [],
        session_id=request.session_id,
        workflow_id=request.workflow_id if request.workflow_id else None,
        video_url=request.video_url if request.video_url else None,
        video_path=request.video_path if request.video_path else None,
        status=request.status if request.status else None,
        xhs_note_from_content=request.xhs_note_from_content if request.xhs_note_from_content else None,
        xhs_note_from_style=request.xhs_note_from_style if request.xhs_note_from_style else None,
        global_user_message=global_user_message,
        **state_old
    )

    # 创建或获取工作流记录
    try:
        create_data = VideoWorkflowRecordCreate(
            session_id=request.session_id or "",
            workflow_id=request.workflow_id or "chat",
            task_name=request.task_name or "视频处理任务",
            video_url=request.video_url or request.video_path or "",
            status="INIT",
            username=request.username or "global",
        )

        await video_workflow_service.create_or_update_workflow_record(
            session_id=create_data.session_id,
            workflow_id=create_data.workflow_id,
            record_data=create_data
        )
        logger.info(f"工作流记录已创建或获取: session_id={request.session_id}")
    except Exception as e:
        logger.error(f"创建工作流记录失败: {e}")

    print(state)
    return StreamingResponse(
        event_manager.event_generator(state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )


@app.post("/chat/session")
async def create_session():
    """创建新会话"""
    session_id = str(uuid.uuid4())
    return {"session_id": session_id}


@app.get("/workflow/records")
async def query_workflow_records_api(session_id: str):
    """
    按会话ID查询工作流记录，固定筛选状态为已完成（status=2）。

    Query Params:
    - session_id: 会话ID（必填）
    """
    result = {"status": 0, "message": "success", "data": {}}
    try:
        query_params = VideoWorkflowRecordQuery(
            session_id=session_id,
            status="SUCCESS",
        )
        records, total = await video_workflow_service.query_workflow_records(query_params)
        # 统一序列化
        serialized = []
        for r in records:
            if hasattr(r, "to_dict"):
                serialized.append(r.to_dict())
            else:
                try:
                    serialized.append(r.model_dump())
                except Exception:
                    serialized.append(dict(r))
        result["data"] = {"total": total, "records": serialized}
        return result
    except Exception as e:
        logger.exception(f"query_workflow_records_error: {str(e)}")
        return {"status": 1, "message": f"query_workflow_records_error: {str(e)}"}


@app.post("/upload/file")
async def upload_file(file: UploadFile = File(...)):
    """
    上传文件到 OSS 并保存到本地

    Args:
        file: 上传的文件

    Returns:
        dict: 包含 OSS 链接和本地文件路径的响应
    """
    result = {
        "status": 0,
        "data": {}
    }
    try:
        # 验证文件名
        if not file.filename:
            result["status"] = 1
            result["message"] = "Filename is empty"
            return result

        # 获取文件扩展名
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ''

        # 创建按日期分组的文件夹
        today = datetime.now().strftime("%Y-%m-%d")
        upload_dir = os.path.join("..", "data", today)
        os.makedirs(upload_dir, exist_ok=True)

        # 生成唯一的文件名（保留原始扩展名）
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        local_file_path = os.path.join(upload_dir, unique_filename)

        # 保存文件到本地
        content = await file.read()
        with open(local_file_path, "wb") as f:
            f.write(content)

        # 上传文件到 OSS
        oss_url = await obs_service.upload_file(local_file_path, unique_filename)
        if not oss_url:
            local_path = os.path.abspath(local_file_path).replace("\\", "/")
            result["data"] = {
                "oss_url": local_path,
                "local_path": local_path,
                "filename": file.filename,
                "unique_filename": unique_filename,
                "storage_warning": "Remote upload failed; using local_path for local development",
            }
            result["message"] = "Remote upload failed; using local_path"
            return result
        result["data"] = {
            "oss_url": oss_url,
            "local_path": local_file_path.replace("\\", "/"),  # 统一使用正斜杠
            "filename": file.filename,
            "unique_filename": unique_filename,
        }
        return result
    except Exception as e:
        logger.exception(f"upload_file_error: {str(e)}")
        result["status"] = 1
        result["message"] = f"upload_file_error: {str(e)}"
        return result


@app.get("/chat/basicData")
async def get_basic_data():
    """获取基础数据 - 返回小红书笔记风格映射数据"""
    return {
        "status": 0,
        "message": "success",
        "data": {
            "xhs_note_from_style_map": xhs_note_from_style_map,
        }
    }


class UpdateXhsRequest(BaseModel):
    title: str
    content: str
    field: str  # "title" 或 "content"
    session_id: str
    requirements: str | None = None


@app.post("/chat/updateXhsContentStream", response_class=StreamingResponse)
async def update_xhs_content_stream(req: UpdateXhsRequest):
    """流式输出更新小红书内容（SSE）。"""
    try:
        if req.field not in ("title", "content"):
            return {"status": 1, "message": "field 必须是 'title' 或 'content'"}
        generator = stream_updated_xhs_content(
            req.title,
            req.content,
            req.field,
            req.session_id,
            req.requirements,
        )  # type: ignore
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception(f"update_xhs_content_stream_error: {str(e)}")
        return {"status": 1, "message": f"update_xhs_content_stream_error: {str(e)}"}


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "active_sessions": event_manager.active_sessions_count
    }


@app.get("/xhs_list")
async def get_xhs_list():
    """获取video_workflow_record表所有数据，最近创建的在前面"""
    return await xhs_detail_service.get_xhs_list()


@app.get("/xhs_detail")
async def get_xhs_detail(session_id: str):
    """获取小红书详情数据接口"""
    return await xhs_detail_service.get_xhs_detail(session_id)


@app.post("/chat/publishXhsNote")
async def publish_xhs_note(xhs_note: Dict[str, Any]):
    """
    小红书帖子发布节点 - 发布小红书帖子
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent  # 也可用你现有的图
    from src.graph.llm.openrouter import create_llm_by_biz

    client = MultiServerMCPClient(
        {
            "xiaohongshu-mcp": {
                "transport": "streamable_http",
                "url": "http://localhost:18060/mcp",
            }
        }
    )
    # 2) 拉取 MCP 工具（会把该服务器上所有 tools 映射成 LangChain Tool）
    tools = await client.get_tools(server_name="xiaohongshu-mcp")

    # 过滤掉缺少有效参数 Schema 的工具，避免 LLM 请求时报 invalid_function_parameters
    def _is_schema_valid(tool):
        schema = getattr(tool, "args_schema", None)
        if schema is None:
            return False
        if isinstance(schema, dict):
            return "properties" in schema
        # Pydantic BaseModel 形式
        try:
            return "properties" in schema.schema()
        except Exception:
            return False

    tools = [t for t in tools if _is_schema_valid(t)]
    # 可选：打印过滤后的工具列表，便于调试

    # 3) 选择发布 Agent 的模型。这里走项目通用的业务模型配置，避免硬编码到单个失效账号。
    llm = create_llm_by_biz("xhs_note_publish", temperature=0.1, max_tokens=4096)

    # 4) 用预制 ReAct 代理把模型和 MCP 工具串起来
    agent = create_react_agent(llm, tools)
    res = await agent.ainvoke({
        "messages": [
            ("user",
             f"在小红书发布一条笔记：标题为{xhs_note['title']}，正文为{xhs_note['content']}，图片是：{xhs_note['image_list']}，标签是：{xhs_note['tag_list']}。")
        ]
    })
    return res


class XhsHotKeywordsSearchRequest(BaseModel):
    keyword: str
    topK: int = 20
    similarityThreshold: Optional[float] = None


@app.post("/xhs/hot_keywords/search_by_embedding")
async def xhs_hot_keywords_search_by_embedding(req: XhsHotKeywordsSearchRequest):
    """
    基于 keyword 的小红书热词相似检索：
    - 将 keyword 转为 embedding
    - 使用向量检索返回相似热词
    """
    try:
        service = get_default_xhs_hot_keyword_service()
        # 使用文本->向量->相似检索
        results = service.search_by_text(
            query=req.keyword,
            top_k=req.topK,
            similarity_threshold=req.similarityThreshold
        )
        return {
            "status": 0,
            "message": "success",
            "data": results
        }
    except Exception as e:
        logger.exception(f"xhs_hot_keywords_search_by_embedding_error: {str(e)}")
        return {"status": 1, "message": f"xhs_hot_keywords_search_by_embedding_error: {str(e)}"}


class XhsHotKeywordsImportItem(BaseModel):
    keyword: str
    keywordType: Optional[str] = ""
    primaryLabel: Optional[str] = ""
    secondaryLabel: Optional[str] = ""
    businessScenario: Optional[str] = ""
    keywordEmbedding: Optional[List[float]] = None
    deleted: Optional[int] = 0


class XhsHotKeywordsImportRequest(BaseModel):
    items: List[XhsHotKeywordsImportItem]
    autoEmbedding: bool = True


@app.post("/xhs/hot_keywords/import")
async def xhs_hot_keywords_import(req: XhsHotKeywordsImportRequest):
    """
    批量导入小红书热词（支持自动生成 embedding）
    """
    try:
        service = get_default_xhs_hot_keyword_service()
        # 映射前端驼峰为后端下划线字段
        transformed = []
        for it in req.items:
            transformed.append({
                "keyword": it.keyword,
                "keyword_type": it.keywordType or "",
                "primary_label": it.primaryLabel or "",
                "secondary_label": it.secondaryLabel or "",
                "business_scenario": it.businessScenario or "",
                "keyword_embedding": it.keywordEmbedding,
                "deleted": it.deleted or 0
            })
        result = service.import_hot_keywords(transformed, auto_embedding=req.autoEmbedding)
        return {
            "status": 0,
            "message": "success",
            "data": result
        }
    except Exception as e:
        logger.exception(f"xhs_hot_keywords_import_error: {str(e)}")
        return {"status": 1, "message": f"xhs_hot_keywords_import_error: {str(e)}"}


class XhsPostScoreRequest(BaseModel):
    title: str
    content: str
    image_list: list[str]
    tag_list: list[str]


@app.post("/xhsPostScore", response_class=StreamingResponse)
async def xhs_post_score_stream(req: XhsPostScoreRequest):
    """流式输出小红书帖子评分（SSE）。"""
    try:
        generator = stream_xhs_post_score(
            req.title,
            req.content,
            req.image_list,
            req.tag_list,
        )
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception(f"xhs_post_score_stream_error: {str(e)}")
        return {"status": 1, "message": f"xhs_post_score_stream_error: {str(e)}"}


class ImageEnhancementRequest(BaseModel):
    image_url: str


@app.post("/imageEnhancement")
async def image_enhancement(req: ImageEnhancementRequest):
    """图像增强业务：调用服务层进行图像增强并返回最终外链。"""
    try:
        result = await img2img_service.enhance_image_and_upload(req.image_url)
        if result.get("success"):
            return {
                "status": 0,
                "message": "成功",
                "data": {
                    "image_url": req.image_url,
                    "enhanced_image_url": result.get("oss_url")
                }
            }
        else:
            return {
                "status": 1,
                "message": result.get("message", "image_enhancement_error"),
                "data": {}
            }
    except Exception as e:
        logger.exception(f"图像质量增强处理异常: {req.image_url}")
        return {
            "status": 1,
            "message": f"image_enhancement_error: {str(e)}",
            "data": {}
        }


class XhsCoverImageEnhancementRequest(BaseModel):
    title: str
    content: str
    origin_cover_image: str
    tag_list: list[str]


@app.post("/xhsCoverImageEnhancement")
async def xhs_cover_image_enhancement(req: XhsCoverImageEnhancementRequest):
    try:
        if not req.origin_cover_image:
            return {
                "status": 1,
                "message": "xhs_cover_enhancement_error: 缺少封面图片",
                "data": {}
            }

        result = await img2img_service.enhance_xhs_cover_and_upload(
            title=req.title,
            full_caption=req.content,
            hashtags=req.tag_list,
            head_image_url=req.origin_cover_image,
        )

        if result.get("success"):
            return {
                "status": 0,
                "message": "成功",
                "data": {
                    "origin_head_url": req.origin_cover_image,
                    "result_head_url": result.get("oss_url")
                }
            }
        else:
            return {
                "status": 1,
                "message": result.get("message", "xhs_cover_enhancement_error"),
                "data": {}
            }
    except Exception as e:
        logger.exception(f"封面图优化处理异常: {str(e)}")
        return {
            "status": 1,
            "message": f"xhs_cover_enhancement_error: {str(e)}",
            "data": {}
        }


if __name__ == "__main__":
    uvicorn.run(
        "__main__:app",
        host="0.0.0.0",
        port=8080,
        # reload=True,
        log_level="info"
    )
