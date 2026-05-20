"""
状态类型定义模块
"""
from typing import Optional, List, Dict

from langgraph.graph import MessagesState
from pydantic import BaseModel


class State(MessagesState):
    """聊天状态类，继承自MessagesState"""
    message_id: Optional[str] = None  # 消息ID
    messages: list[dict] = []
    session_id: str  # 会话ID
    workflow_id: str = ""  # 工作流ID
    status: Optional[str] = None  # 处理状态
    video_url: str = ""  # 视频URL
    video_path: str = ""  # 视频路径
    key_frame_detect_node_result: Optional[dict] = None  # 关键帧提取结果
    key_frame_filter_node_result: Optional[dict] = None  # 关键帧筛选结果
    collage_node_result: Optional[dict] = None
    asr_node_result: Optional[dict] = None  # asr提取结果
    text_and_image_combine_node_result: Optional[dict] = None

    debug: Optional[bool] = None  # 是否开启调试模式
    jump_node: Optional[str] = None  # 当前节点

    # 视频处理相关字段
    video_full_transcript: Optional[str] = None  # 完整视频字幕
    video_duration: Optional[str] = None  # 视频时长
    video_theme: Optional[str] = None  # 视频主题
    video_frame_list: Optional[List[dict]] = None  # 候选帧列表

    # VLM选择结果
    vlm_selection_result: Optional[dict] = None
    vlm_choose_result: Optional[dict] = None  # VLM选择节点结果

    # 图片处理结果
    image_processing_result: Optional[dict] = None  # 图片处理节点结果

    # POI景点提取结果
    poi_extract_node_result: Optional[dict] = None  # POI景点提取

    # 小红书文案生成结果
    generate_node_result: Optional[dict] = None

    # 小红书文案参考字段
    xhs_note_from_content: Optional[str] = None  # 参数的小红书帖子内容
    xhs_note_from_style: Optional[str] = None

    style_request_dict: Optional[dict] = None  # data_for_xhs_content.py 的 key

    xhs_final_text_node_result: Optional[dict] = None  # 小红书文案生成结果
    xhs_post_scoring_node_result: Optional[dict] = None
    global_user_message: Optional[str] = None  # 全局用户信息，用于chat

    # Token使用记录(支持并行节点)
    # 每条记录格式: {"node_name_zh": "节点中文名", "node_name_en": "node_name", "model_name": "azure/gpt-5-chat", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    token_usage_records: Optional[List[Dict]] = None  # Token使用记录列表
    img2img_usage_records: Optional[List[Dict]] = None
    xhs_hot_content_node_result: Optional[dict] = None


class Request(BaseModel):
    """聊天请求模型"""
    query: Optional[str] = None
    session_id: Optional[str] = None
    workflow_id: Optional[str] = None
    video_url: Optional[str] = None  # 视频URL
    video_path: Optional[str] = None  # 视频路径
    status: Optional[str] = None  # 处理状态
    xhs_note_from_content: Optional[str] = None  # 参数的小红书帖子内容
    xhs_note_from_style: Optional[str] = None  # data_for_xhs_content.py 的 key
    message: Optional[str] = None  # 消息内容
    state: Optional[str] = None  # 状态
    username: Optional[str] = None  # 用户名
    task_name: Optional[str] = None
    chat_message: Optional[dict] = None
