import logging
import traceback
import uuid

from langchain_core.messages import AIMessage
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END
from langgraph.types import Command

# 使用prompt模板
from src.prompts.template import get_prompt_template_formatted
from src.utils.state_serialization import serialize_state_for_event, to_json
from .node import add_token_usage_to_state
from ..event.manager import event_manager
from ..state.types import State
from ...service.vlm_service import vlm_service

logger = logging.getLogger(__name__)


async def xhs_style_node(state: State):
    """
    小红书风格分析节点 - 分析原视频文案的风格特征，为生成小红书文案提供指导

    输入：
        - video_full_transcript: 原视频文案

    输出：
        - xhs_style_analysis: 视频文案风格分析描述
    """
    message_id = str(uuid.uuid4())

    try:
        # 发送节点启动通知
        await event_manager.send_event(
            state=state,
            event="xhs_style_node_start",
            data={"message": "🎨 开始分析视频文案风格~", "message_id": message_id}
        )

        # 获取原视频文案
        video_full_transcript = state.get("video_full_transcript", "")

        if not video_full_transcript or not video_full_transcript.strip():
            error_msg = "未找到原视频文案，无法进行风格分析"
            logger.warning(error_msg)
            await event_manager.send_event(
                state=state,
                event="error",
                data={"error": error_msg, "message_id": message_id}
            )
            return Command(
                update={
                    "xhs_style_analysis": "未提供原视频文案，无法分析风格",
                    "messages": [AIMessage(content="抱歉，未找到原视频文案，无法进行风格分析。")]
                },
                goto=END
            )

        logger.info(f"开始分析视频文案风格，文案长度: {len(video_full_transcript)} 字符")

        # 发送处理中通知
        await event_manager.send_event(
            state=state,
            event="xhs_style_node_stream",
            data={"message": "📝 正在分析文案风格特征...", "message_id": message_id}
        )

        # 获取并格式化提示词模板
        prompt = get_prompt_template_formatted(
            "xhs_style_analysis",
            VIDEO_FULL_TRANSCRIPT=video_full_transcript
        )

        # 构建消息
        messages = [
            SystemMessage(content="你是一位专业的内容分析师，擅长分析视频文案的写作风格。"),
            HumanMessage(content=prompt)
        ]

        # 发送分析中进度
        await event_manager.send_event(
            state=state,
            event="xhs_style_node_stream",
            data={"message": "🤔 AI正在分析风格特征...", "message_id": message_id}
        )

        # 调用 LLM（通过服务封装，显式追加全局用户消息）
        response_content, token_usage = await vlm_service.call_llm_with_messages(
            "xhs_style_analysis",  # 业务名称
            messages,
            global_user_message=state.get("global_user_message")
        )
        style_analysis = response_content.strip()
        logger.info(f"xhs_style_node llm response:{response_content}")
        # 记录token使用
        add_token_usage_to_state(state, "小红书风格分析", "xhs_style_node", token_usage)

        if not style_analysis:
            error_msg = "风格分析结果为空"
            logger.warning(error_msg)
            await event_manager.send_event(
                state=state,
                event="error",
                data={"error": error_msg, "message_id": message_id}
            )
            return Command(
                update={
                    "xhs_style_analysis": "风格分析失败",
                    "messages": [AIMessage(content="抱歉，风格分析未能生成有效结果。")]
                },
                goto=END
            )

        logger.info(f"风格分析完成，分析结果长度: {len(style_analysis)} 字符")

        from .data_for_xhs_content import xhs_note_from_style_map
        state["jump_node"] = "vlm_choose"
        # 发送完成通知
        await event_manager.send_event(
            state=state,
            event="xhs_style_node_result",
            data={
                "message": "✅ 视频文案风格分析完成~",
                "xhs_style_result": {
                    "原有视频风格": [style_analysis],
                    "🪄智能风格": ["智能风格"],
                    **xhs_note_from_style_map
                },
                # "message_id": message_id,
                # 避免序列化非 JSON 对象（如 AIMessage/HumanMessage 等）
                "state": to_json(serialize_state_for_event(state, include_messages=False)),
            }
        )

        return Command(
            update={
                "xhs_style_analysis": style_analysis,
                "messages": [AIMessage(content=f"视频文案风格分析完成：\n\n{style_analysis}")]
            },
            goto=END
        )

    except Exception as e:
        error_msg = f"风格分析异常: {str(e)}"
        logger.exception("xhs_style_node_error")

        # 发送错误事件
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": error_msg, "traceback": traceback.format_exc(), "message_id": message_id}
        )

        return Command(
            update={
                "xhs_style_analysis": f"风格分析失败: {str(e)}",
                "messages": [AIMessage(content="抱歉，风格分析过程中出现错误。")]
            },
            goto=END
        )
