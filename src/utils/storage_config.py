"""
项目数据存储配置
定义音频文件、关键帧文件等的存储路径和文件夹结构
"""
from datetime import datetime
from pathlib import Path
from typing import Optional


class StorageConfig:
    """存储配置类，管理项目数据文件的存储路径"""

    def __init__(self, base_data_dir: Optional[str] = None):
        """
        初始化存储配置
        
        Args:
            base_data_dir: 基础数据目录，如果不指定则使用项目根目录下的data文件夹
        """
        if base_data_dir:
            self.base_data_dir = Path(base_data_dir)
        else:
            # 默认使用项目根目录下的data文件夹
            project_root = Path(__file__).parent.parent.parent
            self.base_data_dir = project_root / "data"

        # 确保基础数据目录存在
        self.base_data_dir.mkdir(parents=True, exist_ok=True)

    def get_video_processing_dir(self, video_filename: str) -> Path:
        """
        获取视频处理的专用目录
        
        Args:
            video_filename: 视频文件名（包含扩展名）
            
        Returns:
            Path: 视频处理目录路径，格式为 data/视频文件名_YYYYMMDD_HHMMSS
        """
        # 获取不含扩展名的文件名
        video_name = Path(video_filename).stem

        # 获取当前时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 创建目录名
        dir_name = f"{video_name}_{timestamp}"

        # 创建完整路径
        processing_dir = self.base_data_dir / dir_name
        processing_dir.mkdir(parents=True, exist_ok=True)

        return processing_dir

    def get_audio_dir(self, processing_dir: Path) -> Path:
        """
        获取音频文件存储目录
        
        Args:
            processing_dir: 视频处理目录
            
        Returns:
            Path: 音频文件目录路径
        """
        audio_dir = processing_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir

    def get_keyframes_dir(self, processing_dir: Path) -> Path:
        """
        获取关键帧文件存储目录
        
        Args:
            processing_dir: 视频处理目录
            
        Returns:
            Path: 关键帧文件目录路径
        """
        keyframes_dir = processing_dir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)
        return keyframes_dir

    def get_audio_file_path(self, processing_dir: Path, video_filename: str) -> Path:
        """
        获取音频文件的完整路径
        
        Args:
            processing_dir: 视频处理目录
            video_filename: 原始视频文件名
            
        Returns:
            Path: 音频文件完整路径
        """
        audio_dir = self.get_audio_dir(processing_dir)
        video_name = Path(video_filename).stem
        audio_filename = f"{video_name}_audio.mp3"
        return audio_dir / audio_filename

    def get_keyframe_file_path(self, processing_dir: Path, frame_number: int, timestamp_ms: int) -> Path:
        """
        获取关键帧文件的完整路径
        
        Args:
            processing_dir: 视频处理目录
            frame_number: 帧编号
            timestamp_ms: 时间戳（毫秒）
            
        Returns:
            Path: 关键帧文件完整路径
        """
        keyframes_dir = self.get_keyframes_dir(processing_dir)
        frame_filename = f"frame_{frame_number:03d}_{timestamp_ms:06d}.jpg"
        return keyframes_dir / frame_filename

    def cleanup_processing_dir(self, processing_dir: Path) -> bool:
        """
        清理处理目录（可选功能）
        
        Args:
            processing_dir: 要清理的处理目录
            
        Returns:
            bool: 清理是否成功
        """
        try:
            import shutil
            if processing_dir.exists():
                shutil.rmtree(processing_dir)
                return True
            return True
        except Exception:
            return False


# 创建全局存储配置实例
storage_config = StorageConfig()
