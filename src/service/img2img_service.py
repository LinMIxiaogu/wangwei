import asyncio
import json
import logging
import os
import uuid
from typing import Dict, Any, Optional

import aiohttp

from src.prompts.template import get_prompt_template_formatted
from src.service.obs_service import obs_service

logger = logging.getLogger(__name__)

# 使用新的图像增强服务
from .image_enhancement_service import image_enhancement_service


class Img2ImgService:
    """图生图服务类"""

    def __init__(
            self,
            key="qunar-hr-hackathon2025-37-beta",
            password="6pw85c",
            api_type="BYTEDANCE",
            app_code="pf_have_head",
            project="hackathon",
            api_version="v1",
            user_identity_info="linyang.zhong"
    ):
        """
        初始化图生图服务
        
        Args:
            key: API密钥
            password: API密码
            api_type: API类型
            app_code: 应用代码
            project: 项目名称
            api_version: API版本
            user_identity_info: 用户身份信息
        """
        self.key = key
        self.password = password
        self.api_type = api_type
        self.app_code = app_code
        self.project = project
        self.api_version = api_version
        self.user_identity_info = user_identity_info

        self.submit_url = "http://llm.video.api.corp.qunar.com/Image/img2img/addtask"
        self.query_url = "http://llm.video.api.corp.qunar.com/Image/taskstatus"

    def _generate_trace_id(self) -> str:
        """生成唯一的trace ID"""
        return f"{self.app_code}_{uuid.uuid4().hex[:32]}"

    def _build_header(self, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """构建请求头"""
        if trace_id is None:
            trace_id = self._generate_trace_id()

        return {
            "key": self.key,
            "apiType": self.api_type,
            "appCode": self.app_code,
            "project": self.project,
            "traceID": trace_id,
            "password": self.password,
            "apiVersion": self.api_version,
            "userIdentityInfo": self.user_identity_info,
            "externalUserIdentityInfo": ""
        }

    async def submit_task(self,
                          prompt: str,
                          source_image: str,
                          aspect_ratio: str = "16:9",
                          seed: int = 42,
                          style_weight: float = 0.8,
                          size: str = "4k",
                          model: str = "doubao-seedream-4-0-250828") -> tuple[str, str]:
        """
        提交图生图任务
        
        Args:
            prompt: 提示词
            source_image: 源图片URL
            aspect_ratio: 宽高比，默认"16:9"
            seed: 随机种子，默认42
            style_weight: 风格权重，默认0.8
            size: 图片尺寸，默认"4k"
            model: 模型名称
            
        Returns:
            tuple: (task_id, trace_id)
        """
        trace_id = self._generate_trace_id()

        request_data = {
            "Header": self._build_header(trace_id),
            "Payload": {
                "taskType": "image2image",
                "model": model,
                "prompt": prompt,
                "sourceImage": source_image,
                "aspect_ratio": aspect_ratio,
                "seed": seed,
                "style_weight": style_weight,
                "size": size
            }
        }

        logger.info(f'Submit img2img task with trace_id: {trace_id}')

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self.submit_url,
                    json=request_data,
                    headers={"Content-Type": "application/json"}
            ) as response:
                response_data = await response.json()

                if response_data.get("Header", {}).get("Code") == 0:
                    task_id = response_data.get("Payload", {}).get("TaskId")
                    logger.info(f'Submit task success: {response_data.get("Header", {}).get("Message")}')
                    logger.info(f'Task ID: {task_id}')
                    return task_id, trace_id
                else:
                    error_msg = response_data.get("Header", {}).get("Message", "Unknown error")
                    logger.error(f'Submit task failed: {error_msg}')
                    raise Exception(f'Submit task failed: {error_msg}')

    async def query_task(self, task_id: str, trace_id: str) -> Dict[str, Any]:
        """
        查询图生图任务状态
        
        Args:
            task_id: 任务ID
            trace_id: 追踪ID
            
        Returns:
            dict: 任务状态响应数据
        """
        request_data = {
            "Header": self._build_header(trace_id),
            "Payload": {
                "taskId": task_id
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self.query_url,
                    json=request_data,
                    headers={"Content-Type": "application/json"}
            ) as response:
                response_data = await response.json()

                if response_data.get("Header", {}).get("Code") != 0:
                    error_msg = response_data.get("Header", {}).get("Message", "Unknown error")
                    logger.error(f'Query task failed: {error_msg}')
                    raise Exception(f'Query task failed: {error_msg}')

                return response_data

    def transform_img2img_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将图生图响应数据转换为简洁格式
        
        Args:
            response_data: 原始响应数据
            
        Returns:
            dict: 转换后的简洁格式数据
        """
        payload = response_data.get("Payload", {})
        qinfo = response_data.get("QInfo", {})

        result = {
            "task_id": payload.get("TaskId", ""),
            "status": payload.get("Status", ""),
            "media_url": payload.get("MediaUrl", ""),
            "consume": qinfo.get("Consume", 0),
            "balance": qinfo.get("Balance", 0),
            "billing_metric": qinfo.get("BillingMetric", ""),
            "original_consumption": qinfo.get("OriginalConsumption", "")
        }

        return result

    async def process_image(self,
                            prompt: str,
                            source_image: str) -> Dict[str, Any]:
        """
        处理图生图任务，现在使用 OpenRouter 图像增强服务
        
        Args:
            prompt: 提示词
            source_image: 源图片URL
            aspect_ratio: 宽高比，默认"16:9"
            seed: 随机种子（保留兼容性，实际不使用）
            style_weight: 风格权重（保留兼容性，实际不使用）
            size: 图片尺寸（保留兼容性，实际不使用）
            model: 模型名称（保留兼容性，实际不使用）
            max_wait_time: 最大等待时间（保留兼容性，实际不使用）
            
        Returns:
            dict: 转换后的简洁格式数据，兼容原有格式
        """
        try:
            logger.info(f'开始使用OpenRouter处理图像: {source_image}')

            # 调用图像增强服务，传递自定义提示词
            result = await image_enhancement_service.enhance_image_and_upload(source_image, custom_prompt=prompt)

            if result.get("success"):
                # 转换为兼容原有格式的响应
                transformed_data = {
                    "status": "SUCCESS",
                    "media_url": result.get("oss_url"),
                    "task_id": f"enhancement_{os.urandom(8).hex()}",  # 生成一个假的task_id保持兼容性
                    "consume": 0,  # OpenRouter的消费计算方式不同，暂时设为0
                    "balance": 0,  # 余额信息不适用
                    "billing_metric": "enhancement_tokens"
                }
                logger.info(f'图像处理完成: {source_image} -> {result.get("oss_url")}')
                return transformed_data
            else:
                # 处理失败
                error_msg = result.get("message", "图像处理失败")
                logger.error(f'图像处理失败: {error_msg}')
                raise Exception(error_msg)

        except Exception as e:
            logger.error(f'图像处理异常: {str(e)}')
            raise

    async def enhance_image_and_upload(self, image_url: str) -> Dict[str, Any]:
        """封装图像增强+上传OSS的业务逻辑。

        现在使用 OpenRouter 调用图像增强，保存到本地后上传到 OBS。

        返回结构示例：
        {
          "success": true,
          "final_url": "https://...",
          "source_url": "http://...",
          "oss_url": "https://..." | null,
          "enhancement_result": { ... }
        }
        """
        try:
            return await image_enhancement_service.enhance_image_and_upload(image_url)
        except Exception as e:
            logger.exception(f"图像质量增强处理异常: {image_url}")
            return {
                "success": False,
                "message": f"image_enhancement_error: {str(e)}",
                "enhancement_result": {}
            }

    async def enhance_xhs_cover_and_upload(
            self,
            title: str,
            full_caption: str,
            hashtags: list[str] | str,
            head_image_url: str,
    ) -> Dict[str, Any]:
        """小红书封面图优化：按 4:5 竖版比例生成封面风格并上传到 OSS。

        - 使用模板 `xhs_cover_optimization` 生成封面优化提示词。
        - 调用图生图接口，style_weight 适当提高（0.9），size 使用 "4k"。
        - 将返回的内网地址统一上传到 OSS，返回最终外链。
        """
        try:
            tags_text = " ".join(hashtags) if isinstance(hashtags, list) else (hashtags or "")
            cover_prompt = get_prompt_template_formatted(
                "xhs_cover_optimization",
                TITLE=title or "",
                FULL_CAPTION=full_caption or "",
                HASHTAGS=tags_text,
            )

            cover_result = await self.process_image(
                prompt=cover_prompt,
                source_image=head_image_url
            )

            if cover_result.get("status") == "SUCCESS" and cover_result.get("media_url"):
                source_url = cover_result["media_url"]
                oss_url = await obs_service.upload_from_url(source_url)
                final_url = oss_url or source_url
                logger.info(f"封面图优化成功: {head_image_url} -> {final_url}")
                return {
                    "success": True,
                    "final_url": final_url,
                    "source_url": source_url,
                    "oss_url": oss_url,
                    "enhancement_result": cover_result,
                }
            else:
                logger.info(f"封面图优化失败: {head_image_url}")
                return {
                    "success": False,
                    "message": f"xhs_cover_enhancement_error: {cover_result}",
                    "enhancement_result": cover_result,
                }
        except Exception as e:
            logger.exception(f"封面图优化处理异常: {head_image_url}")
            return {
                "success": False,
                "message": f"xhs_cover_enhancement_error: {str(e)}",
                "enhancement_result": {},
            }


# 创建全局服务实例
img2img_service = Img2ImgService()


async def main():
    """测试图生图服务"""
    try:
        # 测试参数
        test_prompt = "一个美丽的风景画，充满阳光和绿色植物"
        test_source_image = "https://hackathon.obs.cn-north-4.myhuaweicloud.com/keyframe/1/scene_0022_frame_1269_time_42300.0_sharp_1446.jpg"

        # 使用图生图服务
        result = await img2img_service.process_image(
            prompt=test_prompt,
            source_image=test_source_image,
            aspect_ratio="16:9",
            seed=42,
            style_weight=0.8,
            size="4k"
        )

        print("图生图处理结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("SUCCESS!")

    except Exception as e:
        print(f"FAILED: {str(e)}")
        exit(1)


if __name__ == '__main__':
    asyncio.run(main())
