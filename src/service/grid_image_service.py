"""
九宫格图片处理服务
接收OSS URL链接，下载图片进行九宫格处理，然后上传回OSS并返回新的URL
"""
import asyncio
import logging
import os
import sys
import tempfile
import uuid
from typing import List, Optional
from urllib.parse import urlparse

from PIL import Image

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from obs_service import obs_service

logger = logging.getLogger(__name__)


class GridImageService:
    """九宫格图片处理服务类"""

    def __init__(self):
        """初始化服务"""
        self.obs_service = obs_service
        self.temp_dir = tempfile.mkdtemp(prefix="grid_image_")
        logger.info(f"九宫格图片处理服务初始化完成，临时目录: {self.temp_dir}")

    async def download_image_from_url(self, url: str, filename: str) -> Optional[str]:
        """
        从URL下载图片到本地临时文件
        Args:
            url: 图片URL
            filename: 本地文件名
        Returns:
            str: 本地文件路径，失败返回None
        """
        try:
            local_path = os.path.join(self.temp_dir, filename)
            # 检查是否是OBS URL
            parsed_url = urlparse(url)
            if 'myhuaweicloud.com' in parsed_url.netloc or 'obs.' in parsed_url.netloc:
                # 从OBS URL中提取object_key
                object_key = parsed_url.path.lstrip('/')
                logger.info(f"检测到OBS URL，使用OBS服务下载: {object_key}")
                # 使用obs_service下载
                success = await self.obs_service.download_file(object_key, local_path)
                if success:
                    logger.info(f"OBS图片下载成功: {url} -> {local_path}")
                    return local_path
                else:
                    logger.error(f"OBS图片下载失败: {url}")
                    return None
        except Exception as e:
            logger.error(f"下载图片异常: {str(e)}")
            return None

    async def create_grid_image(self, image_paths: List[str]) -> Optional[str]:
        """
        创建九宫格图片并上传到OSS
        Args:
            image_paths: 图片路径列表（最多9张）
        Returns:
            str: OSS图片链接，失败返回None
        """
        try:
            if len(image_paths) == 0:
                logger.error("没有提供图片路径")
                return None

            # 打开所有图片
            images = []
            for path in image_paths:
                if os.path.exists(path):
                    images.append(Image.open(path))
                else:
                    logger.warning(f"图片文件不存在: {path}")

            if not images:
                logger.error("没有有效的图片文件")
                return None

            # 如果图片数量不足9张，重复使用现有图片
            while len(images) < 9:
                images.extend(images[:min(9 - len(images), len(images))])

            # 只取前9张图片
            images = images[:9]

            # 获取第一张图片的尺寸作为基准
            width, height = images[0].size

            # 创建新的图片，尺寸为原图片宽度的3倍，高度的3倍
            new_width = width * 3
            new_height = height * 3
            new_image = Image.new("RGB", (new_width, new_height))

            # 将九张图片按照九宫格布局粘贴到新的图片上
            positions = [
                (0, 0), (width, 0), (2 * width, 0),
                (0, height), (width, height), (2 * width, height),
                (0, 2 * height), (width, 2 * height), (2 * width, 2 * height)
            ]

            for i, (image, position) in enumerate(zip(images, positions)):
                # 调整图片尺寸以匹配基准尺寸
                if image.size != (width, height):
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                new_image.paste(image, position)

            # 生成临时文件路径
            temp_filename = f"grid_{uuid.uuid4().hex[:8]}.jpg"
            temp_output_path = os.path.join(self.temp_dir, temp_filename)

            # 保存拼接后的图片到临时文件
            new_image.save(temp_output_path, quality=95)
            logger.info(f"九宫格图片创建成功: {temp_output_path}")

            # 关闭所有图片对象
            for image in images:
                image.close()
            new_image.close()

            # 上传到OSS
            oss_url = await self.obs_service.upload_file(temp_output_path, temp_filename)

            # 清理临时文件
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except:
                pass

            if oss_url:
                logger.info(f"九宫格图片上传OSS成功: {oss_url}")
                return oss_url
            else:
                logger.error("九宫格图片上传OSS失败")
                return None

        except Exception as e:
            logger.error(f"创建九宫格图片异常: {str(e)}")
            return None

    async def process_single_image_grid(self, image_url: str) -> Optional[str]:
        """
        处理单张图片的九宫格（将同一张图片重复9次）
        Args:
            image_url: 图片URL
        Returns:
            str: 处理后的OSS URL，失败返回None
        """
        try:
            # 从URL解析文件名
            parsed_url = urlparse(image_url)
            original_filename = os.path.basename(parsed_url.path)
            if not original_filename:
                original_filename = "image.jpg"
            # 下载图片
            local_image_path = await self.download_image_from_url(
                image_url,
                f"original_{original_filename}"
            )
            if not local_image_path:
                return None
            # 创建九宫格图片（使用同一张图片9次）并直接上传到OSS
            oss_url = await self.create_grid_image([local_image_path] * 9)

            # 清理临时文件
            try:
                if os.path.exists(local_image_path):
                    os.remove(local_image_path)
            except:
                pass

            return oss_url
        except Exception as e:
            logger.error(f"处理单张图片九宫格异常: {str(e)}")
            return None

    async def process_multiple_images_grid(self, image_urls: List[str]) -> Optional[str]:
        """
        处理多张图片的九宫格
        Args:
            image_urls: 图片URL列表（最多9张）
        Returns:
            str: 处理后的OSS URL，失败返回None
        """
        try:
            if not image_urls:
                logger.error("没有提供图片URL")
                return None

            # 限制最多9张图片
            image_urls = image_urls[:9]
            # 下载所有图片
            download_tasks = []
            local_paths = []
            for i, url in enumerate(image_urls):
                filename = f"image_{i + 1}.jpg"
                download_tasks.append(self.download_image_from_url(url, filename))

            # 并发下载
            downloaded_paths = await asyncio.gather(*download_tasks, return_exceptions=True)
            # 过滤成功下载的图片
            valid_paths = [path for path in downloaded_paths if isinstance(path, str) and path]
            if not valid_paths:
                logger.error("没有成功下载任何图片")
                return None
            # 创建九宫格图片并直接上传到OSS
            oss_url = await self.create_grid_image(valid_paths)

            # 清理临时文件
            try:
                for path in valid_paths:
                    if os.path.exists(path):
                        os.remove(path)
            except:
                pass

            return oss_url

        except Exception as e:
            logger.error(f"处理多张图片九宫格异常: {str(e)}")
            return None

    async def process_grid_image(self, image_urls: List[str]) -> Optional[str]:
        """
        处理九宫格图片的主入口方法
        Args:
            image_urls: 图片URL列表
        Returns:
            str: 处理后的OSS URL，失败返回None
        """
        if not image_urls:
            logger.error("没有提供图片URL")
            return None

        if len(image_urls) == 1:
            # 单张图片，创建重复九宫格
            return await self.process_single_image_grid(image_urls[0])
        else:
            # 多张图片，创建组合九宫格
            return await self.process_multiple_images_grid(image_urls)

    def __del__(self):
        """析构函数，清理临时目录"""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"临时目录已清理: {self.temp_dir}")
        except:
            pass


if __name__ == "__main__":
    # 测试代码
    async def test_grid_service():
        grid_image_service = GridImageService()
        test_urls = [
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg",
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251027_095924_frame_003_004033.jpg"
        ]

        result = await grid_image_service.process_grid_image(test_urls)
        print(f"九宫格图片处理结果: {result}")


    # 运行测试
    asyncio.run(test_grid_service())
