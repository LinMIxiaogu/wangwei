import asyncio
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


class ImageSearchService:
    """图像搜索服务类"""

    def __init__(self, base_url="http://pp-xhs-unified.xhs-ai-produce-2.inner3.beta.qunar.com"):
        self.base_url = base_url
        self.search_url = f"{base_url}/baidu/image/library/crawl"

    async def search_images(self, keywords: str, page: int = 1, limit: int = 5) -> Dict[str, Any]:
        """
        搜索图像
        
        Args:
            keywords: 搜索关键词
            page: 页码，默认为1
            limit: 每页数量，默认为5
            
        Returns:
            dict: 搜索结果
        """
        try:
            # 构建查询参数
            params = {
                "keywords": keywords,
                "page": str(page),
                "limit": str(limit)
            }

            # 构建完整URL
            url = f"{self.search_url}?{urlencode(params)}"

            logger.info(f'搜索图像，关键词: {keywords}, 页码: {page}, 数量: {limit}')

            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        logger.info(
                            f'图像搜索成功，关键词: {keywords}，找到 {response_data.get("data", {}).get("totalImages", 0)} 张图片')
                        return response_data
                    else:
                        error_msg = f'图像搜索请求失败，状态码: {response.status}'
                        logger.error(error_msg)
                        raise Exception(error_msg)

        except Exception as e:
            logger.error(f'图像搜索异常: {str(e)}')
            raise

    def transform_search_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将搜索响应数据转换为简洁的数组格式
        
        Args:
            response_data: 原始响应数据
            
        Returns:
            list: 转换后的简洁格式数据
        """
        result = []

        if response_data.get("code") == 200 and "data" in response_data:
            data = response_data["data"]
            images = data.get("images", [])

            for image in images:
                item = {
                    "original_url": image.get("originImageUrl", ""),
                    "processed_url": image.get("imageUrl", ""),
                    "title": image.get("titleShow", ""),
                    "score": image.get("auroraScore", 0.0),
                    "width": image.get("width", 0),
                    "height": image.get("height", 0)
                }
                result.append(item)

        return result

    async def search_and_transform(self, keywords: str, page: int = 1, limit: int = 5) -> Dict[
        str, Any]:
        """
        搜索图像并返回转换后的格式
        
        Args:
            keywords: 搜索关键词
            page: 页码，默认为1
            limit: 每页数量，默认为5
            
        Returns:
            dict: 包含搜索结果和元数据的字典
        """
        try:
            # 执行搜索
            raw_response = await self.search_images(keywords, page, limit)

            # 转换数据格式
            transformed_images = self.transform_search_response(raw_response)

            # 提取元数据
            data = raw_response.get("data", {})

            result = {
                "status": "SUCCESS" if raw_response.get("code") == 200 else "FAILED",
                "message": raw_response.get("msg", ""),
                "keywords": keywords,
                "total_images": data.get("totalImages", 0),
                "total_num": data.get("totalNum", 0),
                "processed_images": data.get("processedImages", 0),
                "cost_time": data.get("costTime", ""),
                "page": data.get("page", str(page)),
                "images": transformed_images,
                "raw_response": raw_response  # 保留原始响应用于调试
            }

            return result

        except Exception as e:
            logger.error(f'图像搜索和转换失败: {str(e)}')
            return {
                "status": "ERROR",
                "message": str(e),
                "keywords": keywords,
                "total_images": 0,
                "total_num": 0,
                "processed_images": 0,
                "cost_time": "",
                "page": str(page),
                "images": [],
                "raw_response": None
            }

    async def get_best_image(self, keywords: str, min_score: float = 0.3) -> Optional[
        Dict[str, Any]]:
        """
        获取最佳图像（评分最高的图像）
        
        Args:
            keywords: 搜索关键词
            min_score: 最小评分阈值，默认0.3
            
        Returns:
            dict: 最佳图像信息，如果没有找到合适的图像则返回None
        """
        try:
            result = await self.search_and_transform(keywords, page=1, limit=10)

            if result["status"] != "SUCCESS" or not result["images"]:
                return {
                    "status": result["status"],
                    "message": result.get("message", "未找到图像"),
                    "keywords": keywords,
                    "best_image": None,
                    "total_images": result.get("total_images", 0),
                    "qualified_images": 0
                }

            # 筛选评分大于等于最小阈值的图像
            qualified_images = [img for img in result["images"] if img["score"] >= min_score]

            if not qualified_images:
                logger.warning(f'没有找到评分大于等于 {min_score} 的图像，关键词: {keywords}')
                return {
                    "status": "FAILED",
                    "message": f"没有找到评分大于等于 {min_score} 的图像",
                    "keywords": keywords,
                    "best_image": None,
                    "total_images": len(result["images"]),
                    "qualified_images": 0
                }

            # 按评分降序排序，返回最高分的图像
            best_image = max(qualified_images, key=lambda x: x["score"])

            logger.info(
                f'找到最佳图像，关键词: {keywords}，评分: {best_image["score"]}, 标题: {best_image["title"]}')

            return {
                "status": "SUCCESS",
                "message": "搜索成功",
                "keywords": keywords,
                "best_image": best_image,
                "total_images": len(result["images"]),
                "qualified_images": len(qualified_images)
            }

        except Exception as e:
            logger.error(f'获取最佳图像失败: {str(e)}')
            return {
                "status": "ERROR",
                "message": str(e),
                "keywords": keywords,
                "best_image": None,
                "total_images": 0,
                "qualified_images": 0
            }


# 创建全局实例
image_search_service = ImageSearchService()


async def main():
    """测试图像搜索服务"""
    try:
        # 测试基本搜索功能
        print("=== 测试基本搜索功能 ===")
        result = await image_search_service.search_and_transform("天安门广场")

        print("搜索结果:")
        print(f"状态: {result['status']}")
        print(f"关键词: {result['keywords']}")
        print(f"总图片数: {result['total_images']}")
        print(f"处理时间: {result['cost_time']}")
        print(f"找到图片数: {len(result['images'])}")

        if result['images']:
            print("\n前3张图片信息:")
            for i, img in enumerate(result['images'][:3], 1):
                print(f"  图片 {i}:")
                print(f"    标题: {img['title']}")
                print(f"    评分: {img['score']}")
                print(f"    尺寸: {img['width']}x{img['height']}")
                print(f"    处理后URL: {img['processed_url']}")

        # 测试获取最佳图像功能
        print("\n=== 测试获取最佳图像功能 ===")
        best_result = await image_search_service.get_best_image("天安门广场", min_score=0.4)

        if best_result:
            best_img = best_result['best_image']
            print(f"最佳图像:")
            print(f"  标题: {best_img['title']}")
            print(f"  评分: {best_img['score']}")
            print(f"  尺寸: {best_img['width']}x{best_img['height']}")
            print(f"  候选图片总数: {best_result['total_candidates']}")
            print(f"  合格图片数: {best_result['qualified_candidates']}")
        else:
            print("未找到合适的最佳图像")

        print("\nSUCCESS!")

    except Exception as e:
        print(f"FAILED: {str(e)}")
        import traceback
        print(f"错误详情:\n{traceback.format_exc()}")
        exit(1)


if __name__ == '__main__':
    asyncio.run(main())
