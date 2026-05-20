import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.database import video_workflow_service, VideoWorkflowRecordQuery
from src.database.ext_utils import parse_state_from_ext

logger = logging.getLogger(__name__)


def calculate_token_cost(token_usage_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    计算token使用成本

    参数:
        token_usage_records: token使用记录列表

    返回:
        dict: 包含 input_cost, output_cost, total_cost 的字典(单位:美元)；以及对应的人民币字段 *_cny
    """
    # 定价(美元/百万token)
    INPUT_PRICE_PER_MILLION = 1.250
    OUTPUT_PRICE_PER_MILLION = 10.000

    total_input_tokens = 0
    total_output_tokens = 0

    for record in token_usage_records:
        total_input_tokens += record.get("input_tokens", 0)
        total_output_tokens += record.get("output_tokens", 0)

    # 计算成本(转换为百万token)
    input_cost = (total_input_tokens / 1_000_000) * INPUT_PRICE_PER_MILLION
    output_cost = (total_output_tokens / 1_000_000) * OUTPUT_PRICE_PER_MILLION
    total_cost = input_cost + output_cost

    # 人民币汇率（可通过环境变量 USD_CNY_RATE 覆盖），默认 7.2
    try:
        usd_cny_rate = float(os.getenv("USD_CNY_RATE", "7.2"))
    except ValueError:
        usd_cny_rate = 7.2

    input_cost_cny = input_cost * usd_cny_rate
    output_cost_cny = output_cost * usd_cny_rate
    total_cost_cny = total_cost * usd_cny_rate

    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total_cost, 6),
        "input_cost_cny": round(input_cost_cny, 6),
        "output_cost_cny": round(output_cost_cny, 6),
        "total_cost_cny": round(total_cost_cny, 6),
        "usd_cny_rate": round(usd_cny_rate, 6),
    }


def aggregate_by_frame_text(data):
    """
    基于 frame_text 聚合帧信息

    参数:
        data (dict): 包含 text_and_image_combine_node_result 的原始 JSON 数据

    返回:
        list[dict]: 聚合后的结果列表
    """
    grouped = defaultdict(lambda: {"text_start_time": None, "text_end_time": None, "image_list": []})

    # 遍历每一帧
    for item in data.get("text_and_image_combine_node_result", {}).get("combined_narrative", []):
        text = item.get("frame_text", "").strip()
        if not text:
            continue  # 跳过空文本

        image_url = item.get("image_url")
        start = item.get("text_start_time")
        end = item.get("text_end_time")

        group = grouped[text]

        # 只在第一次出现时保存时间
        if group["text_start_time"] is None:
            group["text_start_time"] = start
            group["text_end_time"] = end

        # 累积图片链接
        if image_url:
            group["image_list"].append(image_url)

    # 转换为目标格式
    result = [
        {
            "frame_text": text,
            "text_start_time": info["text_start_time"],
            "text_end_time": info["text_end_time"],
            "image_list": info["image_list"],
        }
        for text, info in grouped.items()
    ]

    return result


def extract_image_pairs(data):
    """
    从 image_processing_result 中提取原图和处理后图片的映射

    参数:
        data (dict): 包含 image_processing_result 的原始 JSON 数据

    返回:
        list[dict]: 形如
            [
                {
                    "original_url": "...",
                    "processed_url": "..."
                },
                ...
            ]
    """
    result = []

    # 取出 processed_images 列表
    processed_images = data.get("image_processing_result", {}).get("processed_images", [])

    for item in processed_images:
        original_url = item.get("original_url")
        processed_url = item.get("processed_url")

        # 只保留同时存在原图和处理后图片链接的项
        if original_url and processed_url:
            result.append({
                "original_url": original_url,
                "processed_url": processed_url
            })

    return result


def extract_poi_info(data):
    """
    从 poi_extract_node_result 中提取 POI 名称与图片

    参数:
        data (dict): 包含 poi_extract_node_result 的原始 JSON 数据

    返回:
        list[dict]: 形如
            [
                {
                    "name": "...",
                    "image": "..."
                },
                ...
            ]
    """
    result = []

    poi_list = data.get("poi_extract_node_result", {}).get("poi_list", [])

    for poi in poi_list:
        name = poi.get("name", "")
        image = poi.get("image", "")
        result.append({
            "name": name,
            "image": image,
            "image_list": poi.get("image_list", [])
        })

    return result


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    格式化 datetime 为 YYYY-MM-DD HH:MM:SS 格式
    
    参数:
        dt: datetime 对象或 None
        
    返回:
        格式化后的字符串，如果 dt 为 None 则返回 None
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def extract_title_from_ext(ext: Optional[str]) -> str:
    """
    从 ext 字段中提取 title
    
    参数:
        ext: ext 字段的 JSON 字符串
        
    返回:
        提取的 title，如果提取失败则返回 "默认标题"
    """
    title = "默认标题"
    if not ext:
        return title

    try:
        # 第一次解析 ext 字段
        ext_data = json.loads(ext)

        # 如果解析后仍然是字符串，说明是双重编码，需要再次解析
        if isinstance(ext_data, str):
            ext_data = json.loads(ext_data)

        # 获取 state 值
        state_value = ext_data.get("state", {})

        # 如果 state 是字符串，说明也是 JSON 字符串，需要再次解析
        if isinstance(state_value, str):
            state_detail = json.loads(state_value)
        elif isinstance(state_value, dict):
            # 如果 state 已经是字典，直接使用
            state_detail = state_value
        else:
            state_detail = {}

        # 提取 title
        title = state_detail.get("generate_node_result", {}).get("title", "默认标题")
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"解析 ext 字段失败: {str(e)}")
        title = "默认标题"

    return title



async def get_xhs_list() -> Dict[str, Any]:
    """
    获取 video_workflow_record 表所有数据，最近创建的在前面
    
    返回:
        dict: 包含 status, message, data 的字典
    """
    try:
        # 使用分页获取所有记录（limit 最大值为 100）
        all_records = []
        offset = 0
        limit = 100  # limit 最大值为 100
        total = 0

        # 循环获取所有记录
        while True:
            query_params = VideoWorkflowRecordQuery(
                limit=limit,
                offset=offset,
                status="SUCCESS"
            )
            records, query_total = await video_workflow_service.query_workflow_records(query_params)

            # 第一次查询时保存总数
            if offset == 0:
                total = query_total

            if not records:
                break

            all_records.extend(records)

            # 如果获取的记录数小于 limit，说明已经获取完所有记录
            if len(records) < limit:
                break

            offset += limit

        # 统一序列化
        serialized = []
        for r in all_records:
            # 先获取原始的 create_time（datetime 对象）
            original_create_time = r.create_time if hasattr(r, "create_time") else None

            # 先序列化记录
            if hasattr(r, "to_dict"):
                record_dict = r.to_dict()
            else:
                try:
                    record_dict = r.model_dump()
                except Exception:
                    record_dict = dict(r)

            # 从 ext 字段中提取 title
            title = extract_title_from_ext(r.ext)

            # 格式化 create_time（使用原始的 datetime 对象）
            record_dict["create_time"] = format_datetime(original_create_time)

            # 添加 title 字段到记录中
            record_dict["title"] = title
            record_dict.pop("ext", None)  # 移除 ext 字段
            serialized.append(record_dict)

        return {
            "status": 0,
            "message": "success",
            "data": {"total": total, "records": serialized}
        }
    except Exception as e:
        logger.exception(f"get_xhs_list_error: {str(e)}")
        return {
            "status": 1,
            "message": f"get_xhs_list_error: {str(e)}",
            "data": {}
        }


async def get_xhs_detail(session_id: str) -> Dict[str, Any]:
    """
    获取小红书详情数据
    
    参数:
        session_id: 会话ID
        
    返回:
        dict: 包含 status, message, data 的字典
    """
    try:
        query_params = VideoWorkflowRecordQuery(session_id=session_id)
        records, total = await video_workflow_service.query_workflow_records(query_params)

        # 如果没有记录，返回空数据
        if not records or total == 0:
            return {
                "status": 1,
                "message": "未找到已完成的工作流记录",
                "data": {}
            }

        # 获取最新的记录（通常第一条是最新的）
        latest_record = records[0]

        # 解析 ext 字段获取 state
        state_detail = parse_state_from_ext(latest_record.ext)

        # 如果 state 为空，返回空数据
        if not state_detail:
            return {
                "status": 1,
                "message": "工作流记录中未找到 state 数据",
                "data": {}
            }

        # 构建返回数据
        return {
            "status": 0,
            "message": "success",
            "data": {
                # 小红书区域
                "xhs_note": {
                    "title": state_detail.get("xhs_final_text_node_result", {}).get("title", ""),
                    "content": state_detail.get("xhs_final_text_node_result", {}).get("full_caption", ""),
                    "tags": state_detail.get("xhs_final_text_node_result", {}).get("hashtags", []),
                    # 封面图+内容图
                    "image_list": state_detail.get("xhs_final_text_node_result", {}).get("images", []),
                    "origin_cover_image": next((item.get("obs_url", "") for item in (
                            state_detail.get("collage_node_result", {}).get("collage_results") or []) if
                                                item.get("success")), ""),
                },
                "tab_list": [
                    {
                        "title": "视频帧图片",
                        "frame_list": aggregate_by_frame_text(state_detail)
                    },
                    {
                        "title": "AI增强图片",
                        "image_process_list": extract_image_pairs(state_detail)
                    },
                    {
                        "title": "景点图片",
                        "image_info_list": extract_poi_info(state_detail)
                    }
                ],
                "video_full_transcript": state_detail.get("video_full_transcript", ""),
                "xhs_note_from_style": state_detail.get("xhs_note_from_style", ""),
                "xhs_post_scoring": state_detail.get("xhs_post_scoring_node_result", {}).get("scoring_result", ""),
                "token_usage_summary": calculate_token_cost(state_detail.get("token_usage_records", [])),
                "token_usage_records": state_detail.get("token_usage_records", []),
                "img2img_usage_records": state_detail.get("img2img_usage_records", []),
            }
        }
    except Exception as e:
        logger.exception(f"get_xhs_detail_error: {str(e)}")
        return {
            "status": 1,
            "message": f"get_xhs_detail_error: {str(e)}",
            "data": {}
        }
