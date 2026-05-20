"""
节点处理模块
"""
import asyncio
import copy
import json
import logging
import os
import random
import time
import traceback
import uuid
from pathlib import Path
from typing import Literal, Dict, Any

from json_repair import json_repair
from langchain_core.messages import AIMessage
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END
from langgraph.types import Command

# 使用prompt模板
from src.prompts.template import get_prompt_template_formatted
from src.utils.state_serialization import serialize_state_for_event, to_json
from .data_for_xhs_content import xhs_note_from_style_map
from ..event.manager import event_manager
from ..state.types import State
from ...database import video_workflow_service, VideoWorkflowRecordCreate
from ...database.models import ExtendData, VideoWorkflowStatus
from ...service import obs_service, key_frame_service, image_score_service, main_service
from ...service.asr_service import asr_service
from ...service.image_search_service import image_search_service
from ...service.img2img_service import img2img_service
from ...service.vlm_service import vlm_service, TokenUsage
from ...utils import collage_util
from ...utils.collage_util import download_oss_images_to_local, download_poi_img_list
from ...utils.file_handle_util import _parse_time_from_filename

logger = logging.getLogger(__name__)


def add_token_usage_to_state(state: State, node_name_zh: str, node_name_en: str, token_usage: TokenUsage):
    """将token使用记录添加到state中

    Args:
        state: 状态对象
        node_name_zh: 节点中文名称
        node_name_en: 节点英文名称
        token_usage: token使用信息
    """
    try:
        if token_usage and (token_usage.total_tokens > 0 or token_usage.input_tokens > 0):
            record = {
                "node_name_zh": node_name_zh,
                "node_name_en": node_name_en,
                "model_name": token_usage.model_name if hasattr(token_usage, 'model_name') else "",
                "input_tokens": token_usage.input_tokens,
                "output_tokens": token_usage.output_tokens,
                "total_tokens": token_usage.total_tokens
            }

            # 初始化token_usage_records列表(如果不存在)
            if state.get("token_usage_records") is None:
                state["token_usage_records"] = []

            # 添加记录
            state["token_usage_records"].append(record)
            logger.info(
                f"记录token使用: {node_name_zh}({node_name_en}) - model:{record['model_name']}, input:{token_usage.input_tokens}, output:{token_usage.output_tokens}, total:{token_usage.total_tokens}")
    except Exception as e:
        logger.error(f"记录token使用失败: {node_name_zh}({node_name_en}) - {str(e)}", exc_info=True)


def add_img2img_usage_to_state(state: State, node_name_zh: str, node_name_en: str, img_result: Dict[str, Any]):
    """将图生图调用的花费记录添加到 state；若同名记录存在则累加。

    需求：
    - 当 `node_name_zh` 与 `node_name_en` 与现有元素相同时，将本次 `consume` 插入到对应记录的 `consume` 列表；
    - 同时在记录中新增并维护 `total_consume` 字段，进行累计求和。
    """
    try:
        if not img_result:
            return

        current_consume = float(img_result.get("consume", 0) or 0)

        # 初始化 img2img_usage_records 列表(如果不存在)
        if state.get("img2img_usage_records") is None:
            state["img2img_usage_records"] = []

        # 查找是否存在同名节点记录
        target_record = None
        for rec in state["img2img_usage_records"]:
            if rec.get("node_name_zh") == node_name_zh and rec.get("node_name_en") == node_name_en:
                target_record = rec
                break

        if target_record is not None:
            # 将 consume 字段标准化为列表并追加当前消耗
            existing = target_record.get("consume", [])
            if isinstance(existing, list):
                consume_list = existing
            else:
                try:
                    prev = float(existing or 0)
                except Exception:
                    prev = 0.0
                consume_list = [prev] if prev > 0 else []

            if current_consume > 0:
                consume_list.append(current_consume)
            target_record["consume"] = consume_list
            target_record["total_consume"] = float(sum(consume_list))

            logger.info(
                f"记录图像花费累加: {node_name_zh}({node_name_en}) - last:{current_consume}, total:{target_record['total_consume']}"
            )
        else:
            # 创建新记录，consume 使用列表并计算总和
            consume_list = [current_consume] if current_consume > 0 else []
            new_record = {
                "node_name_zh": node_name_zh,
                "node_name_en": node_name_en,
                "consume": consume_list,
                "total_consume": float(sum(consume_list)),
            }
            state["img2img_usage_records"].append(new_record)
            logger.info(
                f"记录图像花费: {node_name_zh}({node_name_en}) - total:{new_record['total_consume']}"
            )
    except Exception as e:
        logger.error(f"记录图像花费失败: {node_name_zh}({node_name_en}) - {str(e)}", exc_info=True)


async def status_router_node(state: State) -> Command[
    Literal[END, "key_frame_detect_node", "xhs_note_publish_node"]]:
    """路由节点 - 根据处理状态跳转响应的节点"""

    if "jump_node" in state and state["jump_node"]:
        return Command(goto=state["jump_node"])
    if "status" in state and state["status"] == "init":
        return Command(goto=END, update={"messages": [SystemMessage(content="请描述您的问题")]})

    # recoder = VideoWorkflowRecordCreate.create_with_extend_data(
    #     session_id=state.get("session_id"),
    #     workflow_id=state.get("workflow_id"),
    #     video_url=state.get("video_url"),
    #     extend_data=ExtendData(state=state, note=None),
    #     status=0
    # )
    # await video_workflow_service.create_workflow_record(recoder)
    # record = await video_workflow_service.get_workflow_record_by_session_and_workflow(state.get("session_id"), "1")
    # print(record)
    return Command(goto=["key_frame_detect_node", "asr_node"])


async def research_node(state: State) -> Command[Literal[END, "llm_node"]]:
    """示例：研究节点 - 模拟多步骤推送"""
    # 步骤1：发送开始通知
    await event_manager.send_event(state=state, event="status", data={"message": "🔍 正在分析问题..."})

    await asyncio.sleep(1)  # 模拟处理（修改为1秒）

    # 步骤2：发送中间结果
    await event_manager.send_event(state=state, event="status", data={"message": "已识别关键词：LangGraph、SSE、流式推送"})

    return Command(
        update={
            "messages": [SystemMessage(content="研究完成")],
        },
        goto=END,
    )


async def summary_node(state: State):
    """总结节点 - 推送结构化数据"""

    # 发送总结结果
    await event_manager.send_event(state=state, event="status", data={"message": "✅ 总结完成"})

    return Command(
        goto=END,
    )


async def key_frame_detect_node(state: State):
    # --- 1. 路径和文件名设置 ---
    message_id = str(uuid.uuid4())
    await event_manager.send_event(state=state, event="key_frame_detect_node_start",
                                   data={"message": "开始关键帧检测~", "message_id": message_id})

    # 从 state 获取视频路径，如果未提供，则使用默认路径
    video_path = state.get("video_path", "")

    # 从完整视频路径中创建本地输出目录
    output_dir, _ = os.path.splitext(video_path)

    logger.info(f"本地输出目录: {output_dir}")

    # --- 2. 提取并上传关键帧 ---
    logger.info("正在提取、上传关键帧并发送进度...")
    saved_keyframe_info = await key_frame_service.find_best_keyframe_in_scenes_k(
        video_path,
        output_dir,
        state,
        obs_service,  # 传入obs_service实例
        message_id=message_id  # 传入message_id
    )

    if not saved_keyframe_info:
        logger.warning("未检测到任何关键帧，节点将提前结束。")
        return Command(
            update={"key_frame_detect_node_result": "No keyframes found."},
            goto=END,
        )

    # --- 3. 格式化数据 ---
    origin_key_frame_local_list = [item['local_path'] for item in saved_keyframe_info]
    origin_key_frame_oss_list = [item['oss_url'] for item in saved_keyframe_info]
    origin_key_frame_dict = {
        item['local_path']: item['oss_url']
        for item in saved_keyframe_info
    }

    logger.info(f"✅ 成功处理 {len(saved_keyframe_info)} 个关键帧。")

    # --- 4. 准备并返回最终结果 ---
    update_data = {
        "key_frame_detect_node_result": {
            "origin_key_frame_dict": origin_key_frame_dict,
            "origin_key_frame_oss_list": origin_key_frame_oss_list,
            "origin_key_frame_local_list": origin_key_frame_local_list
        }
    }
    await event_manager.send_event(state=state, event="key_frame_detect_node_end", data={
        "message": f"🎉 关键帧提取完成，共提取{len(origin_key_frame_local_list)} 个高质量关键帧",
        "image_list": origin_key_frame_oss_list,
        "message_id": message_id
    })
    return Command(
        update=update_data,
        goto="text_and_image_combine_node",
    )


async def key_frame_filter_node(state: State) -> Command[Literal[END, 'text_and_image_combine_node']]:
    """关键帧筛选节点 - 筛选出符合条件的关键帧"""
    message_id = str(uuid.uuid4())
    # 开始进入筛选关键帧
    await event_manager.send_event(state=state, event="key_frame_filter_node_start",
                                   data={"message": "开始关键帧评分~", "message_id": message_id})
    # 取出关键帧
    key_frames_local_path_list = state.get("key_frame_detect_node_result", {}).get("origin_key_frame_local_list", [])
    # 取出本地和 oss 的映射
    key_frames_local_path_to_oss_url = state.get("key_frame_detect_node_result", {}).get("origin_key_frame_dict", {})
    # 质量检测
    image_quality_list = {}
    total_frames = len(key_frames_local_path_list)

    # 创建共享进度列表
    processed_list = []

    async def process_single_image(key_frame_local_path, task_id):
        """处理单个图片的异步函数"""
        try:
            # # 调用图片质量检测服务
            image_quality = await image_score_service.score_image_from_file(key_frame_local_path)
            # # 更新结果和进度（list.append 和字典赋值都是原子操作）
            image_quality_list[key_frames_local_path_to_oss_url[key_frame_local_path]] = image_quality
            processed_list.append(key_frame_local_path)  # 添加到进度列表
            current_count = len(processed_list)  # 使用列表长度作为进度

            # 发送进度事件
            progress_percent = int((current_count / total_frames) * 100) if total_frames > 0 else 0
            await event_manager.send_event(
                state=state,
                event="key_frame_filter_node_stream",
                data={
                    "message": f"正在评分 - {progress_percent}% [Task {task_id}]",
                    "progress": progress_percent,
                    "current": current_count,
                    "total": total_frames,
                    "task_id": task_id,
                    "message_id": message_id
                }
            )
            await asyncio.sleep(0)

        except Exception as e:
            processed_list.append(f"error_{key_frame_local_path}")  # 即使出错也要记录进度
            logger.exception(f"Task {task_id} 处理图片 {key_frame_local_path} 时出错")

    # 为每个图片创建一个独立的 task
    tasks = []
    for i, key_frame_local_path in enumerate(key_frames_local_path_list):
        task = asyncio.create_task(process_single_image(key_frame_local_path, i + 1))
        tasks.append(task)

    # 等待所有 task 完成
    await asyncio.gather(*tasks)

    normal_up_key_frames = list(image_quality_list.keys())

    # 完成质量检测
    await event_manager.send_event(
        state=state,
        event="key_frame_filter_node_result",
        data={
            "message": f"图片评分完成，共处理 {total_frames} 张图片",
            "progress": 100,
            "current": total_frames,
            "total": total_frames,
            "normal_up_key_frames": normal_up_key_frames,
            "image_quality": image_quality_list,
            "message_id": message_id
        }
    )

    # 返回 Command，更新 state 并跳转到 "end" 节点
    return Command(
        update={
            "key_frame_filter_node_result": {
                "image_quality": image_quality_list,
                "normal_up_key_frames": normal_up_key_frames
            }
        },
        goto="text_and_image_combine_node",
    )


async def text_and_image_combine_node(state: State):
    """
    (异步) 图文合并节点：
    遍历所有筛选后的关键帧(列表)，将它们与时间戳匹配的ASR文本对齐。
    """
    logger.info("🎬 开始执行图文合并...")
    # 1. 获取输入数据
    # normal_up_key_frames 是一个 [ {"http://.../img.jpg": 1.234}, ... ] 格式的列表
    # 默认值应为 [], 而不是 {}
    keyframe_dict = state.get("key_frame_detect_node_result", {}).get("origin_key_frame_dict", {})
    keyframe_list = [
        {"local_path": local_path, "image_url": image_url}
        for local_path, image_url in keyframe_dict.items()
    ]
    if not keyframe_list:
        keyframe_list = [
            {"local_path": image_url, "image_url": image_url}
            for image_url in state.get("key_frame_detect_node_result", {}).get("origin_key_frame_oss_list", [])
        ]

    # ASR 文本块
    asr_chunks = state.get("asr_node_result", {}).get("asr_text", [])

    # 检查 keyframe_list 是否为空
    if not keyframe_list:
        logger.warning("没有找到合格的关键帧，图文合并跳过。")
        return Command(
            goto=END  # 假设跳到下一步
        )

    if not asr_chunks:
        logger.warning("没有找到ASR文本，将只生成包含图片和时间的叙事。")
        # 即使没有文本，我们仍然可以创建一个只有图像的叙事
        return Command(
            goto=END  # 假设跳到下一步
        )

    message_id = str(uuid.uuid4())
    # 发送节点启动事件
    await event_manager.send_event(
        state=state,
        event="text_and_image_combine_node_start",
        data={"message": "开始图文合并~", "message_id": message_id}
    )

    # 更新日志中的变量名
    logger.info(f"开始将 {len(keyframe_list)} 个关键帧与 {len(asr_chunks)} 个ASR文本块对齐...")

    combined_narrative = []

    logger.info(f"📦 关键帧列表: {json.dumps(keyframe_list, ensure_ascii=False)}")
    logger.info(f"📦 ars结果列表: {json.dumps(asr_chunks, ensure_ascii=False)}")
    # 2. 遍历每一个关键帧 (Frame-centric approach)
    # 遍历列表中的每一个字典元素
    total_frames = len(keyframe_list)
    for idx, keyframe in enumerate(keyframe_list, start=1):
        local_path = keyframe["local_path"]
        image_url = keyframe["image_url"]
        # 从 URL 中解析出该帧在视频中的时间点（毫秒）
        # 我们用 os.path.basename 来确保只解析文件名，防止URL路径干扰
        keyframe_time_ms = _parse_time_from_filename(os.path.basename(local_path))

        if keyframe_time_ms is None:
            logger.warning(f"无法从关键帧文件名 {local_path} 中解析时间，跳过此帧。")
            continue

        # 准备默认的空数据
        matched_chunk = None

        # 3. 遍历 ASR 文本块，查找匹配项
        for chunk in asr_chunks:
            # 检查关键帧的时间点是否落在 ASR 块的 [start, end] 区间内
            if chunk["start_time"] <= keyframe_time_ms <= chunk["end_time"]:
                # 找到了匹配！
                matched_chunk = chunk
                # 假设一个时间点只属于一个ASR块，找到后立即停止
                break

                # 4. 组装最终的元素 (无论是否找到文本)
        logger.info(f"🔍 处理关键帧: {image_url}")
        logger.info(f"⏰ 关键帧时间: {keyframe_time_ms}ms")

        if matched_chunk:
            narrative_element = {
                "frame_time": str(int(keyframe_time_ms)),  # 毫秒的字符串
                "frame_text": matched_chunk.get("text", ""),
                "image_url": image_url,
                "emotion": matched_chunk.get("emotion", ""),
                "emotion_degree": matched_chunk.get("emotion_degree", ""),
                "emotion_degree_score": matched_chunk.get("emotion_degree_score", ""),
                "emotion_score": matched_chunk.get("emotion_score", ""),
                "text_start_time": matched_chunk.get("start_time", ""),
                "text_end_time": matched_chunk.get("end_time", ""),
            }
        else:
            narrative_element = {
                "frame_time": str(int(keyframe_time_ms)),  # 毫秒的字符串
                "frame_text": "",  # 留空
                "image_url": image_url,
                "emotion": "",  # 留空
                "emotion_degree": "",  # 留空
                "emotion_degree_score": "",  # 留空
                "emotion_score": "",
                "text_start_time": "",
                "text_end_time": "",
            }
        combined_narrative.append(narrative_element)

        # 推送进度事件
        progress_percent = int((idx / total_frames) * 100) if total_frames > 0 else 100
        await event_manager.send_event(
            state=state,
            event="text_and_image_combine_node_stream",
            data={
                "message": f"正在合并图文 - {progress_percent}%",
                "progress": progress_percent,
                "current": idx,
                "total": total_frames,
                "message_id": message_id,
                "narrative_element": narrative_element
            }
        )
        await asyncio.sleep(0.5)  # 模拟异步操作

        # --- (内部逻辑结束) ---

    # 5. 完成处理，准备输出
    # （可选）如果需要，可以根据 frame_time 对
    # combined_narrative 进行排序，以确保叙事的时间顺序
    combined_narrative.sort(key=lambda x: int(x["frame_time"]))
    logger.info(f"📦 生成叙事元素: {json.dumps(combined_narrative, ensure_ascii=False)}")
    logger.info(f"🎉 图文合并完成，成功生成 {len(combined_narrative)} 条叙事元素。")

    update_data = {
        "text_and_image_combine_node_result": {
            "combined_narrative": combined_narrative
        }
    }

    # 发送完成事件
    await event_manager.send_event(
        state=state,
        event="text_and_image_combine_node_end",
        data={
            "message": f"🎉 图文合并完成，共生成 {len(combined_narrative)} 条叙事元素",
            "progress": 100,
            "current": len(combined_narrative),
            "total": len(combined_narrative),
            "combined_narrative": combined_narrative,
            "message_id": message_id
        }
    )

    # 假设下一步是调用LLM进行润色
    return Command(
        update=update_data,
        goto="xhs_style_node"
    )


async def vlm_choose_node(state: State):
    """
    VLM选择节点 - 根据视频字幕和帧列表，使用LLM选择关键图片并分析叙事逻辑
    """
    try:
        message_id = str(uuid.uuid4())
        # 发送节点启动通知
        await event_manager.send_event(
            state=state,
            event="vlm_choose_node_start",
            data={"message": "🎬 AI导演选取画面，分析叙事逻辑~", "message_id": message_id}
        )

        # 从state中获取视频数据
        video_full_transcript = state.get("video_full_transcript", "")
        video_frame_list = [
            {k: frame[k] for k in ['frame_time', 'frame_text', 'image_url'] if k in frame}
            for frame in state.get("text_and_image_combine_node_result", {}).get("combined_narrative", [])
        ]
        # 验证数据有效性
        if not video_full_transcript:
            return await create_error_command(state, "视频完整字幕为空，无法进行分析", message_id=message_id)

        if not video_frame_list:
            return await create_error_command(state, "视频帧列表为空，无法进行分析", message_id=message_id)

        # 构建帧列表字符串（仅作为文本补充信息）
        frame_list_str = ""
        for idx, frame in enumerate(video_frame_list, start=1):
            frame_list_str += f"""
    帧 {idx}:
    - 时间戳: {frame.get('frame_time', 'N/A')}
    - 对应字幕: {frame.get('frame_text', 'N/A')}
    """

        # 使用prompt模板
        prompt = get_prompt_template_formatted(
            "vlm_choose",
            VIDEO_FULL_TRANSCRIPT=video_full_transcript,
            FRAME_COUNT=len(video_frame_list),
            FRAME_LIST=frame_list_str
        )

        # 构建user消息的content部分。部分 OpenAI 兼容网关不稳定支持“纯图片”的用户消息，
        # 因此保留一段文本说明，让任务和图片处在同一条多模态消息里。
        user_content_parts = [{
            "type": "text",
            "text": f"请根据系统提示分析以下 {len(video_frame_list)} 帧视频画面，并按要求返回 JSON。"
        }]

        # 添加所有帧图片（这些是LLM实际能看到的图片）
        for idx, frame in enumerate(video_frame_list, start=1):
            image_url = frame.get("image_url", "")
            if image_url:
                user_content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })

        # 记录实际发送的图片数量
        actual_image_count = sum(1 for part in user_content_parts if part.get("type") == "image_url")
        logger.info(f"实际发送给LLM的图片数量: {actual_image_count}")

        # 若无有效图片，直接返回错误，避免空内容调用
        if actual_image_count == 0:
            return await create_error_command(state, "视频帧中无有效图片URL，无法分析", message_id=message_id)

        # 创建包含图片的用户消息
        user_message = HumanMessage(content=user_content_parts)

        langchain_messages = [
            SystemMessage(content=prompt),
            user_message,
        ]

        logger.info(f"开始调用LLM分析视频帧，共{len(video_frame_list)}帧，使用图片{actual_image_count}张")

        def _build_fallback_vlm_result() -> dict:
            total = len(video_frame_list)
            target_count = min(13, total)
            if target_count <= 0:
                selected_indices = []
            elif total <= target_count:
                selected_indices = list(range(1, total + 1))
            else:
                selected_indices = sorted({
                    max(1, min(total, round(1 + i * (total - 1) / (target_count - 1))))
                    for i in range(target_count)
                })

            selected_images = []
            for index in selected_indices:
                frame = video_frame_list[index - 1]
                frame_text = frame.get("frame_text") or "视频关键画面"
                selected_images.append({
                    "index": index,
                    "description": frame_text[:80],
                    "reason": "模型选图失败时的默认关键帧选择，按视频时间线保留主要叙事节点",
                    "content_tags": [],
                    "keywords": [],
                    "search_keywords": frame_text[:20],
                    "processing_operations": [],
                })

            return {
                "selected_images": selected_images,
                "story_flow": {
                    "summary": "按视频时间线自动选择关键帧，覆盖出行、景点、美食和日落等主要内容。",
                    "chapters": []
                },
                "fallback": True,
                "fallback_reason": "vlm_choose LLM call failed or returned invalid JSON"
            }

        try:
            response_content, token_usage = await vlm_service.call_llm_with_messages(
                "vlm_choose",  # 业务名称
                langchain_messages,
                global_user_message=state.get("global_user_message")
            )
        except Exception as e:
            logger.exception(f"VLM选图图片调用失败，尝试降级为纯文本选图: {e}")
            text_only_messages = [
                SystemMessage(content=prompt),
                HumanMessage(content="图片输入暂不可用。请仅根据系统提示中的完整字幕、帧时间戳和帧字幕信息，选择最适合生成小红书图文的关键帧，并严格返回 JSON。")
            ]
            try:
                response_content, token_usage = await vlm_service.call_llm_with_messages(
                    "vlm_choose",
                    text_only_messages,
                    global_user_message=state.get("global_user_message")
                )
            except Exception as text_error:
                logger.exception(f"VLM选图纯文本调用失败，使用默认选图方案: {text_error}")
                response_content = json.dumps(_build_fallback_vlm_result(), ensure_ascii=False)
                token_usage = None
        logger.info(f"LLM响应内容: {response_content}...")  # 只记录前500字符

        # 记录token使用
        if token_usage:
            add_token_usage_to_state(state, "VLM选择关键图片", "vlm_choose_node", token_usage)

        # 解析JSON响应
        try:
            result_data = json_repair.loads(response_content)

            # 验证结果结构
            if "selected_images" not in result_data:
                raise ValueError("响应中缺少selected_images字段")
            if "story_flow" not in result_data:
                raise ValueError("响应中缺少story_flow字段")

            # 验证选择的图片索引是否在有效范围内
            selected_images = result_data.get("selected_images", [])
            total_frames = len(video_frame_list)
            invalid_indices = []

            for img in selected_images:
                idx = img.get("index")
                if idx is None or idx < 1 or idx > total_frames:
                    invalid_indices.append(idx)

            if invalid_indices:
                logger.warning(f"LLM返回了无效的图片索引: {invalid_indices}, 有效范围是1-{total_frames}")
                # 过滤掉无效的索引
                result_data["selected_images"] = [
                    img for img in selected_images
                    if img.get("index") and 1 <= img.get("index") <= total_frames
                ]
                logger.info(f"已过滤无效索引，剩余{len(result_data['selected_images'])}张有效图片")

            # 统一为所有有效图片添加原始URL
            for img in result_data["selected_images"]:
                img["original_url"] = video_frame_list[img.get("index") - 1].get("image_url", "")
                img["frame_time"] = video_frame_list[img.get("index") - 1].get("frame_time", "")
            json.dumps(result_data, ensure_ascii=False)

            # 发送流式事件，包含每一张图片的详细信息
            for img in result_data["selected_images"]:
                await event_manager.send_event(
                    state=state,
                    event="vlm_choose_node_stream",
                    data={
                        "message": f"已选择图片{img.get('index')}",
                        "img": img,
                        "message_id": message_id
                    }
                )
                await asyncio.sleep(0.5)  # 模拟异步操作

            # 发送成功结果事件
            await event_manager.send_event(
                state=state,
                event="vlm_choose_node_end",
                data={
                    "message": f"✅ 内容图片选择完成，共选择 {len(result_data.get('selected_images', []))} 张",
                    "result": result_data,
                    "message_id": message_id
                }
            )

            logger.info(f"VLM选择完成，共选择{len(result_data.get('selected_images', []))}张图片")
            logger.info(f"VLM选择完成，选择的图片为{json.dumps(result_data, ensure_ascii=False)}")
            # 更新state，保存选择结果
            return Command(
                update={
                    "vlm_choose_result": result_data,
                    "messages": [AIMessage(
                        content=f"已分析视频并选择关键图片，共选择{len(result_data.get('selected_images', []))}张")],
                },
                goto=["poi_extract_node", "xhs_hot_content_node", "image_processing_node"],
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"解析LLM响应JSON失败，使用默认选图方案: {str(e)}, 响应内容: {response_content[:1000]}")
            result_data = _build_fallback_vlm_result()

            for img in result_data["selected_images"]:
                img["original_url"] = video_frame_list[img.get("index") - 1].get("image_url", "")
                img["frame_time"] = video_frame_list[img.get("index") - 1].get("frame_time", "")

            await event_manager.send_event(
                state=state,
                event="vlm_choose_node_end",
                data={
                    "message": f"✅ 内容图片选择完成，共选择 {len(result_data.get('selected_images', []))} 张（默认方案）",
                    "result": result_data,
                    "message_id": message_id
                }
            )

            return Command(
                update={
                    "vlm_choose_result": result_data,
                    "messages": [AIMessage(content=f"已使用默认方案选择关键图片，共选择{len(result_data.get('selected_images', []))}张")],
                },
                goto=["poi_extract_node", "xhs_hot_content_node", "image_processing_node"],
            )

    except Exception as e:
        error_msg = f"图片选择分析失败: {str(e)}"
        # 推送错误事件
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": error_msg, "traceback": traceback.format_exc(), "message_id": message_id}
        )
        return await create_error_command(state, error_msg, include_traceback=True, message_id=message_id)


async def generate_node(state: State):
    """
    小红书文案生成节点 - 根据VLM选择结果生成小红书文案
    """
    if "xhs_hot_content_node_result" not in state or "poi_extract_node_result" not in state:
        return
    try:
        message_id = str(uuid.uuid4())
        # 发送节点启动通知
        await event_manager.send_event(
            state=state,
            event="generate_node_start",
            data={"message": "✍️ 正在生成小红书文案~", "message_id": message_id}
        )

        # 从state中获取vlm_choose_node的输出结果
        vlm_choose_result = state.get("vlm_choose_result")

        if not vlm_choose_result:
            return await create_error_command(
                state=state,
                error_msg="未找到VLM选择结果，无法生成文案",
                message_id=message_id
            )
        xhs_hot_content_node_result = state.get("xhs_hot_content_node_result")
        if not xhs_hot_content_node_result:
            return await create_error_command(
                state=state,
                error_msg="未找到关键热词",
                message_id=message_id
            )
        # 将vlm_choose_result转换为JSON字符串，作为prompt的输入
        vlm_result_json = json.dumps(vlm_choose_result, ensure_ascii=False, indent=2)

        # 获取POI景点信息
        poi_extract_result = state.get("poi_extract_node_result", {})
        poi_result_json = json.dumps(poi_extract_result, ensure_ascii=False, indent=2)

        # 获取参考内容：先取 xhs_note_from_content，再取 xhs_note_from_style 对应的 value
        reference_content = None
        if state.get("xhs_note_from_content"):
            reference_content = state.get("xhs_note_from_content")
        elif state.get("xhs_note_from_style"):
            from .data_for_xhs_content import xhs_note_from_style_map
            style_key = state.get("xhs_note_from_style")
            if style_key in xhs_note_from_style_map:
                # 随机选择一个示例作为参考
                style_examples = xhs_note_from_style_map[style_key]
                if style_examples and len(style_examples) > 0:
                    reference_content = random.choice(style_examples)

        # 构建 Few Shot Examples 部分
        few_shot_section = ""
        if reference_content:
            few_shot_section = f"""# Few Shot Examples

以下是一些小红书文案的参考示例，请参考这些示例的风格和写作方式：

```
{reference_content}
```
"""
        hot_key = xhs_hot_content_node_result.get("xhs_hot_key_final_result", [])
        hot_dot_list = xhs_hot_content_node_result.get("xhs_hot_dot_final_result", [])
        title_list = [item['title'] for item in hot_dot_list]
        # 使用prompt模板
        prompt_kwargs = {
            "VLM_CHOOSE_RESULT": vlm_result_json,
            "FEW_SHOT_EXAMPLES": few_shot_section,
            "POI_INFO": poi_result_json,
            "HOT_KEY": hot_key,
            "HOT_DOT": title_list,
        }
        prompt = get_prompt_template_formatted(
            "xhs_caption_generate",
            **prompt_kwargs
        )

        logger.info("开始调用LLM生成小红书文案")

        langchain_messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="请根据上述视频分析结果，生成小红书文案。")
        ]

        response_content, token_usage = await vlm_service.call_llm_with_messages(
            "xhs_generate",  # 业务名称
            langchain_messages,
            global_user_message=state.get("global_user_message")
        )
        logger.info(f"LLM响应内容: {response_content[:500]}...")

        # 记录token使用
        add_token_usage_to_state(state, "小红书文案生成", "generate_node", token_usage)

        # 解析JSON响应
        try:
            caption_result = json_repair.loads(response_content)

            # 验证结果结构
            required_fields = ["title", "content", "hashtags", "full_caption"]
            missing_fields = [field for field in required_fields if field not in caption_result]

            if missing_fields:
                raise ValueError(f"响应中缺少必需字段: {', '.join(missing_fields)}")

            # 发送完成事件（摘要信息）
            await event_manager.send_event(
                state=state,
                event="generate_node_end",
                data={
                    "message": "🎉 文案生成完成",
                    "progress": 100,
                    "title": caption_result.get("title", ""),
                    "hashtags": caption_result.get("hashtags", []),
                    "full_caption": caption_result.get("full_caption", ""),
                    "message_id": message_id
                }
            )

            logger.info("小红书文案生成完成")

            # 更新state，保存文案结果
            return Command(
                update={
                    "generate_node_result": caption_result,
                    "messages": [AIMessage(
                        content=f"小红书文案生成完成\n\n标题：{caption_result.get('title', '')}\n\n{caption_result.get('full_caption', '')}")],
                },
                goto="xhs_final_text_node",
            )

        except (json.JSONDecodeError, ValueError) as e:
            error_msg = f"解析LLM响应JSON失败: {str(e)}"
            logger.error(f"{error_msg}, 响应内容: {response_content[:1000]}")
            # 推送错误事件
            await event_manager.send_event(
                state=state,
                event="error",
                data={
                    "error": error_msg,
                    "traceback": traceback.format_exc(),
                    "response_preview": response_content[:500],
                    "message_id": message_id
                }
            )
            return await create_error_command(state, error_msg, include_traceback=True, message_id=message_id)

    except Exception as e:
        error_msg = f"小红书文案生成失败: {str(e)}"
        # 推送错误事件
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": error_msg, "traceback": traceback.format_exc(), "message_id": message_id}
        )
        return await create_error_command(state, error_msg, include_traceback=True, message_id=message_id)


async def create_error_command(
        state: State,
        error_msg: str,
        include_traceback: bool = False,
        extra_data: dict = None,
        user_message: str = None,
        message_id: str = None
) -> Command:
    """
    创建错误返回的Command对象

    Args:
        state: 当前状态
        error_msg: 错误消息
        include_traceback: 是否包含traceback信息
        extra_data: 额外的错误数据（字典格式）
        user_message: 返回给用户的消息（如果不提供，则使用error_msg）

    Returns:
        包含错误消息的Command对象，跳转到end节点
    """
    logger.error(error_msg)
    error_data = {"error": error_msg}
    if include_traceback:
        error_data["traceback"] = traceback.format_exc()
    if extra_data:
        error_data.update(extra_data)
    if message_id:
        error_data["message_id"] = message_id

    await event_manager.send_event(
        state=state,
        event="error",
        data=error_data
    )

    return Command(
        update={"messages": [AIMessage(content=user_message or error_msg)]},
        goto=END,
    )


async def asr_node(state: State):
    """ASR语音识别节点 - 处理语音数据并转换为文本"""

    message_id = str(uuid.uuid4())
    # 发送节点启动通知
    await event_manager.send_event(state=state, event="asr_node_start",
                                   data={"message": "🎤 开始进行语音识别~", "message_id": message_id})

    try:
        video_path = state.get("video_path")

        # 提取音频
        logger.info(f"检测到视频path，开始提取音频: {video_path}")
        await event_manager.send_event(state=state, event="asr_node_stream",
                                       data={"message": f"📹 正在从视频提取音频~", "message_id": message_id})

        try:
            # 使用 main_service 提取音频
            audio_path = await main_service.extract_audio(
                video_path, current_processing_dir=Path(video_path).parent
            )

            if not audio_path:
                error_msg = "从视频提取音频失败"
                logger.error(error_msg)
                await event_manager.send_event(state=state, event="error",
                                               data={"error": error_msg, "message_id": message_id})
                return Command(
                    update={
                        "messages": [AIMessage(content="抱歉，从视频文件提取音频失败。")],
                    },
                    goto=END,
                )

            await event_manager.send_event(state=state, event="asr_node_stream",
                                           data={"message": f"📹 音频提取成功~", "message_id": message_id})
            # 上传音频文件到OBS
            audio_url = await main_service.upload_audio_file(audio_path)

            if not audio_url:
                error_msg = "音频文件上传失败"
                logger.error(error_msg)
                await event_manager.send_event(state=state, event="error",
                                               data={"error": error_msg, "message_id": message_id})
                return Command(
                    update={
                        "messages": [AIMessage(content="抱歉，音频文件上传失败。")],
                    },
                    goto=END,
                )

            logger.info(f"音频文件上传成功: {audio_url}")

        except Exception as e:
            error_msg = f"处理视频文件失败: {str(e)}"
            logger.error(error_msg)
            await event_manager.send_event(state=state, event="error",
                                           data={"error": error_msg, "message_id": message_id})
            return Command(
                update={
                    "messages": [AIMessage(content="抱歉，处理视频文件时出现错误。")],
                },
                goto=END,
            )

        logger.info(f"开始处理音频文件: {audio_url}")
        await event_manager.send_event(state=state, event="asr_node_stream",
                                       data={"message": f"🎧 正在识别语音内容~", "message_id": message_id})

        # 调用 ASRService 处理音频
        asr_result = await asr_service.process_audio(audio_url, max_wait_time=300)

        if not asr_result:
            error_msg = "ASR服务返回空结果"
            logger.warning(error_msg)
            await event_manager.send_event(state=state, event="status",
                                           data={"message": "⚠️ 语音识别未检测到内容", "message_id": message_id})
            return Command(
                update={
                    "messages": [AIMessage(content="语音识别完成，但未检测到语音内容。")],
                    "asr_result": []
                },
                goto=END,
            )

        # 处理成功，发送结果
        logger.info(f"ASR处理成功，识别到 {len(asr_result)} 个语音片段")

        # 构建文本摘要
        text_summary = ""
        for item in asr_result:
            if item.get("text"):
                text_summary += item["text"]
        text_summary = text_summary.strip()

        # 发送处理进度
        await event_manager.send_event(state=state, event="asr_node_end", data={
            "message": f"🎯 语音识别完成，识别到 {len(asr_result)} 个语音片段",
            "asr_text": asr_result,
            "text_summary": text_summary,
            "message_id": message_id})
        return Command(
            update={
                "asr_node_result": {
                    "asr_text": asr_result
                },
                "video_full_transcript": text_summary
            },
            goto="text_and_image_combine_node",
        )

    except Exception as e:
        error_msg = f"ASR处理异常: {str(e)}"
        logger.exception("asr_node_error")

        # 发送错误事件
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": error_msg, "traceback": traceback.format_exc(), "message_id": message_id}
        )

        return Command(
            update={
                "messages": "ASR处理异常",
            },
            goto=END,
        )


async def style_node(state: State):
    """
    :param state:
    :return:
    """
    message_id = str(uuid.uuid4())
    await event_manager.send_event(state=state, event="style_node_start",
                                   data={"message": "🎤 开始小红书风格定制处理~", "message_id": message_id})
    style_request_dict = state.get("style_request_dict", {})
    xhs_note_from_content = ""
    xhs_note_from_img_list = []
    if not style_request_dict:
        # 去embedding
        xhs_note_from_content = ""
    elif style_request_dict.get("type") == "appoint":
        style_key = style_request_dict.get("value")
        if style_key in xhs_note_from_style_map:
            # 随机选择一个示例作为参考
            style_examples = xhs_note_from_style_map[style_key]
            if style_examples and len(style_examples) > 0:
                xhs_note_from_content = random.choice(style_examples)
    elif style_request_dict.get("type") == "link":
        # 去搜索小红书帖子内容
        xhs_note_from_content = ""
        xhs_note_from_img_list = []

    await event_manager.send_event(state=state, event="style_node_end",
                                   data={"message": "🎤 已匹配对应小红书风格，处理完成~",
                                         "xhs_note_from_content": xhs_note_from_content,
                                         "xhs_note_from_img_list": xhs_note_from_img_list,
                                         "message_id": message_id})
    return Command(
        update={
            "xhs_note_from_content": xhs_note_from_content,
            "xhs_note_from_img_list": xhs_note_from_img_list
        },
        goto="text_and_image_combine_node"
    )


async def xhs_note_scoring_node(state: State) -> Command[Literal[END]]:
    """
    小红书帖子VLM评分节点 - 根据生成的小红书帖子进行多维度评分分析
    """
    try:
        # 从 state 获取最终汇总的文案与图片
        recoder = VideoWorkflowRecordCreate.create_with_extend_data(
            session_id=state.get("session_id"),
            workflow_id=state.get("workflow_id") or "1",
            video_url=state.get("video_url"),
            extend_data=ExtendData(state=state),
            status=VideoWorkflowStatus.SUCCESS
        )
        await video_workflow_service.create_or_update_workflow_record(state.get("session_id"), state.get("workflow_id"),
                                                                      recoder)
        xhs_final_text_node_result = state.get("xhs_final_text_node_result", {})

        if not xhs_final_text_node_result:
            logger.warning("未找到最终文案数据 xhs_final_text_node_result，评分节点跳过")
            return Command(
                update={"xhs_post_scoring_node_result": {"error": "No final note data found"}},
                goto=END
            )

        # 提取帖子内容（优先使用完整文案）
        post_content = xhs_final_text_node_result.get("full_caption", "")
        if not post_content:
            # 回退：组合标题与标签
            title = xhs_final_text_node_result.get("title", "")
            hashtags = xhs_final_text_node_result.get("hashtags", [])
            post_content = f"{title}\n\n{' '.join(hashtags)}".strip()

        # 获取帖子图片URL列表
        image_urls = xhs_final_text_node_result.get("images", []) or []

        # 验证数据有效性
        if not post_content.strip():
            logger.warning("帖子内容为空，无法进行评分")
            return Command(
                update={"xhs_post_scoring_node_result": {"error": "Empty post content"}},
                goto=END
            )

        if not image_urls:
            logger.warning("未找到帖子图片，将仅对文案进行评分")

        # 在开始事件中输出字数与图片数量
        await event_manager.send_event(
            state=state,
            event="xhs_note_scoring_start",
            data={
                "message": f"🎯 开始对生成的小红书帖子进行评分分析...（文案 {len(post_content)} 字符，{len(image_urls)} 张图片）"
            }
        )

        logger.info(f"开始评分小红书帖子，文案长度: {len(post_content)}, 图片数量: {len(image_urls)}")

        # 启动VLM评分为后台任务，并模拟约20-30秒的进度递增
        score_task = asyncio.create_task(
            vlm_service.score_xhs_post(
                "xhs_scoring",  # 业务名称
                post_content,
                image_urls,
                global_user_message=state.get("global_user_message")
            )
        )

        # 进度计划（每步约3秒）
        progress_plan = [
            (8, "正在预处理输入..."),
            (18, "正在分析帖子内容..."),
            (30, "正在提取图文特征..."),
            (45, "正在评估图片质量..."),
            (60, "正在评估文案质量..."),
            (75, "正在进行风格分析..."),
            (88, "正在汇总评分结果..."),
            (94, "正在生成优化建议..."),
            (97, "准备完成...")
        ]

        for pct, msg in progress_plan:
            if score_task.done():
                break
            try:
                await asyncio.sleep(3)
            except Exception:
                # 在取消或其他异常情况下继续尝试发送当前进度
                pass
            await event_manager.send_event(
                state=state,
                event="xhs_note_scoring_stream",
                data={
                    "message": msg,
                    "progress": pct
                }
            )

        # 等待评分任务完成（若已完成则立即返回结果）
        scoring_result, token_usage = await score_task

        # 记录token使用
        add_token_usage_to_state(state, "小红书帖子评分", "xhs_note_scoring_node", token_usage)

        # 校验返回值
        if not scoring_result or (isinstance(scoring_result, dict) and scoring_result.get("error")):
            err_msg = scoring_result.get("error") if isinstance(scoring_result, dict) else "Scoring failed"
            logger.error(f"VLM评分失败: {err_msg}")
            await event_manager.send_event(
                state=state,
                event="error",
                data={"error": f"xhs_note_scoring_node: {err_msg}"}
            )
            return Command(
                update={"xhs_post_scoring_node_result": {"error": err_msg}},
                goto=END
            )

        # 发送完成通知
        overall_score = scoring_result.get("overall_score", 0)
        grade = scoring_result.get("grade", "N/A")

        # 将评分细则输出到 SSE（结构化子项与分析文本）
        image_quality = scoring_result.get("image_quality", {}) or {}
        copywriting_quality = scoring_result.get("copywriting_quality", {}) or {}
        scoring_details = {
            "overall_score": overall_score,
            "grade": grade,
            "image_quality": {
                "total_score": image_quality.get("total_score"),
                "max_score": image_quality.get("max_score", 75),
                "analysis": image_quality.get("analysis", ""),
                "sub_scores": {
                    "cover_appeal": image_quality.get("sub_scores", {}).get("cover_appeal", {}),
                    "relevance": image_quality.get("sub_scores", {}).get("relevance", {}),
                    "aesthetics": image_quality.get("sub_scores", {}).get("aesthetics", {}),
                }
            },
            "copywriting_quality": {
                "total_score": copywriting_quality.get("total_score"),
                "max_score": copywriting_quality.get("max_score", 25),
                "analysis": copywriting_quality.get("analysis", ""),
                "sub_scores": {
                    "content_value": copywriting_quality.get("sub_scores", {}).get("content_value", {}),
                    "style": copywriting_quality.get("sub_scores", {}).get("style", {}),
                }
            },
            "summary": scoring_result.get("summary", {}),
        }

        await event_manager.send_event(
            state=state,
            event="xhs_note_scoring_end",
            data={
                "message": f"✅ 帖子评分完成！综合得分: {overall_score}/100 (等级: {grade})",
                "progress": 100,
                "scoring_details": scoring_details,
                # 统一使用安全序列化
                "state": to_json(serialize_state_for_event(state, include_messages=False)),
                "button_list": {
                    "重新生成": "vlm_choose_node",
                    "一键发布": "xhs_note_publish_node"
                }
            }
        )

        # 准备返回结果
        update_data = {
            "xhs_post_scoring_node_result": {
                "scoring_result": scoring_result,
                "scoring_details": scoring_details,
                "post_content": post_content,
                "images": image_urls,
                "image_count": len(image_urls),
                "overall_score": overall_score,
                "grade": grade,
                "title": xhs_final_text_node_result.get("title", ""),
                "hashtags": xhs_final_text_node_result.get("hashtags", []),
            }
        }
        state.update(update_data)
        recoder = VideoWorkflowRecordCreate.create_with_extend_data(
            session_id=state.get("session_id"),
            workflow_id=state.get("workflow_id") or "1",
            video_url=state.get("video_url") or "",
            extend_data=ExtendData(state=state),
            status="SUCCESS"
        )
        await video_workflow_service.create_or_update_workflow_record(state.get("session_id"), state.get("workflow_id"),
                                                                      recoder)
        logger.info(f"🎉 小红书帖子VLM评分完成，综合得分: {overall_score}/100, 等级: {grade}")

        return Command(
            update=update_data,
            goto=END
        )

    except Exception as e:
        logger.exception("小红书帖子评分节点执行失败")
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": str(e), "traceback": traceback.format_exc()}
        )

        return Command(
            update={"xhs_post_scoring_node_result": {"error": str(e)}},
            goto=END
        )


async def xhs_note_publish_node(state: State) -> Command[Literal[END]]:
    """
    小红书帖子发布节点 - 发布小红书帖子
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent  # 也可用你现有的图
    from ..llm.openrouter import create_llm_by_biz
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

    # 3) 选择发布 Agent 的模型，走项目通用的业务模型配置。
    llm = create_llm_by_biz("xhs_note_publish", temperature=0.1, max_tokens=4096)

    # 4) 用预制 ReAct 代理把模型和 MCP 工具串起来
    agent = create_react_agent(llm, tools)
    res = await agent.ainvoke({
        "messages": [
            ("user",
             "在小红书发布一条笔记：标题2025 AI Hackathon，正文是 2025 AI Hackathon 加油，图片：https://hackathon.obs.cn-north-4.myhuaweicloud.com/keyframe/1/scene_0006_frame_288_time_9600.0_sharp_518.jpg #周末去哪#标签。")
        ]
    })
    print(res)

    # 记录token使用(从agent响应中提取)
    try:
        # LangGraph agent的响应可能包含usage_metadata
        messages = res.get("messages", [])
        total_input = 0
        total_output = 0
        for msg in messages:
            if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                total_input += msg.usage_metadata.get('input_tokens', 0)
                total_output += msg.usage_metadata.get('output_tokens', 0)

        if total_input > 0 or total_output > 0:
            from ...service.vlm_service import TokenUsage
            token_usage = TokenUsage(
                input_tokens=total_input,
                output_tokens=total_output,
                total_tokens=total_input + total_output,
                model_name="azure/gpt-5-chat-2025-08-07"  # agent使用的模型
            )
            add_token_usage_to_state(state, "小红书帖子发布", "xhs_note_publish_node", token_usage)
    except Exception as e:
        logger.error(f"记录发布节点token失败: {e}")


async def collage_node(state: State):
    # 启动事件：通知前端正在进行图片拼接与组装
    message_id = str(uuid.uuid4())
    await event_manager.send_event(
        state=state,
        event="collage_node_start",
        data={
            "message": "🧩 正在拼接图片合集，请稍候片刻~",
            "message_id": message_id
        }
    )

    # 从state中获取视频数据
    video_full_transcript = state.get("video_full_transcript", "")
    video_frame_list = [
        {
            # Part 1: 复制 'frame_time', 'description' (如果存在)
            **{k: frame[k] for k in ['frame_time', 'description'] if k in frame},

            # Part 2: 添加 'index'
            'index': i,

            # Part 3: 映射 'reason' -> 'tip' (如果 'reason' 存在)
            **({'tip': frame['reason']} if 'reason' in frame else {}),

            # Part 4: 映射 'origin_url' -> 'image_url' (如果 'origin_url' 存在)
            **({'image_url': frame['processed_url']} if 'processed_url' in frame else {})
        }
        for i, frame in enumerate(state.get("image_processing_result", {}).get("processed_images", []), start=1)
    ]
    logger.info(f"拼图中参数 video_full_transcript:{json.dumps(video_full_transcript, ensure_ascii=False)}")
    logger.info(f"拼图中参数 video_frame_list:{json.dumps(video_frame_list, ensure_ascii=False)}")

    # 验证数据有效性
    if not video_full_transcript:
        return await create_error_command(state, "视频完整字幕为空，无法进行分析", message_id=message_id)

    if not video_frame_list:
        return await create_error_command(state, "视频帧列表为空，无法进行分析", message_id=message_id)

    # 交由 collage_util 封装：构建 KeyFrame Assembler 消息并并发执行
    unique_id = str(uuid.uuid4())
    logger.info(f"启动并发：LLM调用与图片下载，unique_id={unique_id}")
    key_frame_llm_task = asyncio.create_task(
        collage_util.call_keyframe_assembler_llm(
            video_full_transcript,
            video_frame_list,
            state
        )
    )
    download_image_task = asyncio.create_task(download_oss_images_to_local(video_frame_list, unique_id))

    poi_desc_list = collage_util.collect_poi_images(state)
    poi_img_uuid = str(uuid.uuid4())

    # 当 poi_desc_list 为空时，不启动相关任务，避免未定义变量导致 gather 报错
    poi_llm_task = None
    down_load_poi_task = None
    if poi_desc_list:
        poi_llm_task = asyncio.create_task(
            collage_util.call_poi_assembler_llm(
                video_full_transcript,
                poi_desc_list,
                state
            )
        )
        down_load_poi_task = asyncio.create_task(
            download_poi_img_list(poi_desc_list, poi_img_uuid)
        )

    if poi_llm_task and down_load_poi_task:
        (process_img_res_content, _), process_img_local_path, poi_img_local_path, (poi_img_res_content,
                                                                                   _) = await asyncio.gather(
            key_frame_llm_task,
            download_image_task,
            down_load_poi_task,
            poi_llm_task
        )
    else:
        # 无 POI 数据时，仅等待前两个任务，并设置合理的默认值
        (process_img_res_content, _), process_img_local_path = await asyncio.gather(
            key_frame_llm_task,
            download_image_task
        )
        poi_img_local_path = []
        # 统一空结果格式，后续解析与统计逻辑可正常运行
        poi_img_res_content = json.dumps({"function": []}, ensure_ascii=False)

    logger.info(f"process_img_res_contentLLM响应内容: {process_img_res_content}")
    logger.info(f"poi_img_res_contentLLM响应内容: {poi_img_res_content}")
    # 容错解析，防止上游返回空字符串/None 导致异常
    try:
        process_img_llm_result = json_repair.loads(process_img_res_content or "{}")
    except Exception:
        process_img_llm_result = {}
    try:
        poi_img_llm_result = json_repair.loads(poi_img_res_content or "{}")
    except Exception:
        poi_img_llm_result = {}

    total_items = len(process_img_llm_result.get("function", [])) + len(poi_img_llm_result.get("function", []))
    current_item = len(process_img_llm_result.get("function", []))
    # 处理拼图结果
    collage_results = await collage_util.process_collage_results(process_img_llm_result, state, process_img_local_path,
                                                                 unique_id, total_items, 0)

    # 当 POI 结果为空或本地路径为空时跳过处理，返回空列表
    collage_poi_results = []
    if poi_img_llm_result.get("function") and len(poi_img_llm_result.get("function", [])) > 0 and poi_img_local_path:
        collage_poi_results = await collage_util.process_collage_results(
            poi_img_llm_result,
            state,
            poi_img_local_path,
            poi_img_uuid,
            total_items,
            current_item
        )

    if isinstance(collage_results, list):
        if len(collage_results) >= 1 and collage_poi_results and len(collage_poi_results) > 0:
            # 插入到第二个元素（索引 1）
            collage_results.insert(1, collage_poi_results[0])
        elif collage_poi_results and len(collage_poi_results) > 0:
            # 如果原列表为空，直接追加
            collage_results.append(collage_poi_results[0])

    collage_results = collage_util.filter_collage_results(collage_results)

    # 提取所有成功的拼图URL
    successful_collages = [
        item for item in collage_results
        if item.get("success") and item.get("obs_url")
    ]
    successful_urls = [item["obs_url"] for item in successful_collages]

    # 结束事件：通知前端处理完成
    await event_manager.send_event(
        state=state,
        event="collage_node_end",
        data={
            "message": f"🎉 成功生成 {len(successful_urls)} 张图片合集！",
            "message_id": message_id,
            "collage_urls": successful_urls
        }
    )

    # 更新状态并跳转到下一节点
    logger.info(f"Collage node finished. State updated. Transitioning to xhs_final_text_node.")

    # 确保 img2img_usage_records 被保留到下一个节点
    # 注意：Command 中的 update 只包含本节点的新数据，不会自动继承 state 中的现有字段
    # 因此需要显式地将 img2img_usage_records 包含在 update 中
    update_dict = {
        "collage_node_result": {
            "collage_results": collage_results,
            "successful_urls": successful_urls
        }
    }

    # 保留 img2img_usage_records（如果存在）
    if state.get("img2img_usage_records"):
        update_dict["img2img_usage_records"] = state.get("img2img_usage_records")

    return Command(
        update=update_dict,
        goto="xhs_final_text_node"
    )


async def _process_single_image(
        image_info: dict,
        state: State,
        total_images: int,
        idx: int,
        message_id: str,
        process_list: list[int]
) -> tuple[dict | None, str | None]:
    """异步处理单张图片"""
    try:
        image_index = image_info.get("index")
        description = image_info.get("description", "")
        processing_operations = image_info.get("processing_operations", [])
        search_keywords = image_info.get("search_keywords", "")
        reason = image_info.get("reason", "")
        frame_time_str = str(image_info.get("frame_time", "")).strip()
        try:
            frame_time_ms = int(frame_time_str) if frame_time_str else None
        except Exception:
            frame_time_ms = None

        raw_original = str(image_info.get("original_url", "")).strip()
        original_image_url = raw_original.strip(" `\"'") if raw_original else ""
        if not original_image_url:
            combined_narrative = state.get("text_and_image_combine_node_result", {}).get("combined_narrative", [])
            if image_index and 1 <= image_index <= len(combined_narrative):
                original_image_url = combined_narrative[image_index - 1].get("image_url", "")

        if not original_image_url:
            logger.warning(f"无法找到索引 {image_index} 对应的图片URL")
            return None, f"图片 {image_index}: 跳过，未找到原始URL"

        processed_image_info = {
            "index": image_index,
            "description": description,
            "reason": reason,
            "frame_time": frame_time_str,
            "frame_time_ms": frame_time_ms,
            "original_url": original_image_url,
            "processed_url": original_image_url,
            "processing_operations": processing_operations,
            "search_keywords": search_keywords,
            "processing_results": {}
        }
        current_url = original_image_url
        log_messages = []

        # 1. 图像质量增强
        try:
            logger.info(f"开始图像质量增强处理: {current_url}")

            enhancement_result = await img2img_service.enhance_image_and_upload(current_url)

            if enhancement_result.get("success") and enhancement_result.get("oss_url"):
                final_url = enhancement_result["oss_url"]
                current_url = final_url
                processed_image_info["processing_results"]["quality_enhancement"] = {
                    "status": "success",
                    "result_url": final_url,
                    "source_url": enhancement_result.get("source_url", current_url),
                    "oss_url": enhancement_result.get("oss_url"),
                    "enhancement_method": "openrouter"
                }
                log_messages.append(f"图片 {image_index}: 图像质量增强成功")
                logger.info(f"图像质量增强成功: {processed_image_info['original_url']} -> {current_url}")
            else:
                processed_image_info["processing_results"]["quality_enhancement"] = {
                    "status": "failed",
                    "error": enhancement_result.get("message", "图像质量增强失败")
                }
                log_messages.append(f"图片 {image_index}: 图像质量增强失败")
        except Exception as e:
            logger.exception(f"图像质量增强处理异常: {e}")
            processed_image_info["processing_results"]["quality_enhancement"] = {"status": "error", "error": str(e)}
            log_messages.append(f"图片 {image_index}: 图像质量增强处理异常 - {str(e)}")

        # 2. 图像搜索替换
        if "image_search" in processing_operations and search_keywords:
            try:
                logger.info(f"开始图像搜索替换处理: 关键词={search_keywords}")
                search_result = await image_search_service.get_best_image(search_keywords)
                if search_result and search_result.get("status") == "SUCCESS" and search_result.get("best_image"):
                    best_image = search_result["best_image"]
                    new_image_url = best_image.get("imageUrl")
                    if not new_image_url:
                        new_image_url = best_image.get("processed_url") or best_image.get("original_url")
                    if new_image_url:
                        current_url = new_image_url
                        processed_image_info["processing_results"]["image_search"] = {
                            "status": "success",
                            "result_url": new_image_url,
                            "search_keywords": search_keywords,
                            "image_info": {
                                "title": best_image.get("titleShow", ""),
                                "score": best_image.get("auroraScore", 0),
                                "width": best_image.get("width", 0),
                                "height": best_image.get("height", 0),
                                "original_url": best_image.get("originImageUrl", "")
                            },
                            "total_candidates": search_result.get("total_images", 0),
                            "qualified_candidates": search_result.get("qualified_images", 0)
                        }
                        log_messages.append(
                            f"图片 {image_index}: 图像搜索替换成功 (关键词: {search_keywords}, 评分: {best_image.get('auroraScore', 0)})")
                        logger.info(f"图像搜索替换成功: {search_keywords} -> {new_image_url}")
                    else:
                        processed_image_info["processing_results"]["image_search"] = {
                            "status": "failed",
                            "error": "搜索结果中没有有效的图片URL",
                            "search_keywords": search_keywords
                        }
                        log_messages.append(f"图片 {image_index}: 图像搜索替换失败 - 没有有效的图片URL")
                else:
                    error_message = search_result.get("message", "搜索失败") if search_result else "搜索服务无返回"
                    processed_image_info["processing_results"]["image_search"] = {
                        "status": "failed",
                        "error": error_message,
                        "search_keywords": search_keywords
                    }
                    log_messages.append(
                        f"图片 {image_index}: 图像搜索替换失败 - {error_message}")
                    logger.warning(f"图像搜索失败: {search_result}")
            except Exception as e:
                logger.exception(f"图像搜索替换处理异常: {e}")
                processed_image_info["processing_results"]["image_search"] = {
                    "status": "error",
                    "error": str(e),
                    "search_keywords": search_keywords
                }
                log_messages.append(f"图片 {image_index}: 图像搜索替换处理异常 - {str(e)}")

        processed_image_info["processed_url"] = current_url
        process_list.append(idx)

        progress_percent = int((len(process_list) / total_images) * 100) if process_list else 0
        await event_manager.send_event(
            state=state,
            event="image_processing_node_stream",
            data={
                "message": f"已处理第 {idx}/{total_images} 张图片",
                "progress": progress_percent,
                "current": idx,
                "total": total_images,
                "image_index": image_index,
                "original_url": original_image_url,
                "frame_time": frame_time_str,
                "processed_url": current_url,
                "processing_results": processed_image_info.get("processing_results", {}),
                "message_id": message_id
            }
        )

        return processed_image_info, ", ".join(log_messages) if log_messages else f"图片 {image_index}: 处理成功"

    except Exception as e:
        logger.exception(f"处理图片 {idx} 时发生异常: {e}")
        return None, f"图片 {idx}: 处理异常 - {str(e)}"


async def image_processing_node(state: State) -> Command[Literal[END, "generate", "collage_node"]]:
    """
    图片处理节点 - 根据vlm_choose的结果对图片进行相应的处理操作
    支持：去水印、图像质量增强、图像搜索替换
    """
    try:
        time.sleep(1)
        message_id = str(uuid.uuid4())
        vlm_result = state.get("vlm_choose_result", {})
        selected_images = vlm_result.get("selected_images", [])

        if not selected_images:
            logger.warning("没有找到需要处理的图片")
            return Command(
                update={"image_processing_result": {"processed_images": [], "processing_log": []}},
                goto="generate"
            )

        await event_manager.send_event(
            state=state,
            event="image_processing_node_start",
            data={"message": "🎨 开始增强对应场景的图片~", "message_id": message_id}
        )

        total_images = len(selected_images)
        logger.info(f"开始并发处理 {total_images} 张图片")

        tasks = []
        process_list = []
        for idx, image_info in enumerate(selected_images, 1):
            # 为每个任务设置60秒的超时
            task = asyncio.wait_for(
                _process_single_image(image_info, state, total_images, idx, message_id, process_list),
                timeout=120.0
            )
            tasks.append(task)

        # 使用 return_exceptions=True 来收集所有结果，包括异常
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_images = []
        processing_log = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                if isinstance(res, asyncio.TimeoutError):
                    error_msg = f"图片 {i + 1}: 处理超时 (超过60秒)"
                    logger.error(error_msg)
                    processing_log.append(error_msg)
                else:
                    error_msg = f"图片 {i + 1}: 处理时发生未知异常: {res}"
                    logger.exception(error_msg)
                    processing_log.append(error_msg)
            elif res and res[0]:
                processed_images.append(res[0])
                if res[1]:
                    processing_log.append(res[1])

        await event_manager.send_event(
            state=state,
            event="image_processing_node_end",
            data={
                "message": f"✅ 图片处理完成，共处理 {len(processed_images)} 张图片",
                "progress": 100,
                "processed_images": processed_images,
                "processed_count": len(processed_images),
                "total_count": total_images,
                "processing_log": processing_log,
                "message_id": message_id
            }
        )

        processing_result = {
            "processed_images": processed_images,
            "processing_log": processing_log,
            "summary": {
                "total_images": total_images,
                "processed_count": len(processed_images),
                "watermark_removal_count": len([img for img in processed_images
                                                if "watermark_removal" in img.get("processing_operations", [])]),
                "quality_enhancement_count": len([img for img in processed_images
                                                  if "quality_enhancement" in img.get("processing_operations", [])]),
                "image_search_count": len([img for img in processed_images
                                           if "image_search" in img.get("processing_operations", [])])
            }
        }

        logger.info(f"图片处理节点完成，处理结果: {json.dumps(processing_result, ensure_ascii=False)}")

        update_dict = {
            "image_processing_result": processing_result
        }

        # 保留 img2img_usage_records（如果存在）
        if state.get("img2img_usage_records"):
            update_dict["img2img_usage_records"] = state.get("img2img_usage_records")

        return Command(
            update=update_dict,
            goto="collage_node"
        )
    except Exception as e:
        logger.exception(f"图片处理节点发生严重错误: {e}")
        return create_error_command(
            message="图片处理节点发生严重错误",
            traceback=traceback.format_exc(),
            extra_data={"error": str(e)}
        )

    except Exception as e:
        logger.exception(f"图片处理节点异常: {e}")
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": f"图片处理失败: {str(e)}", "traceback": traceback.format_exc(), "message_id": message_id}
        )

        return await create_error_command(
            state=state,
            error_msg=f"图片处理失败: {str(e)}",
            include_traceback=True,
            message_id=message_id
        )


async def xhs_final_text_node(state: State):
    """
    最终汇总节点 - 汇总生成的文案与拼图图片
    从 State 中读取：
    - generate_node_result: 包含标题、完整文案、hashtags 等
    - collage_node_result: 包含拼图结果列表及上传到 OSS 的链接

    输出：
    - xhs_final_text_node_result: { title, full_caption, hashtags, images, image_count, uploaded_count, image_tips }
    并发送统一的 SSE 事件：start/end，携带 message_id。
    """
    message_id = str(uuid.uuid4())

    # 发送启动事件
    await event_manager.send_event(
        state=state,
        event="xhs_final_text_node_start",
        data={"message": "🧾 正在汇总文案与图片~", "message_id": message_id}
    )

    try:
        generate_node_result = state.get("generate_node_result", {
            "content": "姐妹们！吃饭逛街看书一次满足的地方我找到了！在常州迎春路的红盒子，不仅能吃到让人上头的美食，还能顺便去顶楼图书馆拍美照\n\n **甜品开场**\n一进门就被那碗浓稠的黑芝麻糊甜品吸引，香气扑鼻，入口丝滑。抹茶控也有福利，绿色抹茶酱厚厚一层，苦甜交织，幸福感爆棚！\n\n **主菜惊喜**\n招牌冰川茄子外酥里嫩，金黄的外皮咬下去嘎嘣脆，芝麻的香气更是锦上添花。爆炒猪肝色泽红亮，配着青蒜和辣椒，鲜香辣交融，超下饭！\n\n **暖心主食**\n蒸蛋拌饭是我心中的治愈系担当，金黄蒸蛋覆盖在白米饭上，每一勺都是细腻嫩滑的享受。\n\n **美食后的文化之旅**\n吃饱后走进红盒子顶楼的现代风格图书馆，圆形天窗洒下的光线让整片书海温柔且有质感。别忘了看看悬挂的绿色书本艺术装置，拍照超有创意！还有红色打卡墙，常州字样和圆灯饰特别适合拍OOTD。\n\n打卡攻略\n红盒子图书馆：常州市迎春路红盒子建筑顶楼 | 周一至周日 9:00-18:00 | 设计感满满，适合拍照和静心阅读\n\n **小Tips**\n建议中午来，先吃饭再逛图书馆，光线最好！拍照记得带鲜艳的衣服，和红色楼梯、打卡墙更配哦。\n\n吃+拍+读一次搞定，周末就安排这里吧你们去过红盒子了吗？留言告诉我你的必点菜！",
            "full_caption": "姐妹们！吃饭逛街看书一次满足的地方我找到了！在常州迎春路的红盒子，不仅能吃到让人上头的美食，还能顺便去顶楼图书馆拍美照\n\n **甜品开场**\n一进门就被那碗浓稠的黑芝麻糊甜品吸引，香气扑鼻，入口丝滑。抹茶控也有福利，绿色抹茶酱厚厚一层，苦甜交织，幸福感爆棚！\n\n **主菜惊喜**\n招牌冰川茄子外酥里嫩，金黄的外皮咬下去嘎嘣脆，芝麻的香气更是锦上添花。爆炒猪肝色泽红亮，配着青蒜和辣椒，鲜香辣交融，超下饭！\n\n **暖心主食**\n蒸蛋拌饭是我心中的治愈系担当，金黄蒸蛋覆盖在白米饭上，每一勺都是细腻嫩滑的享受。\n\n **美食后的文化之旅**\n吃饱后走进红盒子顶楼的现代风格图书馆，圆形天窗洒下的光线让整片书海温柔且有质感。别忘了看看悬挂的绿色书本艺术装置，拍照超有创意！还有红色打卡墙，常州字样和圆灯饰特别适合拍OOTD。\n\n打卡攻略\n红盒子图书馆：常州市迎春路红盒子建筑顶楼 | 周一至周日 9:00-18:00 | 设计感满满，适合拍照和静心阅读\n\n **小Tips**\n建议中午来，先吃饭再逛图书馆，光线最好！拍照记得带鲜艳的衣服，和红色楼梯、打卡墙更配哦。\n\n吃+拍+读一次搞定，周末就安排这里吧你们去过红盒子了吗？留言告诉我你的必点菜！\n\n#常州美食 #探店分享 #图书馆打卡 #冰川茄子 #生活方式 #周末去哪儿 #本地生活 #美食探店",
            "hashtags": ["#常州美食", "#探店分享", "#图书馆打卡", "#冰川茄子", "#生活方式", "#周末去哪儿", "#本地生活",
                         "#美食探店"], "title": "常州红盒子：美食+图书馆一次打卡！"})
        collage_node_result = state.get("collage_node_result", {"collage_results": [
            {"function_name": "create_collage_9_images",
             "obs_url": "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110736_collage_1_create_collage_9_images.jpg",
             "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_1_create_collage_9_images.jpg",
             "params": {"output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_1_create_collage_9_images.jpg",
                        "path_g1": "..\\data\\collage_img\\ce688c88\\frame_001.jpg",
                        "path_g2": "..\\data\\collage_img\\ce688c88\\frame_002.jpg",
                        "path_g3": "..\\data\\collage_img\\ce688c88\\frame_003.jpg",
                        "path_g4": "..\\data\\collage_img\\ce688c88\\frame_006.jpg",
                        "path_g5": "..\\data\\collage_img\\ce688c88\\frame_007.jpg",
                        "path_g6": "..\\data\\collage_img\\ce688c88\\frame_008.jpg",
                        "path_g7": "..\\data\\collage_img\\ce688c88\\frame_009.jpg",
                        "path_g8": "..\\data\\collage_img\\ce688c88\\frame_010.jpg",
                        "path_hero": "..\\data\\collage_img\\ce688c88\\frame_004.jpg"},
             "reason": "九宫格概览，将情感高潮(蒸蛋拌饭特写 index 4)置于顶部英雄位置，串联美食与红盒子图书馆的完整故事。",
             "success": True, "unique_id": "ce688c88", "upload_success": True},
            {"function_name": "create_collage_2_images",
             "obs_url": "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110738_collage_2_create_collage_2_images.jpg",
             "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_2_create_collage_2_images.jpg",
             "params": {"output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_2_create_collage_2_images.jpg",
                        "path_bottom": "..\\data\\collage_img\\ce688c88\\frame_002.jpg",
                        "path_top": "..\\data\\collage_img\\ce688c88\\frame_001.jpg"},
             "reason": "展示冰川茄子的前后变化，将未淋酱汁的茄子(index 1)置于顶部，淋酱后的成品(index 2)置于底部，形成鲜明对比。",
             "success": True, "unique_id": "ce688c88", "upload_success": True},
            {"function_name": "create_collage_1_images",
             "obs_url": "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110739_collage_3_create_collage_1_images.jpg",
             "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_3_create_collage_1_images.jpg",
             "params": {"output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_3_create_collage_1_images.jpg",
                        "path_main": "..\\data\\collage_img\\ce688c88\\frame_003.jpg"},
             "reason": "单图突出爆炒猪肝的色泽与食欲感(index 3)，强化美食主题的核心菜品之一。", "success": True,
             "unique_id": "ce688c88", "upload_success": True}, {"function_name": "create_collage_3_images",
                                                                "obs_url": "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110741_collage_4_create_collage_3_images.jpg",
                                                                "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_4_create_collage_3_images.jpg",
                                                                "params": {
                                                                    "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_4_create_collage_3_images.jpg",
                                                                    "path_left": "..\\data\\collage_img\\ce688c88\\frame_004.jpg",
                                                                    "path_right_bottom": "..\\data\\collage_img\\ce688c88\\frame_006.jpg",
                                                                    "path_right_top": "..\\data\\collage_img\\ce688c88\\frame_005.jpg"},
                                                                "reason": "展示蒸蛋拌饭的不同食用状态，将整碗蒸蛋(index 4)置于左侧主图，右上放拌饭状态(index 5)，右下放舀起的细节(index 6)，形成过程感。",
                                                                "success": True, "unique_id": "ce688c88",
                                                                "upload_success": True},
            {"function_name": "create_collage_1_images",
             "obs_url": "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110742_collage_5_create_collage_1_images.jpg",
             "output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_5_create_collage_1_images.jpg",
             "params": {"output_path": "..\\data\\collage_img\\ce688c88\\output\\collage_5_create_collage_1_images.jpg",
                        "path_main": "..\\data\\collage_img\\ce688c88\\frame_007.jpg"},
             "reason": "单图突出红盒子图书馆的内部空间感(index 7)，传递安静与文化氛围。", "success": True,
             "unique_id": "ce688c88", "upload_success": True},
            {"error": "create_collage_4_images() missing 1 required positional argument: 'path_br'",
             "function_name": "create_collage_4_images",
             "reason": "展示红盒子外观与内部艺术装置，将外观(index 8)置于左上，悬挂书本装置(index 9)置于右上，红色阶梯近景(index 10)置于左下，阶梯远景(index 11)置于右下，形成完整空间导览。",
             "success": False}, {"error": "没有有效的图片参数", "function_name": "create_collage_1_images",
                                 "reason": "单图突出红色阶梯的全景与人物互动感(index 11)，强化打卡氛围。",
                                 "success": False}], "successful_urls": [
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110736_collage_1_create_collage_9_images.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110738_collage_2_create_collage_2_images.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110739_collage_3_create_collage_1_images.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110741_collage_4_create_collage_3_images.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251109_110742_collage_5_create_collage_1_images.jpg"]})

        # 提取文案字段
        title = generate_node_result.get("title", "")
        full_caption = generate_node_result.get("full_caption", "")
        hashtags = generate_node_result.get("hashtags", [])

        # 组装图片列表（优先使用已上传的 OSS 链接）
        images = []
        image_tips = []
        collage_results = collage_node_result.get("collage_results", [])
        for item in collage_results:
            if item.get("success"):
                url = item.get("obs_url") or item.get("output_path") or item.get("local_output_path")
                if url:
                    images.append(url)
                tip = item.get("tip") or item.get("reason")
                if tip:
                    image_tips.append(tip)
                else:
                    image_tips.append("景点拼图")

        final_note = {
            "title": title,
            "full_caption": full_caption,
            "hashtags": hashtags,
            "images": images,
            "image_count": len(images),
            "uploaded_count": len(images),
            "image_tips": image_tips,
        }
        # 发送完成事件
        await event_manager.send_event(
            state=state,
            event="xhs_final_text_node_end",
            data={
                "message": f"✅ 汇总完成，图片 {len(images)} 张",
                "final_note": final_note,
                "message_id": message_id,
                "session_id": state.get("session_id")
            }
        )

        # 确保 img2img_usage_records 被保留到下一个节点
        update_dict = {
            "xhs_final_text_node_result": final_note,
            "messages": [AIMessage(content=f"汇总完成，已生成最终文案与图片\n\n标题：{title}\n\n{full_caption}")]
        }
        if state.get("img2img_usage_records"):
            update_dict["img2img_usage_records"] = state.get("img2img_usage_records")

        return Command(
            update=update_dict,
            goto="xhs_cover_opt_node"
        )

    except Exception as e:
        # 推送错误事件并返回统一错误 Command
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": f"汇总失败: {str(e)}", "traceback": traceback.format_exc(), "message_id": message_id}
        )
        return await create_error_command(
            state=state,
            error_msg=f"汇总失败: {str(e)}",
            include_traceback=True,
            message_id=message_id
        )


def deep_copy_state(state: State):
    try:
        state_dict = copy.deepcopy(state)

        # 如果包含 AIMessage 等不可序列化对象
        if "messages" in state_dict:
            state_dict.pop("messages")

        print(json.dumps(state_dict, indent=2, ensure_ascii=False))
        logger.info("deep_copy_state ==> " + json.dumps(state_dict, ensure_ascii=False))
    except Exception as e:
        logger.exception(f"deep_copy_state: {e}")
