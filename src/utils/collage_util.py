import logging
import os
import json
import random
from typing import List, Dict, Any
from urllib.parse import urlparse

import aiohttp
from langchain_core.messages import SystemMessage, HumanMessage

from src.graph.event.manager import event_manager
from src.prompts.template import get_prompt_template_formatted
from src.service import obs_service
from src.service.grid_image_service import GridImageService
from src.service.vlm_service import vlm_service
from src.utils import collage_scheme

logger = logging.getLogger(__name__)


async def process_collage_results(result, state, index_to_local_path, unique_id, total_items, current_item):
    """
    处理LLM返回的拼图结果，解析并调用相应的拼图函数

    Args:
        result: LLM返回的结果列表，包含function_name、params、reason
        state: 当前状态对象

    Returns:
        list: 处理结果列表，包含成功生成的拼图信息
    """
    logger.info(f"开始处理拼图结果，共 {len(result)} 个拼图任务")

    # 生成唯一标识符用于存储目录x

    if not index_to_local_path:
        logger.error("没有成功下载任何图片，无法进行拼图处理")
        return []

    collage_results = []

    # 创建拼图输出目录
    output_dir = os.path.join("..", "data", "collage_img", unique_id, "output")
    os.makedirs(output_dir, exist_ok=True)

    for idx, collage_task in enumerate(result.get("function", [])):
        try:
            function_name = collage_task.get("function_name")
            params = collage_task.get("params", {})
            reason = collage_task.get("reason", "")

            logger.info(f"处理第 {idx + 1} 个拼图任务: {function_name}")
            logger.info(f"参数: {params}")
            logger.info(f"原因: {reason}")

            # 将参数中的index映射为实际的本地图片路径
            mapped_params = {}
            for param_name, index_value in params.items():
                if isinstance(index_value, int):
                    if index_value in index_to_local_path:
                        local_path = index_to_local_path[index_value]
                        mapped_params[param_name] = local_path
                        logger.info(f"映射参数 {param_name}: index {index_value} -> {local_path}")
                        continue
                    else:
                        logger.warning(f"无法找到index {index_value} 对应的本地图片")
                        continue
                else:
                    continue

            # 检查是否有足够的参数
            if len(mapped_params) == 0:
                logger.error(f"拼图任务 {idx + 1} 没有有效的图片参数")
                collage_results.append({
                    "function_name": function_name,
                    "reason": reason,
                    "success": False,
                    "error": "没有有效的图片参数"
                })
                continue

            # 添加输出路径参数
            output_filename = f"collage_{idx + 1}_{function_name}.jpg"
            output_path = os.path.join(output_dir, output_filename)
            mapped_params["output_path"] = output_path

            # 动态调用拼图函数（函数位于 collage_scheme 模块）
            module = collage_scheme
            if hasattr(module, function_name):
                collage_function = getattr(module, function_name)
                logger.info(f"调用函数 {function_name}（来自 collage_scheme），参数: {mapped_params}")

                # 调用拼图函数
                collage_function(**mapped_params)

                # 检查输出文件是否生成成功
                if os.path.exists(output_path):
                    # 上传到OBS
                    obs_url = await obs_service.upload_file(output_path)
                    if not obs_url:
                        logger.error(f"拼图 {idx + 1} 上传到OBS失败: {output_path}")
                        # 即使上传失败，也记录本地路径的结果
                        result_data = {
                            "function_name": function_name,
                            "output_path": output_path,  # 本地路径
                            "obs_url": None,
                            "reason": reason,
                            "success": True,  # 生成是成功的
                            "upload_success": False,
                            "params": mapped_params,
                            "unique_id": unique_id
                        }
                    else:
                        logger.info(f"拼图 {idx + 1} 上传到OBS成功: {obs_url}")
                        result_data = {
                            "function_name": function_name,
                            "output_path": output_path,
                            "obs_url": obs_url,
                            "reason": reason,
                            "success": True,
                            "upload_success": True,
                            "params": mapped_params,
                            "unique_id": unique_id
                        }
                        # 推送stream事件

                        # 避免除以零错误（虽然这里 +1 理论上不会是零，但保留代码严谨性）
                        if total_items == 0:
                            progress_percent = 30
                        else:
                            progress_percent = int(((idx + 1 + current_item) / total_items) * 100)
                        await event_manager.send_event(
                            state=state,
                            event="collage_node_stream",
                            data={
                                "message": f"拼图进度- {progress_percent}%",
                                "progress": f"{progress_percent}%",
                                "current": idx + 1,
                                "total": len(result.get('function', [])) + 1,
                                "collage_info": {
                                    "function_name": function_name,
                                    "obs_url": obs_url,
                                    "reason": reason
                                }
                            }
                        )

                    collage_results.append(result_data)
                    logger.info(f"拼图 {idx + 1} 生成成功: {output_path}")
                else:
                    logger.error(f"拼图 {idx + 1} 生成失败，输出文件不存在: {output_path}")
                    collage_results.append({
                        "function_name": function_name,
                        "reason": reason,
                        "success": False,
                        "error": "输出文件未生成"
                    })
            else:
                logger.error(f"函数 {function_name} 不存在于 collage_scheme 模块中")
                collage_results.append({
                    "function_name": function_name,
                    "reason": reason,
                    "success": False,
                    "error": f"函数 {function_name} 不存在"
                })

        except Exception as e:
            logger.error(f"处理拼图任务 {idx + 1} 时发生错误: {str(e)}")
            collage_results.append({
                "function_name": collage_task.get("function_name", "unknown"),
                "reason": collage_task.get("reason", ""),
                "success": False,
                "error": str(e)
            })

    logger.info(f"拼图处理完成，成功: {sum(1 for r in collage_results if r.get('success'))}/{len(collage_results)}")
    return collage_results


async def download_oss_images_to_local(video_frame_list, unique_id):
    """
    下载OSS图片到本地存储

    Args:
        video_frame_list: 视频帧列表，包含image_url等信息
        unique_id: 唯一标识符，用于创建存储目录

    Returns:
        dict: 映射关系 {index: local_path}
    """
    logger.info(f"开始下载OSS图片到本地，唯一标识: {unique_id}")

    # 创建本地存储目录
    local_dir = os.path.join("..", "data", "collage_img", unique_id)
    os.makedirs(local_dir, exist_ok=True)

    # 初始化GridImageService
    grid_service = GridImageService()

    # 存储映射关系
    index_to_path = {}

    for frame in video_frame_list:
        try:
            index = frame.get("index")
            image_url = frame.get("image_url")

            if not image_url:
                logger.warning(f"帧 {index} 没有image_url")
                continue

            # 生成本地文件名
            filename = f"frame_{index:03d}.jpg"

            # 下载图片：OBS 链接使用 OBS 服务下载，其他 HTTP 图片直接下载。
            # GridImageService.download_image_from_url 当前只处理 OBS 域名；
            # qimgs.qunarzz.com 等普通图片链接需要走通用 HTTP 下载。
            local_path = None
            if _is_oss_url(image_url):
                local_path = await grid_service.download_image_from_url(image_url, filename)
            else:
                target_path = os.path.join(local_dir, filename)
                if await _download_http_image(image_url, target_path):
                    local_path = target_path

            if local_path:
                # 移动到目标目录
                target_path = os.path.join(local_dir, filename)
                if local_path != target_path:
                    import shutil
                    shutil.move(local_path, target_path)
                    local_path = target_path

                index_to_path[index] = local_path
                logger.info(f"帧 {index} 下载成功: {image_url} -> {local_path}")
            else:
                logger.error(f"帧 {index} 下载失败: {image_url}")

        except Exception as e:
            logger.error(f"下载帧 {index} 时发生错误: {str(e)}")

    logger.info(f"图片下载完成，成功: {len(index_to_path)}/{len(video_frame_list)}")
    return index_to_path


async def get_local_image_path(image_url, state):
    """
    获取图片的本地路径

    Args:
        image_url: 图片URL或路径
        state: 当前状态对象

    Returns:
        str: 本地图片路径
    """
    # 如果image_url已经是本地路径，直接返回
    if os.path.exists(image_url):
        return image_url

    # 如果是URL，可能需要下载或者从缓存中获取
    # 这里假设image_url是相对路径或者已经是可访问的本地路径
    # 根据实际情况调整这个逻辑

    # 尝试从state中获取基础路径
    base_path = state.get("base_image_path", "")
    if base_path and not os.path.isabs(image_url):
        full_path = os.path.join(base_path, image_url)
        if os.path.exists(full_path):
            return full_path

    # 如果都不行，返回原始路径，让调用方处理
    return image_url


def is_normal_image_url(url: str) -> bool:
    """
    根据URL路径结构判断是否为正常图片。
    - 正常 (True): /images/后面直接是文件名 (e.g., /images/filename.jpg)
    - 异常 (False): /images/后面还有多层目录 (e.g., /images/fd/tg/g1/filename.jpg)
    """
    try:
        # 1. 解析URL，只获取其路径部分
        # e.g., "/images/fd/tg/g1/M06/FC/24/CghzflW7H_iATdynAAA-FlXAIeA738_C_1280_720_Q70.jpg"
        # or "/images/0105d120005r7mms6BC9A_C_1280_720_Q70.jpg"
        path = urlparse(url).path
        # 2. 找到 '/images/' 锚点
        anchor = '/images/'
        if anchor not in path:
            # 如果URL结构很奇怪，没有 /images/，按业务逻辑处理
            # 这里我们假设它不是我们要找的占位图，标记为“正常”
            return True
        # 3. 获取 '/images/' 之后的所有内容
        # 使用 .split(anchor, 1) 确保只分割一次
        path_after_images = path.split(anchor, 1)[-1]
        # 4. 核心逻辑：检查这部分是否还包含斜杠 '/'
        #    - 'fd/tg/g1/...' 中包含 '/'  -> False (不正常)
        #    - '0105d120005r7mms6...' 中不包含 '/' -> True (正常)
        if '/' in path_after_images:
            return False  # 包含多余分隔，是占位图
        else:
            return True  # 不包含，是正常图片
    except Exception as e:
        # 处理无效URL等边缘情况
        print(f"处理URL时出错: {url}, 错误: {e}")
        # 出现错误时，保守地标记为“不正常”，以便后续排查
        return False


def _is_oss_url(url: str) -> bool:
    """
    判断是否为华为云 OBS 链接。
    """
    try:
        netloc = urlparse(url).netloc.lower()
        return ('myhuaweicloud.com' in netloc) or ('obs.' in netloc)
    except Exception:
        return False


async def _download_http_image(url: str, target_path: str) -> bool:
    """
    通用 HTTPS 图片下载（非 OBS 链接）。

    将远程图片直接保存到指定的本地路径。
    """
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning(f"HTTP下载失败，状态码={resp.status}: {url}")
                    return False
                content = await resp.read()
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, 'wb') as f:
                    f.write(content)
        return True
    except Exception as e:
        logger.error(f"HTTP下载异常: {e}")
        return False


def collect_poi_images(state, max_count: int = 15) -> List[Dict[str, Any]]:
    """
    从 state 中的 poi_list 以“横向轮次”的方式提取最多 `max_count` 张图片 URL。

    策略（例如 A、B、C 三个 item）：
    - 第一轮：按顺序依次取 A.image、B.image、C.image；
    - 第二轮：按顺序依次取 A.image_list[0]、B.image_list[0]、C.image_list[0]；
    - 第三轮：按顺序依次取 A.image_list[1]、B.image_list[1]、C.image_list[1]；
    - 以此类推，直到达到 `max_count` 或所有图片耗尽。
    - 收集过程中不允许重复链接。

    去重与清理：
    - 每个 URL 执行 `strip()` 去除首尾空白；
    - 结果进行去重（保持首次出现的顺序）。

    Args:
        state: 当前状态对象，需包含键 `poi_extract_node_result.poi_list`。
        max_count: 最大返回数量，默认 15。

    Returns:
         List[Dict[str, Any]
    """

    # 从 state 中获取 poi_list
    poi_result = state.get("poi_extract_node_result") or {}
    poi_list: List[Dict[str, Any]] = poi_result.get("poi_list") or []

    result_list: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _push(url: str, src_item: Dict[str, Any]):
        if url and url not in seen:
            seen.add(url)
            idx = len(result_list)
            name = str(src_item.get("name", "")).strip()
            desc = str(src_item.get("description", "")).strip()
            if name and desc:
                text = f"{name}。{desc}"
            elif name:
                text = name
            else:
                text = desc
            result_list.append({"index": idx, "image_url": url, "description": text})

    # 第一轮：优先取每个 item 的 image
    for item in poi_list or []:
        if len(result_list) >= max_count:
            break
        image = item.get("image", "")
        if isinstance(image, str):
            s = image.strip()
            if s:
                _push(s, item)
                if len(result_list) >= max_count:
                    break

    # 计算每个 item 的 image_list 最大长度，用于横向轮次
    max_len = 0
    for item in poi_list or []:
        image_list = item.get("image_list") or []
        if isinstance(image_list, list) and len(image_list) > max_len:
            max_len = len(image_list)

    # 后续轮次：按横向索引依次取各 item 的第 i 张图
    for i in range(max_len):
        if len(result_list) >= max_count:
            break
        for item in poi_list or []:
            if len(result_list) >= max_count:
                break
            image_list = item.get("image_list") or []
            if isinstance(image_list, list) and i < len(image_list):
                entry = image_list[i]
                if isinstance(entry, str):
                    s = entry.strip()
                    if s:
                        _push(s, item)

    logger.info(f"POI图片收集完成（按横向轮次遍历），最终数量={len(result_list)}")
    return result_list


async def call_keyframe_assembler_llm(
        video_full_transcript: str,
        video_frame_list: List[Dict[str, Any]],
        state: Any | None = None
):
    """
    构建 Key Frame Assembler 的提示与图片消息，并并行执行 LLM 与下载。

    Args:
        video_full_transcript: 视频完整字幕文本
        video_frame_list: 帧列表（需包含 'image_url' 与可选 'frame_time'/'description'）
        temperature: LLM 温度

    Returns:
        (response_content, index_to_local_path, unique_id)
    """
    # 构建帧列表字符串（仅作为文本补充信息）
    frame_list_str = ""
    for idx, frame in enumerate(video_frame_list, start=1):
        frame_list_str += f"""
    index: {idx}:
    - 时间戳: {frame.get('frame_time', 'N/A')}
    - 对应描述: {frame.get('description', 'N/A')}
    """

    collage_scheme_json = collage_scheme.generate_layout_map()
    prompt = get_prompt_template_formatted(
        "key_frame_assembler",
        VIDEO_FULL_TRANSCRIPT=video_full_transcript,
        TOTAL_IMAGE_COUNT=len(video_frame_list),
        VIDEO_FRAME_LIST=frame_list_str,
        COLLAGE_SCHEME=collage_scheme_json,
    )

    # 构建 user 消息的 content 部分（只包含图片）
    user_content_parts: List[Dict[str, Any]] = []
    for idx, frame in enumerate(video_frame_list, start=1):
        image_url = frame.get("image_url", "")
        if image_url:
            user_content_parts.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })

    actual_image_count = len(user_content_parts)
    logger.info(f"实际发送给LLM的图片数量: {actual_image_count}")

    langchain_messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=user_content_parts),
    ]

    try:
        response, token_usage = await vlm_service.call_llm_with_messages("keyframe_assembler", langchain_messages)
    except Exception as e:
        logger.exception(f"关键帧拼图组装LLM调用失败，使用默认拼图方案: {e}")
        function_list = []
        image_count = len(video_frame_list)
        if image_count >= 9:
            function_list.append({
                "function_name": "create_collage_9_images_3x3",
                "params": {
                    "path_r1c1": 1, "path_r1c2": 2, "path_r1c3": 3,
                    "path_r2c1": 4, "path_r2c2": 5, "path_r2c3": 6,
                    "path_r3c1": 7, "path_r3c2": 8, "path_r3c3": 9,
                },
                "reason": "默认九宫格概览"
            })

        for index in range(1, min(image_count, 8) + 1):
            function_list.append({
                "function_name": "create_collage_1_images",
                "params": {"path_main": index},
                "reason": "默认精选单图"
            })

        response = json.dumps({"function": function_list}, ensure_ascii=False)
        token_usage = None
    logger.info(f"call_keyframe_assembler_llm response:{response}")
    # 新增cost记录
    try:
        if state is not None and token_usage and (
                getattr(token_usage, "total_tokens", 0) > 0 or getattr(token_usage, "input_tokens", 0) > 0):
            from src.graph.node.node import add_token_usage_to_state
            add_token_usage_to_state(state, "关键帧拼图组装", "keyframe_assembler", token_usage)
        else:
            model_name = getattr(token_usage, "model_name", "")
            logger.info(
                f"[TokenUsage] keyframe_assembler model={model_name} input={getattr(token_usage, 'input_tokens', 0)} output={getattr(token_usage, 'output_tokens', 0)} total={getattr(token_usage, 'total_tokens', 0)}")
    except Exception as e:
        logger.error(f"记录关键帧拼图组装token使用失败: {e}")
    # 并发调用
    return response, token_usage


async def call_poi_assembler_llm(
        video_full_transcript: str,
        poi_desc_list: List[Dict[str, Any]],
        state: Any | None = None
):
    """
    构建 Key Frame Assembler 的提示与图片消息，并并行执行 LLM 与下载。

    Args:
        video_full_transcript: 视频完整字幕文本
        poi_desc_list: 帧列表（需包含 'image_url' 与可选 'frame_time'/'description'）
        temperature: LLM 温度

    Returns:
        (response_content, index_to_local_path, unique_id)
    """
    # 构建帧列表字符串（仅作为文本补充信息）
    poi_list_str = ""
    for idx, frame in enumerate(poi_desc_list, start=1):
        poi_list_str += f"""
    index: {idx}:对应描述: {frame.get('description', 'N/A')}
    """

    collage_scheme_json = collage_scheme.generate_layout_map()
    prompt = get_prompt_template_formatted(
        "poi_assembler",
        VIDEO_FULL_TRANSCRIPT=video_full_transcript,
        TOTAL_IMAGE_COUNT=len(poi_desc_list),
        POI_LIST_DESC=poi_list_str,
        COLLAGE_SCHEME=collage_scheme_json,
    )

    # 构建 user 消息的 content 部分（只包含图片）
    user_content_parts: List[Dict[str, Any]] = []
    for idx, frame in enumerate(poi_desc_list, start=1):
        image_url = frame.get("image_url", "")
        if image_url:
            user_content_parts.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })

    actual_image_count = len(user_content_parts)
    logger.info(f"实际发送给LLM的图片数量: {actual_image_count}")

    langchain_messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=user_content_parts),
    ]

    response, token_usage = await vlm_service.call_llm_with_messages("poi_assembler", langchain_messages)
    logger.info(f"call_poi_assembler_llm response={response}")
    # 新增cost记录
    try:
        if state is not None and token_usage and (
                getattr(token_usage, "total_tokens", 0) > 0 or getattr(token_usage, "input_tokens", 0) > 0):
            # 复用全局的记录方法，确保前后端口径一致
            from src.graph.node.node import add_token_usage_to_state
            add_token_usage_to_state(state, "POI拼图组装", "poi_assembler", token_usage)
        else:
            # 兜底日志，至少在没有state时也能看到成本
            model_name = getattr(token_usage, "model_name", "")
            logger.info(
                f"[TokenUsage] poi_assembler model={model_name} input={getattr(token_usage, 'input_tokens', 0)} output={getattr(token_usage, 'output_tokens', 0)} total={getattr(token_usage, 'total_tokens', 0)}")
    except Exception as e:
        logger.error(f"记录POI拼图组装token使用失败: {e}")
    # 并发调用
    return response, token_usage


async def download_poi_img_list(poi_desc_list: List[Dict[str, Any]], unique_id: str) -> Dict[int, str]:
    """
    下载传入的 POI 图片 URL 列表，返回本地路径的索引映射。

    要求：
    - 入参 `poi_img_url_list` 为字符串 URL 列表；
    - 下载到本地目录 `../data/collage_img/<uuid>/poi/`；
    - 返回 `poi_local_path`，key 为索引（从 1 开始），value 为目标本地路径；
    - 索引严格与输入位置一致；下载失败也保留该索引的占位路径。

    Args:

    Returns:
        Dict[int, str]: 索引（1开始）到本地路径的映射（失败项也保留占位路径）。
    """

    poi_img_url_list = [item['image_url'] for item in poi_desc_list if 'image_url' in item]
    # 本地目录（基于传入唯一ID）
    poi_unique_id = str(unique_id)[:8]
    poi_dir = os.path.join("..", "data", "collage_img", poi_unique_id, "poi")
    os.makedirs(poi_dir, exist_ok=True)

    grid_service = GridImageService()

    poi_local_path: Dict[int, str] = {}

    for idx, url in enumerate(poi_img_url_list or [], start=1):
        if not isinstance(url, str):
            continue
        url_s = url.strip()
        if not url_s:
            continue

        filename = f"poi_{idx:02d}.jpg"
        target_path = os.path.join(poi_dir, filename)

        path: str | None = None
        try:
            if _is_oss_url(url_s):
                path = await grid_service.download_image_from_url(url_s, filename)
                if path and path != target_path:
                    try:
                        import shutil
                        shutil.move(path, target_path)
                        path = target_path
                        poi_local_path[idx] = path
                    except Exception:
                        pass
            else:
                success = await _download_http_image(url_s, target_path)
                if success:
                    path = target_path
                    poi_local_path[idx] = path
        except Exception as e:
            logger.error(f"下载 POI 图片失败: {e}")
            path = None
        if path:
            logger.info(f"POI 图片下载成功: {url_s} -> {target_path}")
        else:
            logger.warning(f"POI 图片下载失败，保留占位路径: {url_s} -> {target_path}")

    return poi_local_path


def filter_collage_results(collage_results: list[dict]) -> list[dict]:
    """
    按照优先级规则将拼图结果列表缩减至最多9个。

    规则:
    1. 移除所有 "success": False 的项。
    2. 如果还 > 9, 从第3项(索引2)开始，只移除"多图拼图" (非 create_collage_1_)。
    3. 如果还 > 9, 随机移除，直到列表长度为 9。
    """

    # 创建一个可变副本，以避免修改原始传入的列表
    filtered_list = list(collage_results)

    # 1. 检查是否需要处理
    if len(filtered_list) <= 9:
        return filtered_list

    # --- 规则 1: 移除所有失败的项 ---
    # (我们假设 "失败" 指的是字典中明确包含 "success": False)
    # (使用 .get("success") is not False 会安全地保留 "success": True 和 "success" 键不存在的项)
    filtered_list = [c for c in filtered_list if c.get("success") is not False]

    if len(filtered_list) <= 9:
        return filtered_list

    # --- 规则 2: 如果还大于9 (因为规则2没找到足够的多图拼图) ---
    # 随机移除，直到长度为 9

    while len(filtered_list) > 9:
        # 随机选择一个索引并移除
        remove_index = random.randint(0, len(filtered_list) - 1)
        filtered_list.pop(remove_index)

    return filtered_list
