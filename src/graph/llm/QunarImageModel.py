import asyncio
import logging
import os
import uuid
from typing import Dict, Any, Union, List, Optional

import aiohttp
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import Runnable, RunnableConfig

logger = logging.getLogger(__name__)


class QunarImageModel(Runnable):
    """去哪儿图生图模型适配器"""

    def __init__(
            self,
            **kwargs
    ):
        pass
    def _generate_trace_id(self) -> str:
        """生成唯一的trace ID"""
        return f"qal_wangwei_{uuid.uuid4().hex[:32]}"

    def _build_header(self, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """构建请求头"""
        if trace_id is None:
            trace_id = self._generate_trace_id()

        return {
            "key": os.getenv("LLM_MODEL_CONFIG_KEY_IMAGE_ENHANCEMENT", "qunar-qal-siduChishuiCloud-01-beta"),
            "apiType": os.getenv("LLM_MODEL_CONFIG_API_TYPE_IMAGE_ENHANCEMENT", "BYTEDANCE"),
            "appCode": os.getenv("LLM_MODEL_CONFIG_APP_CODE_IMAGE_ENHANCEMENT", "qal_wangwei"),
            "project": os.getenv("LLM_MODEL_CONFIG_PROJECT_IMAGE_ENHANCEMENT", "ai_travel"),
            "traceID": trace_id,
            "password": os.getenv("LLM_MODEL_CONFIG_PASSWORD_IMAGE_ENHANCEMENT", "masaiD6i"),
            "apiVersion": os.getenv("LLM_MODEL_CONFIG_API_VERSION_IMAGE_ENHANCEMENT", "v1"),
            "userIdentityInfo":  os.getenv("LLM_MODEL_CONFIG_USER_IDENTITY_IMAGE_ENHANCEMENT", "yishou.liu"),
            "externalUserIdentityInfo": ""
        }

    def _to_prompt_and_image(self, messages: Union[str, List[BaseMessage]]) -> tuple[str, Union[List[str], str]]:
        prompt_text = ""
        image_urls = []

        for msg in messages:
            # --- 1. 提取 Prompt (通常在 SystemMessage 中) ---
            if isinstance(msg, SystemMessage):
                prompt_text += msg.content

            # --- 2. 提取 Images (通常在 HumanMessage 中) ---
            elif isinstance(msg, HumanMessage):
                # 处理多模态内容 (List[dict])
                if isinstance(msg.content, list):
                    for item in msg.content:
                        # 提取图片
                        if isinstance(item, dict) and item.get("type") == "image_url":
                            # 兼容处理 {"url": "..."} 结构
                            url_obj = item.get("image_url")
                            if isinstance(url_obj, dict):
                                image_urls.append(url_obj.get("url"))
                            elif isinstance(url_obj, str):
                                image_urls.append(url_obj)

                        # 如果 HumanMessage 里混有文字，拼接到 prompt 后 (视需求而定)
                        elif isinstance(item, dict) and item.get("type") == "text":
                            # 如果需要保留 Human 的文字指令，取消下面注释
                            # prompt_text += "\n" + item.get("text", "")
                            pass

                # 处理纯文本 HumanMessage (防止报错)
                elif isinstance(msg.content, str):
                    prompt_text += "\n" + msg.content
                    pass

        # --- 3. 根据图片数量处理返回类型 ---
        # 没有图片 -> 返回空列表
        if not image_urls:
            final_images = []
        # 只有一张图片 -> 返回 str
        elif len(image_urls) == 1:
            final_images = image_urls[0]
        # 多张图片 -> 返回 List[str]
        else:
            final_images = image_urls

        return prompt_text, final_images

    async def submit_task(
            self,
            prompt: str,
            source_image: str
    ) -> tuple[str, str]:
        """
        提交图生图任务
        
        Args:
            prompt: 提示词
            source_image: 源图片URL
            aspect_ratio: 宽高比
            seed: 随机种子
            style_weight: 风格权重
            size: 图片尺寸
            model: 模型名称
            
        Returns:
            tuple: (task_id, trace_id)
        """
        trace_id = self._generate_trace_id()
        # 使用默认值（如果参数为None）
        aspect_ratio = os.getenv("LLM_MODEL_CONFIG_ASPECT_RATIO_IMAGE_ENHANCEMENT", "16:9")
        seed = int(os.getenv("LLM_MODEL_CONFIG_ASPECT_SEED_IMAGE_ENHANCEMENT", "42"))
        style_weight = float(os.getenv("LLM_MODEL_CONFIG_STYLE_WEIGHT_IMAGE_ENHANCEMENT", "0.8"))
        size = os.getenv("LLM_MODEL_CONFIG_SIZE_IMAGE_ENHANCEMENT", "4k")
        model = os.getenv("LLM_MODEL_CONFIG_MODEL_IMAGE_ENHANCEMENT", "doubao-seedream-4-0-250828")
        submit_url = os.getenv("LLM_MODEL_SUBMIT_URL_IMAGE_ENHANCEMENT", "http://llm.video.api.corp.qunar.com/Image/img2img/addtask")
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
                    submit_url,
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
        query_url = os.getenv("LLM_MODEL_CONFIG_QUERY_URL_IMAGE_ENHANCEMENT", "http://llm.video.api.corp.qunar.com/Image/taskstatus")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    query_url,
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

    def invoke(self, input: Union[str, List[BaseMessage]], config: Optional[RunnableConfig] = None,
               **kwargs) -> AIMessage:
        """同步调用（不推荐用于图像生成）"""
        return AIMessage(content="Error: 请使用 ainvoke 进行异步调用")

    async def ainvoke(
            self,
            input: Union[str, List[BaseMessage]],
            config: Optional[RunnableConfig] = None,
            **kwargs
    ) -> AIMessage:
        """
        异步调用 - 提交任务并轮询结果
        
        Args:
            input: 输入格式为 "prompt|source_image_url"
            config: 运行时配置
            **kwargs: 可覆盖的参数（aspect_ratio, seed, style_weight, size, model, max_wait_time）
            
        Returns:
            AIMessage: 包含结果的消息
        """
        try:
            # 解析输入
            prompt, source_image = self._to_prompt_and_image(input)
            max_wait_time = int(os.getenv("LLM_MODEL_CONFIG_MAX_WAIT_TIME_IMAGE_ENHANCEMENT", "120"))
            # 提交任务
            task_id, trace_id = await self.submit_task(
                prompt=prompt,
                source_image=source_image
            )

            # 轮询查询结果
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < max_wait_time:
                query_response = await self.query_task(task_id, trace_id)
                # 记录本次查询的消费（若不存在则按0处理）
                qinfo = query_response.get("QInfo", {})
                status = query_response.get("Payload", {}).get("Status", "")

                if status == "SUCCESS":  # 任务完成
                    transformed_data = self.transform_img2img_response(query_response)
                    media_url = transformed_data.get("media_url", "")
                    from src.service.obs_service import obs_service

                    oss_url = await obs_service.upload_from_url(media_url)
                    result_url = oss_url or media_url
                    if not oss_url:
                        logger.error(f'Img2img OSS upload failed, falling back to media_url: {media_url}')
                    # 同时返回每次调用（查询）的消费列表
                    transformed_data["consume"] = qinfo.get("Consume", 0)
                    logger.info(f'Img2img processing completed for task: {task_id}')
                    # 返回 media_url 作为 AIMessage 的内容
                    return AIMessage(content=result_url)
                elif status == "FAILED":  # 任务失败
                    logger.error(f'Img2img task failed: {task_id}')
                    raise Exception(f'Img2img task failed: {task_id}')
                elif status in ["COMMIT", "PROCESSING"]:  # 任务进行中
                    logger.info(f'Task {task_id} status: {status}, waiting...')
                    await asyncio.sleep(2)  # 等待2秒后再次查询
                else:
                    logger.warning(f'Unknown task status: {status}')
                    await asyncio.sleep(2)

            # 超时
            logger.error(f'Img2img task timeout after {max_wait_time} seconds')
            raise Exception(f'Img2img task timeout after {max_wait_time} seconds')

        except Exception as e:
            logger.error(f'Img2img processing error: {str(e)}')
            return AIMessage(content=f"Error: {str(e)}")
