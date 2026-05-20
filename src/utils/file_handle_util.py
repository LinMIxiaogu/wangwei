import os
import re
from typing import Optional


def _parse_time_from_filename(filename: str) -> Optional[float]:
    """
    从文件名中解析时间戳，并统一返回毫秒。

    支持两种格式:
    1. ..._time_5000ms_... (毫秒)
    2. ..._time_5.0_sharp_... (秒)
    """

    # 优先匹配毫秒 ( ..._time_12345ms_... )
    # (e.g., scene_0001_frame_150_time_5000ms_sharp_102.jpg)
    match_ms = re.search(r"_time_(\d+\.?\d*)ms_", filename)
    if match_ms:
        try:
            # logger.debug(f"解析到毫秒: {match_ms.group(1)}")
            return float(match_ms.group(1))  # 直接返回毫秒
        except ValueError:
            pass

    # 如果毫秒匹配失败，尝试匹配秒 ( ..._time_5.0_sharp_... )
    # (e.g., scene_0001_frame_0_time_0.0_sharp_720.jpg)
    match_sec = re.search(r"_time_(\d+\.?\d*)_sharp_", filename)
    if match_sec:
        try:
            seconds = float(match_sec.group(1))
            # logger.debug(f"解析到秒: {seconds}s，转换为 {seconds * 1000}ms")
            return seconds  # 转换成毫秒
        except ValueError:
            pass

    return None


#
def get_file_project_path() -> Optional[str]:
    """
    获取项目根目录路径
    通过查找项目根目录的标识文件（如 requirements.txt, .gitignore 等）来确定项目根目录
    
    Returns:
        Optional[str]: 项目根目录的绝对路径，如果找不到则返回 None
    """
    # 从当前文件开始向上查找项目根目录
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 项目根目录的标识文件
    project_markers = [
        'requirements.txt',
        '.gitignore',
        'README.md',
        '.env'
    ]

    # 向上遍历目录，直到找到项目根目录或到达文件系统根目录
    while current_dir != os.path.dirname(current_dir):  # 防止到达文件系统根目录
        # 检查当前目录是否包含项目标识文件
        for marker in project_markers:
            if os.path.exists(os.path.join(current_dir, marker)):
                return current_dir

        # 向上一级目录
        current_dir = os.path.dirname(current_dir)

    return None
