"""服务模块，提供各种业务服务"""

from .image_score import ImageScoreService, image_score_service
from .main_service import MainService, main_service
from .obs_service import OBSService, obs_service, ProgressCallback

__all__ = [
    # 服务类
    "MainService", "main_service",
    "OBSService", "obs_service", "ProgressCallback",
    "ImageScoreService", "image_score_service",
]
