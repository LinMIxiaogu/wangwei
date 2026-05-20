import logging
import os
from typing import Any, Dict, Optional, List

import aiohttp

logger = logging.getLogger(__name__)

# Tikhub 小红书热榜接口与鉴权配置
API_URL = "https://api.tikhub.io/api/v1/xiaohongshu/web_v2/fetch_hot_list"


def _resolve_token(explicit_token: Optional[str]) -> str:
    """
    解析鉴权 Token，优先使用显式入参，其次使用环境变量，最后回落到内置示例值。
    """
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()
    env_token = os.getenv("TIKHUB_XHS_TOKEN", "").strip()
    if env_token:
        return env_token
    raise ValueError("Tikhub 小红书热榜接口鉴权 Token 未通过参数或环境变量提供")


def _build_headers(token: str) -> Dict[str, str]:
    """
    构建请求头，尽量还原提供的 cURL 头信息。
    """
    return {
        "Authorization": f"Bearer {token}",
        "Cookie": "Bearer=",
        "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
        "Accept": "*/*",
        "Host": "api.tikhub.io",
        "Connection": "keep-alive",
    }


def _extract_items_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    兼容多种返回结构，提取 items 列表：
    - 顶层完整结构: payload['data']['data']['items']
    - 仅返回 data:  payload['data']['items']
    - 直接返回列表:  payload['items']
    """
    candidate_paths = [
        ["data", "data", "items"],
        ["data", "items"],
        ["items"],
    ]
    for path in candidate_paths:
        node: Any = payload
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            return node  # type: ignore[return-value]
    return []


async def get_xhs_hot_leaderboard(
        token: Optional[str] = None,
        timeout_seconds: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    获取小红书热榜数据（通过 Tikhub Web V2 接口）。

    最终返回:
    - 成功: 热榜 items 列表
    - 失败: 空列表 []
    """
    try:
        resolved_token = _resolve_token(token)
        headers = _build_headers(resolved_token)
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_URL, headers=headers) as resp:
                text_body = await resp.text()
                if resp.status != 200:
                    logger.error("xhs_hot_leaderboard_http_error: %s - %s", resp.status, text_body)
                    return []

                # 解析 JSON 响应
                try:
                    payload = await resp.json(content_type=None)
                except Exception as parse_err:
                    logger.exception("xhs_hot_leaderboard_parse_error: %s", str(parse_err))
                    return []

                # Tikhub 顶层 code==200 表示请求成功
                top_code = payload.get("code")
                if top_code != 200:
                    logger.error("xhs_hot_leaderboard_api_error: %s", payload)
                    return []

                # 成功：提取 items
                return _extract_items_from_payload(payload)
    except Exception as e:
        logger.exception("xhs_hot_leaderboard_unexpected_error: %s", str(e))
        return []


async def get_xhs_hot_leaderboard_from_cache(
        cache_url: str,
        timeout_seconds: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    通过 Tikhub 响应中提供的 cache_url 直接获取缓存结果（24小时有效，且不再计费）。

    最终返回:
    - 成功: 热榜 items 列表
    - 失败: 空列表 []
    """
    if not cache_url or not cache_url.startswith("http"):
        return []

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(cache_url) as resp:
                text_body = await resp.text()
                if resp.status != 200:
                    logger.error("xhs_hot_leaderboard_cache_http_error: %s - %s", resp.status, text_body)
                    return []

                try:
                    payload = await resp.json(content_type=None)
                except Exception as parse_err:
                    logger.exception("xhs_hot_leaderboard_cache_parse_error: %s", str(parse_err))
                    return []

                # 兼容缓存可能返回的多种结构
                return _extract_items_from_payload(payload)
    except Exception as e:
        logger.exception("xhs_hot_leaderboard_cache_unexpected_error: %s", str(e))
        return []


__all__ = ["get_xhs_hot_leaderboard", "get_xhs_hot_leaderboard_from_cache"]
