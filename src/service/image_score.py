"""
图片质量评分服务
使用 Everypixel API 对图片进行质量评分
支持从URL下载图片并进行评分
"""
import logging
import os
import sys
import tempfile
from typing import Optional, Dict, Any
from urllib.parse import urlparse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from obs_service import obs_service

logger = logging.getLogger(__name__)


class ImageScoreService:
    """图片质量评分服务类"""

    def __init__(self, client_id: str = "eWIHKwnAgXg4d8pdn3cNNhhU",
                 client_secret: str = "qMZdMzbnWwXcJmRg9a2zsFXNfFi0geyH6AsFd5VS40BGtkt8"):
        """
        初始化图片评分服务
        
        Args:
            client_id: Everypixel API 客户端ID
            client_secret: Everypixel API 客户端密钥
        """
        # 从环境变量或参数获取API凭证
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_url = 'https://api.everypixel.com/v1/quality_ugc'
        self.temp_dir = tempfile.mkdtemp(prefix='image_score_')

    async def download_image_from_url(self, url: str) -> Optional[str]:
        """
        从URL下载图片到本地临时文件
        
        Args:
            url: 图片URL
            
        Returns:
            str: 本地文件路径，如果下载失败返回None
        """
        try:
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path) or 'temp_image.jpg'
            local_path = os.path.join(self.temp_dir, filename)

            # 检查是否是OBS URL
            if 'obs.cn-north-4.myhuaweicloud.com' in url:
                # 从OBS URL提取object_key
                # URL格式: https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/filename.jpg
                url_parts = url.split('/')
                if 'uploads' in url_parts:
                    # 找到uploads的位置，获取完整的object_key
                    uploads_index = url_parts.index('uploads')
                    object_key = '/'.join(url_parts[uploads_index:])
                else:
                    # 如果没有uploads前缀，假设是直接的文件名
                    filename = url_parts[-1]
                    object_key = f"uploads/{filename}"

                logger.info(f"从OBS下载图片: {object_key}")

                # 使用obs_service下载
                success = await obs_service.download_file(object_key, local_path)
                if success:
                    logger.info(f"图片下载成功: {local_path}")
                    return local_path
                else:
                    logger.error(f"从OBS下载图片失败: {object_key}")
                    return None
        except Exception as e:
            logger.error(f"下载图片失败 {url}: {str(e)}")
            return None

    async def score_image_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        对本地图片文件进行评分
        
        Args:
            file_path: 本地图片文件路径
            
        Returns:
            dict: 评分结果，包含质量分数等信息
        """
        try:
            # 将路径中的反斜杠替换为正斜杠，确保路径格式统一
            # normalized_path = file_path.replace("\\", "/")
            if not os.path.exists(file_path):
                logger.error(f"图片文件不存在: {file_path}")
                return None

            # 使用异步方式上传图片
            import aiohttp
            with open(file_path, 'rb') as image_file:
                data = aiohttp.FormData()
                data.add_field('data', image_file, filename=os.path.basename(file_path))
                logger.info(f"正在评分图片: {file_path}")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                            self.api_url,
                            data=data,
                            auth=aiohttp.BasicAuth(self.client_id, self.client_secret),
                            timeout=aiohttp.ClientTimeout(total=10),
                            proxy=os.getenv("IMAGE_QUANTITY_PROXY")
                    ) as response:
                        response.raise_for_status()
                        result = await response.json()
                        if result and 'status' in result and result['status'] == 'ok':
                            return result['quality']
                        else:
                            logger.error(f"API返回错误: {result}")
                            return None

        except aiohttp.ClientError as e:
            logger.exception(f"API请求失败")
            return None
        except Exception as e:
            logger.exception(f"图片评分失败")
            return None

    async def score_image_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        从URL获取图片并进行评分
        
        Args:
            url: 图片URL
            
        Returns:
            dict: 评分结果，包含质量分数等信息
        """
        local_path = None
        try:
            # 下载图片
            local_path = await self.download_image_from_url(url)
            if not local_path:
                return None

            # 评分图片
            result = self.score_image_from_file(local_path)
            return result

        finally:
            # 清理临时文件
            if local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                    logger.info(f"临时文件已清理: {local_path}")
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {str(e)}")

    def extract_score(self, result: Dict[str, Any]) -> Optional[float]:
        """
        从评分结果中提取质量分数
        
        Args:
            result: API返回的完整结果
            
        Returns:
            float: 质量分数 (0-1之间)
        """
        try:
            if result and 'quality' in result:
                quality = result['quality']
                if 'score' in quality:
                    return float(quality['score'])
            return None
        except Exception as e:
            logger.error(f"提取分数失败: {str(e)}")
            return None

    def cleanup(self):
        """清理临时目录"""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"临时目录已清理: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理临时目录失败: {str(e)}")

    def __del__(self):
        """析构函数，自动清理临时目录"""
        self.cleanup()


# 创建服务实例
image_score_service = ImageScoreService()
