import logging
import traceback
import uuid
from typing import Literal

from json_repair import json_repair
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END
from langgraph.types import Command

# 使用prompt模板
from src.prompts.template import get_prompt_template_formatted
from .node import create_error_command, add_token_usage_to_state
from ..event.manager import event_manager
from ..state.types import State
from ...service.vlm_service import vlm_service

logger = logging.getLogger(__name__)


def _extract_structured_fields_from_detail(detail_data: dict, candidate: dict) -> dict:
    poi_info = detail_data.get("poiInfo") or {}
    sight_detail = detail_data.get("sightDetail") or {}

    structured = {
        "address": poi_info.get("address") or sight_detail.get("address") or "",
        "opening_hours": poi_info.get("openingHours") or detail_data.get("openingHours") or "",
        "spend_time": detail_data.get("spendTimeDesc") or "",
        "price": str(detail_data.get("price") or sight_detail.get("qunarPrice") or ""),
        "description": (detail_data.get("subtitle") or ""),
        "sight_score": detail_data.get("sightDetail", {}).get("score") or "",
        "image_list": detail_data.get("imageList", []),
    }

    return structured


async def poi_extract_node(state: State) -> Command[Literal[END, "generate"]]:
    """
    景点提取节点 - 从视频字幕中提取景点信息并获取详细信息
    """
    try:
        message_id = str(uuid.uuid4())

        # 发送节点启动通知
        await event_manager.send_event(
            state=state,
            event="poi_extract_node_start",
            data={"message": "🗺️ 开始提取视频中的景点信息~", "message_id": message_id}
        )

        # 获取视频字幕文案
        video_full_transcript = state.get("video_full_transcript", "")

        if not video_full_transcript:
            logger.warning("视频字幕为空，无法提取景点信息")
            return Command(
                update={"poi_extract_node_result": {"poi_list": []}},
                goto="generate"
            )

        logger.info(f"开始从字幕中提取景点，字幕长度: {len(video_full_transcript)}")

        # 步骤1: 使用LLM提取景点和城市信息
        await event_manager.send_event(
            state=state,
            event="poi_extract_node_start",
            data={"message": "正在分析字幕，识别景点...", "progress": 20, "message_id": message_id}
        )

        # 构建提示词，让LLM提取景点和城市
        # 使用模板统一构建提示词
        extract_prompt = get_prompt_template_formatted(
            "poi_extract",
            VIDEO_FULL_TRANSCRIPT=video_full_transcript,
        )

        # 调用LLM提取景点
        langchain_messages = [
            SystemMessage(
                content="你是一个专业的旅游信息提取助手，擅长从文本中识别景点和地理位置信息，并能准确判断景点的热门程度和重要性。"),
            HumanMessage(content=extract_prompt)
        ]
        extract_content, token_usage = await vlm_service.call_llm_with_messages(
            "poi_extract",  # 业务名称
            langchain_messages,
            global_user_message=state.get("global_user_message")
        )

        # 记录token使用
        add_token_usage_to_state(state, "POI景点提取", "poi_extract_node", token_usage)

        logger.info(f"LLM提取结果: {extract_content[:500]}...")

        # 解析LLM返回的JSON
        try:
            extract_result = json_repair.loads(extract_content)
            locations = extract_result.get("locations", [])
        except Exception as e:
            logger.error(f"解析LLM提取结果失败: {e}")
            locations = []

        if not locations:
            logger.info("未从字幕中提取到景点信息")
            await event_manager.send_event(
                state=state,
                event="poi_extract_node_result",
                data={
                    "message": "未在视频中识别到景点信息",
                    "poi_list": [],
                    "message_id": message_id
                }
            )
            return Command(
                update={"poi_extract_node_result": {"poi_list": []}},
                goto="generate"
            )

        logger.info(f"提取到 {len(locations)} 个景点关键词")

        # 步骤2: 调用接口查询景点详细信息
        await event_manager.send_event(
            state=state,
            event="poi_extract_node_start",
            data={"message": f"正在查询 {len(locations)} 个景点的详细信息...", "progress": 50, "message_id": message_id}
        )

        import aiohttp
        poi_details = []
        poi_list = []
        async with aiohttp.ClientSession() as session:
            for idx, location in enumerate(locations, 1):
                try:
                    city = location.get("city", "")
                    keyword = location.get("keyword", "")

                    if not city or not keyword:
                        continue

                    # 调用POI Top-K匹配接口
                    topk_url = "http://qai.corp.qunar.com/qal_marco_polo/api/poi_match_top_k"
                    DEFAULT_POI_TYPES = [
                        "12", "18", "19", "2", "20", "3", "5", "66", "7", "70",
                        "8", "81", "9", "90", "91", "92", "93", "94", "95", "96", "97"
                    ]
                    province = location.get("province", state.get("province", ""))
                    country = location.get("country", state.get("country", "中国")) or "中国"
                    topk_payload = {
                        "spot_name": keyword,
                        "spot_city": city,
                        "poi_types": DEFAULT_POI_TYPES,
                        "province": province,
                        "country": country,
                    }

                    logger.info(f"TopK查询景点: {city} - {keyword}")

                    async with session.post(topk_url, json=topk_payload, timeout=10) as response:
                        if response.status == 200:
                            topk_result = await response.json()
                            data_list = topk_result.get("data") or []
                            if isinstance(data_list, list) and data_list:
                                candidate = data_list[0]
                                poi_id = str(candidate.get("poi_id") or "")
                                poi_score = candidate.get("poi_score") or 0
                                try:
                                    poi_score = float(poi_score)
                                except Exception:
                                    poi_score = 0.0

                                if poi_id and poi_score >= 0.8:
                                    # 调用详情接口
                                    detail_url = "http://qai.corp.qunar.com/dufu/client/trip/product/poi/detail"
                                    detail_payload = {"poiId": poi_id}

                                    async with session.post(detail_url, json=detail_payload, timeout=10) as detail_resp:
                                        if detail_resp.status == 200:
                                            detail = await detail_resp.json()
                                            if detail.get("status") == 0 and detail.get("data"):
                                                detail_data = detail["data"]
                                                title = detail_data.get("title") or candidate.get("poi_name") or keyword
                                                poi_info = detail_data.get("poiInfo") or {}
                                                sight_detail = detail_data.get("sightDetail") or {}
                                                address = poi_info.get("address") or sight_detail.get("address") or ""
                                                image_list = detail_data.get("imageList") or sight_detail.get(
                                                    "originalImageURLs") or []
                                                image = image_list[0] if isinstance(image_list,
                                                                                    list) and image_list else ""
                                                structured_info = _extract_structured_fields_from_detail(detail_data,
                                                                                                         candidate)
                                                current_poi = {
                                                    "city": city,
                                                    "name": title,
                                                    "address": address,
                                                    "image": image,
                                                    **structured_info,
                                                }
                                                poi_list.append(current_poi)
                                                poi_details.append({
                                                    "city": city,
                                                    "keyword": keyword,
                                                    "poi_detail": detail_data,
                                                    "raw_data": candidate,
                                                })

                                                # 计算进度并推送
                                                progress = 50 + int((idx / len(locations)) * 30)
                                                await event_manager.send_event(
                                                    state=state,
                                                    event="poi_extract_node_stream",
                                                    data={
                                                        "message": f"正在搜索景点信息 ({idx}/{len(locations)})...",
                                                        "progress": progress,
                                                        "message_id": message_id,
                                                        "current_poi": current_poi,
                                                    }
                                                )
                                                logger.info(f"成功获取景点信息: {title} (score={poi_score})")
                                        else:
                                            logger.warning(f"景点详情查询失败，状态码: {detail_resp.status}")
                                else:
                                    logger.info(f"TopK候选评分不足或缺失，poi_id={poi_id}, score={poi_score}")
                        else:
                            logger.warning(f"TopK接口查询失败，状态码: {response.status}")

                    # 发送进度
                    progress = 50 + int((idx / len(locations)) * 30)
                    # await event_manager.send_event(
                    #     state=state,
                    #     event="poi_extract_node_stream",
                    #     data={
                    #         "message": f"已查询 {idx}/{len(locations)} 个景点",
                    #         "progress": progress,
                    #         "message_id": message_id
                    #     }
                    # )

                except Exception as e:
                    logger.exception(f"查询景点 {keyword} 时异常: {e}")
                    continue

        if not poi_details:
            logger.info("未查询到任何景点详细信息")
            await event_manager.send_event(
                state=state,
                event="poi_extract_node_result",
                data={
                    "message": "未能获取到景点的详细信息",
                    "poi_list": [],
                    "message_id": message_id
                }
            )
            return Command(
                update={"poi_extract_node_result": {"poi_list": []}},
                goto="generate"
            )

        #         # 步骤3: 使用LLM逐个精简景点信息
        #         await event_manager.send_event(
        #             state=state,
        #             event="poi_extract_node_start",
        #             data={"message": "正在整理景点信息...", "progress": 80, "message_id": message_id}
        #         )

        #         poi_list = []
        #         total_pois = len(poi_details)

        #         # 逐个处理每个景点
        #         for idx, poi in enumerate(poi_details):
        #             try:
        #                 logger.info(f"处理景点 {idx + 1}/{total_pois}: {poi.get('keyword', '')}")

        #                 # 构建单个景点的精简提示词
        #                 simplify_prompt = f"""请将以下景点详细信息精简为一段简洁的描述，包含：具体地址、营业时间、游玩时长、重要提醒等关键信息。

        # 景点信息：
        # {json.dumps(poi, ensure_ascii=False, indent=2)}

        # 请以JSON格式返回，格式如下：
        # {{
        #     "name": "景点名称",
        #     "detail": "地址：具体地址。营业时间：营业时间。游玩时长：推荐时长。价格：门票价格。交通方式：如何到达。特色亮点：景点特色。适合人群：适合谁去。最佳时间：最佳游玩时间。周边设施：周边配套。美食推荐：附近美食。拍照打卡点：最佳拍照位置。踩坑提醒：重要注意事项。其他信息：其他有用的信息"
        # }}

        # 要求：
        # 1. detail字段按照"字段名：内容"的格式组织，用句号或逗号分隔
        # 2. 可包含但不限于以下字段：地址、营业时间、游玩时长、价格、交通方式、特色亮点、适合人群、最佳时间、周边设施、美食推荐、拍照打卡点、踩坑提醒等
        # 3. 根据实际情况灵活选择和添加字段，不强制要求所有字段都存在
        # 4. 如果某个字段信息缺失，可以省略该字段
        # 5. 突出最重要的实用信息
        # 6. 如果有用户评论中的踩坑提醒或实用建议，要包含进去
        # 7. 保持客观中立的语气
        # 8. 可以根据景点特点自行添加其他有价值的信息字段
        # 9. 控制在150字以内
        # """

        #                 langchain_messages = [
        #                     SystemMessage(content="你是一个专业的旅游信息整理助手，擅长提炼关键信息。"),
        #                     HumanMessage(content=simplify_prompt)
        #                 ]

        #                 simplify_response = await llm.ainvoke(langchain_messages)
        #                 simplify_content = simplify_response.content if hasattr(simplify_response, 'content') else str(
        #                     simplify_response)

        #                 logger.info(f"景点 {idx + 1} LLM精简结果: {simplify_content[:200]}...")

        #                 # 解析精简结果
        #                 try:
        #                     poi_result = json_repair.loads(simplify_content)
        #                     if isinstance(poi_result, dict) and "name" in poi_result and "detail" in poi_result:
        #                         poi_list.append(poi_result)
        #                     else:
        #                         raise ValueError("返回格式不正确")
        #                 except Exception as parse_error:
        #                     logger.error(f"解析景点 {idx + 1} LLM精简结果失败: {parse_error}")
        #                     # 如果解析失败，使用原始数据构建简单版本
        #                     detail = poi.get("poi_detail", {})
        #                     poi_list.append({
        #                         "name": detail.get("name", poi.get("keyword", "")),
        #                         "detail": f"地址: {detail.get('address', '未知')}，营业时间: {detail.get('openTime', '未知')}"
        #                     })

        #                 # 更新进度，发送当前处理结果
        #                 progress = 80 + int((idx + 1) / total_pois * 15)
        #                 current_poi = poi_list[-1]  # 获取刚添加的景点
        #                 await event_manager.send_event(
        #                     state=state,
        #                     event="poi_extract_node_stream",
        #                     data={
        #                         "message": f"正在搜索景点信息 ({idx + 1}/{total_pois})...",
        #                         "progress": progress,
        #                         "message_id": message_id,
        #                         "current_poi": current_poi,  # 添加当前处理的景点结果
        #                     }
        #                 )

        #             except Exception as e:
        #                 logger.exception(f"处理景点 {idx + 1} 时异常: {e}")
        #                 # 即使出错也添加基本信息
        #                 detail = poi.get("poi_detail", {})
        #                 poi_list.append({
        #                     "name": detail.get("name", poi.get("keyword", "")),
        #                     "detail": f"地址: {detail.get('address', '未知')}"
        #                 })

        logger.info(f"景点信息提取完成，共 {len(poi_list)} 个景点")

        # 发送完成通知
        await event_manager.send_event(
            state=state,
            event="poi_extract_node_end",
            data={
                "message": f"✅ 景点信息提取完成，共识别 {len(poi_list)} 个景点",
                "poi_list": poi_list,
                "progress": 100,
                "message_id": message_id
            }
        )

        return Command(
            update={"poi_extract_node_result": {"poi_list": poi_list}},
            goto="generate"
        )

    except Exception as e:
        logger.exception(f"景点提取节点异常: {e}")
        await event_manager.send_event(
            state=state,
            event="error",
            data={"error": f"景点提取失败: {str(e)}", "traceback": traceback.format_exc(), "message_id": message_id}
        )

        return await create_error_command(
            state=state,
            error_msg=f"景点提取失败: {str(e)}",
            include_traceback=True,
            message_id=message_id
        )
