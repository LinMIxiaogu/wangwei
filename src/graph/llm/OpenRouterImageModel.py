import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Union, List, Optional

from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenRouterImageModel(Runnable):
    """简化的 OpenRouter 图像模型适配器"""

    def __init__(self, model: str, api_key: str, base_url: str, **kwargs):
        self.temp_dir = Path(tempfile.mkdtemp(prefix='image_enhancement_'))
        self.temp_dir.mkdir(exist_ok=True)
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        # 简化参数处理
        self.temperature = float(kwargs.get('temperature', 0.3))
        self.max_tokens = int(kwargs.get('max_tokens', 4096))

    def _to_openai_messages(self, input: Union[str, List[BaseMessage]]) -> List[Dict[str, Any]]:
        """简化的消息转换"""
        if isinstance(input, str):
            return [{"role": "user", "content": input}]

        messages = []
        for msg in input:
            if hasattr(msg, 'content'):
                role = "system" if "SystemMessage" in str(type(msg)) else "user"
                messages.append({"role": role, "content": msg.content})
        return messages

    def invoke(self, input: Union[str, List[BaseMessage]], config: Optional[RunnableConfig] = None,
               **kwargs) -> AIMessage:
        """同步调用（不推荐用于图像生成）"""
        return AIMessage(content="Error: 请使用 ainvoke 进行异步调用")

    async def ainvoke(self, input: Union[str, List[BaseMessage]], config: Optional[RunnableConfig] = None,
                      **kwargs) -> AIMessage | None:
        """异步调用 - 简化版本"""
        try:
            messages = self._to_openai_messages(input)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )

            # 直接从响应中提取图片数据，减少层级
            # 方式1: 尝试从 message.content 获取
            if response.choices and response.choices[0].message.content:
                return AIMessage(content=response.choices[0].message.content)

            # 方式2: 尝试从 model_extra 获取（如果存在）
            if hasattr(response.choices[0].message, 'model_extra') and response.choices[0].message.model_extra:
                extra = response.choices[0].message.model_extra
                if 'images' in extra and extra['images']:
                    image_url = extra['images'][0].get('image_url', {}).get('url')
                    if image_url:
                        # 3. 保存增强后的图片到本地
                        output_filename = f"enhanced_{os.urandom(8).hex()}.jpg"
                        local_output_path = str(self.temp_dir / output_filename)
                        save_success = await self.save_base64_to_local(image_url, local_output_path)
                        if not save_success:
                            return None

                        # 4. 上传到OBS
                        from src.service.obs_service import obs_service

                        oss_url = await obs_service.upload_file(local_output_path)
                        if not oss_url:
                           return None

                        # 5. 清理临时文件
                        try:
                            os.unlink(local_output_path)
                        except:
                            pass  # 忽略清理错误
                        return AIMessage(content=oss_url)
            return None
        except Exception as e:
            logger.error(f"图像增强失败: {e}")
            return None

    async def save_base64_to_local(self, base64_data: str, output_path: str) -> bool:
        """
        将base64数据保存为本地文件

        Args:
            base64_data: base64编码的图片数据
            output_path: 输出文件路径

        Returns:
            bool: 保存是否成功
        """
        try:
            # 清理base64数据（移除可能的前缀）
            if ',' in base64_data:
                base64_data = base64_data.split(',', 1)[1]

            # 解码图片数据
            image_data = base64.b64decode(base64_data)

            # 使用内置的异步文件写入
            def _write_file():
                with open(output_path, 'wb') as f:
                    f.write(image_data)

            # 在线程池中执行文件写入操作 (兼容 Python 3.7+)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _write_file)

            logger.info(f"图片保存成功: {output_path}")
            return True

        except Exception as e:
            logger.error(f"保存图片失败: {output_path}, error: {str(e)}")
            return False
