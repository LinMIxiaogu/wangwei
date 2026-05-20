import asyncio
import json
import logging
from typing import Literal, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from src.graph.llm.config import llm_factory
from src.graph.llm.openrouter import create_llm_by_biz
from src.prompts.template import get_prompt_template_formatted
from src.service.vlm_service import vlm_service


async def stream_updated_xhs_content(
        title: str,
        content: str,
        field: Literal["title", "content"],
        session_id: Optional[str] = None,
        requirements: Optional[str] = None,
):
    """返回 SSE 文本流：事件名为 update_start / update_stream / update_end / update_error。"""

    try:
        if field not in ("title", "content"):
            error_payload = json.dumps(
                {"message": "field 必须是 'title' 或 'content'"}, ensure_ascii=False
            )
            yield f"event: update_error\ndata: {error_payload}\n\n"
            return

        if field == "title":
            instruction = (
                "基于上述内容生成一个更吸引人的中文标题，简洁有力、口语化，避免过度营销和敏感词。"
            )
        else:
            instruction = (
                "基于上述标题与正文，重新生成更高质量的中文正文：结构清晰、有层次，语气真实生活化，"
            )

        field_desc = "标题" if field == "title" else "正文"

        # 根据 session_id 追加风格与原始字幕到提示词
        style_text = ""
        transcript_text = ""
        if session_id:
            try:
                from src.service.xhs_detail_service import get_xhs_detail
                detail = await get_xhs_detail(session_id)
                if detail.get("status") == 0:
                    data = detail.get("data", {})
                    style_text = data.get("xhs_note_from_style", "") or ""
                    transcript_text = data.get("video_full_transcript", "") or ""
            except Exception as e:
                logging.exception(f"fetch xhs_detail failed: {str(e)}")

        prompt = get_prompt_template_formatted(
            "xhs_content_title_update",
            TITLE=title,
            CONTENT=content,
            FIELD=field_desc,
            INSTRUCTION=instruction,
            ORIGIN_TEXT=transcript_text,
            STYLE=style_text,
        )
        llm = create_llm_by_biz("updated_xhs_content")
        langchain_messages = [SystemMessage(content=prompt)]
        # 用户优化要求以用户消息形式传递，避免与系统提示割裂
        if requirements and requirements.strip():
            langchain_messages.append(HumanMessage(content=requirements.strip()))

        # 发送开始事件，便于前端状态控制
        yield f"event: update_start\ndata: {json.dumps({'field': field}, ensure_ascii=False)}\n\n"

        aggregated: list[str] = []
        # 优先使用事件流（支持 on_llm_new_token）
        try:
            async for event in llm.astream_events(langchain_messages, version="v1"):
                if event.get("event") == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue
                    text = getattr(chunk, "content", None)
                    if not text:
                        continue
                    aggregated.append(text)
                    yield f"event: update_stream\ndata: {text}\n\n"
        except Exception:
            # 兼容不支持 astream_events 的模型
            try:
                async for chunk in llm.astream(langchain_messages):
                    text = getattr(chunk, "content", None)
                    if text is None:
                        text = str(chunk)
                    if isinstance(text, list):
                        s = "".join(
                            seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in text
                        )
                    else:
                        s = str(text)
                    if s.strip():
                        aggregated.append(s)
                        yield f"event: update_stream\ndata: {s}\n\n"
            except Exception:
                # 回退为一次性生成
                resp = await llm.ainvoke(langchain_messages)
                text = getattr(resp, "content", resp)
                if isinstance(text, list):
                    s = "".join(
                        seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in text
                    )
                else:
                    s = str(text)
                if s.strip():
                    aggregated.append(s)
                    yield f"event: update_stream\ndata: {s}\n\n"

        final_text = "".join(aggregated).strip()
        yield f"event: update_end\ndata: {final_text}\n\n"
    except Exception as e:
        error_payload = json.dumps({"message": str(e)}, ensure_ascii=False)
        yield f"event: update_error\ndata: {error_payload}\n\n"


async def stream_xhs_post_score(
        title: str,
        content: str,
        image_list: Optional[List[str]] = None,
        tag_list: Optional[List[str]] = None,
):
    """返回 SSE 文本流：小红书帖子评分（事件：xhs_note_scoring_start/stream/end/error）。"""
    try:
        hashtags = " ".join(tag_list or [])
        post_content = f"{title}\n\n{content}\n\n{hashtags}".strip()
        image_urls = image_list or []

        # 开始事件
        start_payload = {
            "message": f"🎯 开始评分...（文案 {len(post_content)} 字符，{len(image_urls)} 张图片）",
            "progress": 0,
        }
        yield f"event: xhs_note_scoring_start\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        # 异步启动VLM评分任务，同时模拟进度在约20-30秒内递增
        score_task = asyncio.create_task(vlm_service.score_xhs_post("xhs_scoring", post_content, image_urls))

        # 进度计划（百分比与描述），每步约 3 秒，总计 ~27 秒
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
            stream_payload = {"message": msg, "progress": pct}
            yield f"event: xhs_note_scoring_stream\ndata: {json.dumps(stream_payload, ensure_ascii=False)}\n\n"

        # 等待评分任务完成（若已完成则立即返回结果）
        scoring_result, _ = await score_task

        # 错误处理
        if not scoring_result or (isinstance(scoring_result, dict) and scoring_result.get("error")):
            err_msg = scoring_result.get("error") if isinstance(scoring_result, dict) else "Scoring failed"
            logging.error(f"VLM评分失败: {err_msg}")
            error_payload = {"error": f"xhs_post_score: {err_msg}"}
            yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            return

        # 结构化评分细则
        overall_score = scoring_result.get("overall_score", 0)
        grade = scoring_result.get("grade", "N/A")

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
                },
            },
            "copywriting_quality": {
                "total_score": copywriting_quality.get("total_score"),
                "max_score": copywriting_quality.get("max_score", 25),
                "analysis": copywriting_quality.get("analysis", ""),
                "sub_scores": {
                    "content_value": copywriting_quality.get("sub_scores", {}).get("content_value", {}),
                    "style": copywriting_quality.get("sub_scores", {}).get("style", {}),
                },
            },
            "summary": scoring_result.get("summary", {}),
        }

        end_payload = {
            "message": f"✅ 帖子评分完成！综合得分: {overall_score}/100 (等级: {grade})",
            "progress": 100,
            "scoring_details": scoring_details,
            "post_content": post_content,
            "images": image_urls,
            "image_count": len(image_urls),
            "title": title,
            "hashtags": tag_list or [],
            "button_list": {
                "重新生成": "vlm_choose_node",
                "一键发布": "xhs_note_publish_node",
            },
        }
        yield f"event: xhs_note_scoring_end\ndata: {json.dumps(end_payload, ensure_ascii=False)}\n\n"
    except Exception as e:
        logging.exception("xhs_post_score_stream_error")
        error_payload = {"error": str(e)}
        yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
