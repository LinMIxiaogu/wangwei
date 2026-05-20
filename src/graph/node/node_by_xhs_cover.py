import asyncio
import logging
import traceback
import uuid
from typing import Literal

from langgraph.graph import END
from langgraph.types import Command

from src.prompts.template import get_prompt_template_formatted
from ..event.manager import event_manager
from ..state.types import State
from ...service.img2img_service import img2img_service
from ...service.obs_service import obs_service

logger = logging.getLogger(__name__)


async def xhs_cover_opt_node(state: State) -> Command[Literal[END, "xhs_note_scoring_node"]]:
    """
    小红书头图优化节点

    输入：
      - xhs_final_text_node_result: { title, full_caption, hashtags, images, image_tips, ... }

    处理：
      - 使用图生图服务对第一张图片进行小红书风格优化（竖版 4:5）
      - 成功则替换 images[0]，并追加优化提示；失败或异常则添加提示并保留原图

    输出：
      - 更新后的 xhs_final_text_node_result
      - 跳转到 "xhs_note_scoring_node"
    """
    message_id = str(uuid.uuid4())

    try:
        final_note = state.get("xhs_final_text_node_result") or {}

        if not final_note:
            logger.warning("未找到 xhs_final_text_node_result，封面优化节点跳过")
            return Command(update={}, goto="xhs_note_scoring_node")

        title = final_note.get("title", "")
        full_caption = final_note.get("full_caption", "")
        hashtags = final_note.get("hashtags", [])
        images = final_note.get("images", []) or []
        image_tips = final_note.get("image_tips", []) or []

        # 有图片才进行封面优化
        if images:
            head_url = images[0]
            try:
                await event_manager.send_event(
                    state=state,
                    event="xhs_cover_opt_start",
                    data={
                        "message": "🎯 正在优化封面图为小红书风格",
                        "message_id": message_id,
                        "origin_head_url": head_url
                    }
                )

                cover_prompt = get_prompt_template_formatted(
                    "xhs_cover_optimization",
                    TITLE=title or "",
                    FULL_CAPTION=full_caption or "",
                    HASHTAGS=" ".join(hashtags) if isinstance(hashtags, list) else (hashtags or "")
                )

                # 将耗时的图生图处理放入后台任务，并在 30-40s 内持续推送进度
                task = asyncio.create_task(
                    img2img_service.process_image(
                        prompt=cover_prompt,
                        source_image=head_url
                    )
                )

                # 约 35s 的进度模拟，每 3.5s 推送一次，共 10 次
                progress_plan = [
                    (5, "解析文案与标签，规划视觉元素"),
                    (12, "设定小红书风格基调与配色"),
                    (20, "提取主体物与构图规则"),
                    (30, "生成初版封面布局"),
                    (40, "优化光影与清晰度"),
                    (50, "增强画面氛围与细节"),
                    (62, "适配 4:5 竖版比例"),
                    (74, "提升主视觉吸引力"),
                    (86, "检查边缘与纹理一致性"),
                    (95, "最终润色与输出中")
                ]

                for pct, msg in progress_plan:
                    # 如果任务已提前完成则停止模拟
                    if task.done():
                        break
                    await event_manager.send_event(
                        state=state,
                        event="xhs_cover_opt_stream",
                        data={
                            "message": msg,
                            "progress": pct,
                            "message_id": message_id
                        }
                    )
                    await asyncio.sleep(3.5)

                cover_result = await task
                # 记录图生图花费
                from .node import add_img2img_usage_to_state
                add_img2img_usage_to_state(state, "封面图优化", "xhs_cover_opt_node", cover_result)

                if cover_result.get("status") == "SUCCESS" and cover_result.get("media_url"):
                    source_url = cover_result["media_url"]
                    oss_url = await obs_service.upload_from_url(source_url)
                    final_url = oss_url or source_url
                    images[0] = final_url
                    image_tips.append("封面图已进行小红书风格优化")
                    await event_manager.send_event(
                        state=state,
                        event="xhs_cover_opt_end",
                        data={
                            "message": "✅ 封面图优化完成",
                            "origin_head_url": head_url,
                            "result_head_url": final_url,
                            "message_id": message_id,
                        }
                    )
                else:
                    image_tips.append("封面图风格优化失败，已保留原图")
                    await event_manager.send_event(
                        state=state,
                        event="xhs_cover_opt_end",
                        data={"message": "⚠️ 封面图优化失败，保留原图", "message_id": message_id}
                    )

            except Exception as e:
                logger.exception(f"封面图风格优化异常: {e}")
                image_tips.append(f"封面图风格优化异常: {str(e)}")
                await event_manager.send_event(
                    state=state,
                    event="error",
                    data={"error": f"封面图风格优化异常: {str(e)}"}
                )

            # 将更新写回到 final_note，并同步到 state
            final_note.update({
                "images": images,
                "image_tips": image_tips,
                "image_count": len(images),
                "uploaded_count": len(images)
            })

        # 确保 img2img_usage_records 被保留到下一个节点
        update_dict = {"xhs_final_text_node_result": final_note}
        if state.get("img2img_usage_records"):
            update_dict["img2img_usage_records"] = state.get("img2img_usage_records")

        return Command(update=update_dict, goto="xhs_note_scoring_node")

    except Exception as e:
        logger.exception(f"封面优化节点发生严重错误: {e}")
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": f"封面优化节点异常: {str(e)}", "traceback": traceback.format_exc()}
        )
        # 即使异常也不中断流程，进入评分节点，但保留 img2img_usage_records
        error_update = {}
        if state.get("img2img_usage_records"):
            error_update["img2img_usage_records"] = state.get("img2img_usage_records")
        return Command(update=error_update, goto="xhs_note_scoring_node")
