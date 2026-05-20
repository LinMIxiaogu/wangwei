"""
图像增强服务
使用 OpenRouter 调用图像增强模型，保存到本地后上传到 OBS
"""
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from src.graph.llm.openrouter import create_llm_by_biz
from src.prompts.template import get_prompt_template_local

logger = logging.getLogger(__name__)


class ImageEnhancementService:
    """图像增强服务类，使用 OpenRouter 调用图像增强"""

    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix='image_enhancement_'))
        self.temp_dir.mkdir(exist_ok=True)

    async def enhance_image_and_upload(self, image_url: str, custom_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        图像增强主流程：OpenRouter增强->保存->上传OBS
        
        Args:
            image_url: 原始图片URL（外网）
            aspect_ratio: 宽高比（暂时保留，兼容现有接口）
            custom_prompt: 自定义提示词，如果不提供则使用默认模板
            
        Returns:
            dict: 处理结果
        """
        try:
            logger.info(f"开始图像增强处理: {image_url}")

            # 1. 获取增强提示词
            if custom_prompt:
                prompt_template = custom_prompt
            else:
                prompt_template = get_prompt_template_local("image_enhancement")
            # 创建LLM实例
            llm = create_llm_by_biz("image_enhancement")

            # 构建消息，直接使用外网图片URL
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=prompt_template),
                HumanMessage(content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    }
                ])
            ]
            # 调用LLM
            response = await llm.ainvoke(messages)
            if not response or not response.content:
                return {
                    "success": False,
                    "message": "图像增强失败",
                    "enhancement_result": {}
                }
            oss_url = response.content
            if isinstance(oss_url, str) and oss_url.startswith("Error:"):
                return {
                    "success": False,
                    "message": oss_url,
                    "enhancement_result": {}
                }
            logger.info(f"图像增强成功: {image_url} -> {response}")
            return {
                "success": True,
                "final_url": oss_url,
                "source_url": image_url,
                "oss_url": oss_url,
                "enhancement_result": {
                    "status": "SUCCESS",
                    "media_url": oss_url
                }
            }
        except Exception as e:
            logger.exception(f"图像增强处理异常: {image_url}")
            return {
                "success": False,
                "message": f"image_enhancement_error: {str(e)}",
                "enhancement_result": {}
            }

    def cleanup(self):
        """清理临时目录"""
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass

# 创建全局服务实例
image_enhancement_service = ImageEnhancementService()
