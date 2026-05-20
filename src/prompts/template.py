import logging
import os
import re
from datetime import datetime

# from app.qconfig import common_config
# from app.utils import QMonitor

WEEKDAY_MAP = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

logger = logging.getLogger(__name__)


def get_format_now():
    """
    :return: 示例: 2025-07-11 20:14:57 Fri(周五)
    """
    now = datetime.now()
    format_str = now.strftime("%Y-%m-%d %H:%M:%S %a")
    weekday_desc = WEEKDAY_MAP[now.weekday()]
    return f"{format_str}({weekday_desc})"


def get_format_current_date(format_str: str = "%Y-%m-%d %H:%M:%S %a"):
    """
    :return: 示例: 2025-07-11 20:14:57 Fri(周五)
    """
    now = datetime.now()
    format_str = now.strftime(format_str)
    return f"{format_str}"


# def get_prompt_template(prompt_name: str) -> str:
#     # 获取远程的配置
#     remote_template = fetcher.get(f"{prompt_name}.md", "")
#
#     # 如果 remote_template 是 None，则用空字符串代替再 strip
#     use_config_prompt = len((remote_template or "").strip()) > 0
#     QMonitor.record_one(f"use_config_prompt_{prompt_name}_res_{use_config_prompt}")
#     if use_config_prompt:
#         template = remote_template
#     else:
#         logger.log(logging.INFO,
#                    f"[get_prompt_template] 未获取到 {prompt_name} 的配置，使用本地文件")
#         template = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md"),
#                         encoding='utf-8').read()
#     # Escape curly braces using backslash
#     template = template.replace("{", "{{").replace("}", "}}")
#     # Replace `<<VAR>>` with `{VAR}`
#     template = re.sub(r"<<([^>>]+)>>", r"{\1}", template)
#     return template


def get_prompt_template_local(prompt_name: str) -> str:
    template = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md"),
                    encoding='utf-8').read()
    # Escape curly braces using backslash
    template = template.replace("{", "{{").replace("}", "}}")
    # Replace `<<VAR>>` with `{VAR}`
    template = re.sub(r"<<([^>>]+)>>", r"{\1}", template)
    return template


def get_prompt_template_formatted(prompt_name: str, **kwargs) -> str:
    """
    获取并格式化prompt模板

    Args:
        prompt_name: prompt文件名（不含.md后缀）
        **kwargs: 模板变量，使用 <<VAR_NAME>> 格式在模板中定义

    Returns:
        格式化后的prompt字符串

    Example:
        template = get_prompt_template_formatted("vlm_choose",
                                                 VIDEO_FULL_TRANSCRIPT="字幕内容",
                                                 FRAME_COUNT=10,
                                                 FRAME_LIST="帧列表")
    """
    template = open(os.path.join(os.path.dirname(__file__), f"{prompt_name}.md"),
                    encoding='utf-8').read()
    # Replace `<<VAR>>` with actual values from kwargs
    for key, value in kwargs.items():
        placeholder = f"<<{key}>>"
        template = template.replace(placeholder, str(value))
    # Replace any remaining `<<VAR>>` with empty string (for variables not provided)
    template = re.sub(r"<<([^>>]+)>>", "", template)
    return template
