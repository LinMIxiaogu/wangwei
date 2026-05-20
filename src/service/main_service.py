"""视频音频提取服务。"""
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from .obs_service import obs_service
from ..utils.storage_config import storage_config

logger = logging.getLogger(__name__)


class MainService:
    """主要服务类"""

    def __init__(self):
        pass

    async def extract_audio(self, video_path: str, output_path: Optional[str] = None,
                            current_processing_dir: Optional[Path] = None) -> Optional[str]:
        """
        从视频文件中提取音频
        
        Args:
            video_path: 视频文件路径
            output_path: 输出音频文件路径（如果指定则使用指定路径，否则使用新的存储结构）
            current_processing_dir: 当前处理目录
            
        Returns:
            str: 音频文件路径，失败返回None
        """
        try:
            if not os.path.exists(video_path):
                logger.error(f"视频文件不存在: {video_path}")
                return None

            # 生成输出路径
            if not output_path:
                if current_processing_dir:
                    # 使用新的存储结构
                    video_filename = Path(video_path).name
                    output_path = str(
                        storage_config.get_audio_file_path(current_processing_dir, video_filename))
                else:
                    # 如果没有处理目录，抛出错误
                    raise ValueError("必须提供output_path或current_processing_dir")

            # 使用ffmpeg提取音频
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vn",  # 不处理视频流
                "-acodec", "mp3",  # 音频编码为mp3
                "-ar", "16000",  # 采样率16kHz
                "-ac", "1",  # 单声道
                "-y",  # 覆盖输出文件
                output_path
            ]

            logger.info(f"开始提取音频: {video_path} -> {output_path}")

            # 执行ffmpeg命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                encoding='utf-8',  # 指定编码
                errors='ignore'  # 忽略编码错误
            )

            if result.returncode == 0:
                logger.info(f"音频提取成功: {output_path}")
                return output_path
            else:
                logger.error(f"ffmpeg执行失败: {result.stderr}")
                return None
        except Exception as e:
            logger.exception("提取音频时发生错误")
            return None

    async def upload_audio_file(self, audio_path: str) -> Optional[str]:
        """
        上传音频文件并返回URL
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            str: 音频文件的URL，失败返回None
        """
        try:
            # 使用OBS服务上传音频文件
            audio_url = await obs_service.upload_file(audio_path)

            if audio_url:
                logger.info(f"音频文件上传成功: {audio_path} -> {audio_url}")
                return audio_url
            else:
                logger.error(f"音频文件上传失败: {audio_path}")
                return None

        except Exception as e:
            logger.error(f"上传音频文件时发生错误: {str(e)}")
            return None

    def cleanup_temp_files(self, file_path: str) -> bool:
        """
        清理临时文件
        
        Args:
            file_path: 要删除的文件路径
            
        Returns:
            bool: 删除成功返回True
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"临时文件已删除: {file_path}")
                return True
            return True
        except Exception as e:
            logger.error(f"删除临时文件失败: {str(e)}")
            return False


# 创建服务实例
main_service = MainService()
