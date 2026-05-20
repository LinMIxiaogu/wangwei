"""
工作流记录扩展字段解析工具
提供 ext 字段的解析功能，避免循环导入
"""
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def parse_state_from_ext(ext: Optional[str]) -> Dict[str, Any]:
    """
    从 ext 字段中解析 state 数据

    参数:
        ext: ext 字段的 JSON 字符串

    返回:
        解析后的 state 字典，如果解析失败则返回空字典
    """
    state_detail = {}
    if not ext:
        return state_detail

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

    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.exception(f"解析 ext 字段失败: {str(e)}")
        state_detail = {}

    return state_detail

