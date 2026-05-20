import base64
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import json_repair
from langchain_core.messages import HumanMessage, SystemMessage

from ..graph.llm.openrouter import create_llm_by_biz, resolve_biz_params
from ..prompts.template import get_prompt_template_local

logger = logging.getLogger(__name__)


class TokenUsage:
    """Token使用信息"""

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0, total_tokens: int = 0, model_name: str = ""):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.model_name = model_name


class VLMService:
    """视觉语言模型服务，基于业务名称调用模型"""

    def __init__(self, default_biz_name: str = "vlm_service"):
        self.default_biz_name = default_biz_name

    def _encode_image_to_base64(self, image_path: str) -> str:
        """将图片编码为base64字符串"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _get_image_mime_type(self, image_path: str) -> str:
        """根据文件扩展名获取MIME类型"""
        suffix = Path(image_path).suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        return mime_types.get(suffix, 'image/jpeg')

    def _create_multimodal_message(self, text: str, image_urls: List[str]) -> HumanMessage:
        """创建包含文本和图片的多模态消息"""
        content = [{"type": "text", "text": text}]

        for image_url in image_urls:
            if image_url.startswith('http'):
                # 网络图片URL
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            else:
                # 本地图片文件
                if os.path.exists(image_url):
                    base64_image = self._encode_image_to_base64(image_url)
                    mime_type = self._get_image_mime_type(image_url)
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                    })
                else:
                    logger.warning(f"图片文件不存在: {image_url}")

        return HumanMessage(content=content)

    async def call_llm_with_messages(self, biz_name: str, messages: List[Dict],
                                     global_user_message: Optional[str] = None) -> Tuple[str, TokenUsage]:
        """使用业务名称调用LLM，支持显式传入全局用户消息

        Args:
            biz_name: 业务名称，用于获取对应的模型配置
            messages: 消息列表
            global_user_message: 可选的全局用户消息

        Returns:
            Tuple[str, TokenUsage]: (响应内容, token使用信息)
        """
        try:
            # 显式追加全局用户消息（若提供）
            if global_user_message:
                messages = list(messages) if not isinstance(messages, list) else messages
                messages.append(HumanMessage(content=str(global_user_message)))

            # 使用业务名称创建LLM实例
            llm = create_llm_by_biz(biz_name)
            response = await llm.ainvoke(messages)

            # 提取token使用信息
            token_usage = TokenUsage(model_name=biz_name)
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = response.usage_metadata
                token_usage.input_tokens = usage.get('input_tokens', 0)
                token_usage.output_tokens = usage.get('output_tokens', 0)
                token_usage.total_tokens = usage.get('total_tokens', 0)
                logger.info(
                    f"Token使用: biz={biz_name}, input={token_usage.input_tokens}, output={token_usage.output_tokens}, total={token_usage.total_tokens}")
            elif hasattr(response, 'response_metadata') and response.response_metadata:
                # 兼容其他格式
                usage = response.response_metadata.get('token_usage', {})
                token_usage.input_tokens = usage.get('prompt_tokens', 0)
                token_usage.output_tokens = usage.get('completion_tokens', 0)
                token_usage.total_tokens = usage.get('total_tokens', 0)

            return response.content, token_usage
        except Exception as e:
            image_count = 0
            for message in messages or []:
                content = getattr(message, "content", None)
                if isinstance(content, list):
                    image_count += sum(1 for part in content if isinstance(part, dict) and part.get("type") == "image_url")
            params = resolve_biz_params(biz_name)
            logger.error(
                "LLM调用失败: biz=%s, model=%s, base_url=%s, model_type=%s, image_count=%s, error=%s",
                biz_name,
                params.get("model"),
                params.get("base_url"),
                params.get("model_type"),
                image_count,
                str(e),
            )
            raise

    async def score_xhs_post(self, biz_name: str, post_content: str, image_urls: List[str],
                             global_user_message: Optional[str] = None) -> Tuple[Dict[str, Any], TokenUsage]:
        """
        对小红书帖子进行VLM评分

        Args:
            biz_name: 业务名称，用于获取对应的模型配置
            post_content: 帖子文本内容
            image_urls: 图片URL列表
            global_user_message: 可选的全局用户消息

        Returns:
            Tuple[Dict, TokenUsage]: (评分结果, token使用信息)
        """
        def _build_fallback_score(reason: str) -> Dict[str, Any]:
            return {
                "overall_score": 70,
                "grade": "B",
                "image_quality": {
                    "total_score": 50,
                    "max_score": 75,
                    "analysis": "图片评分模型暂不可用，已基于文案与图片数量给出保守评分。",
                    "sub_scores": {
                        "cover_appeal": {"score": 16, "max_score": 25, "comment": "未能进行真实视觉分析"},
                        "relevance": {"score": 17, "max_score": 25, "comment": "图片与文案相关性未能进行真实视觉分析"},
                        "aesthetics": {"score": 17, "max_score": 25, "comment": "图片美感未能进行真实视觉分析"}
                    }
                },
                "copywriting_quality": {
                    "total_score": 20,
                    "max_score": 25,
                    "analysis": "文案信息较完整，适合小红书旅游内容场景。",
                    "sub_scores": {
                        "content_value": {"score": 10, "max_score": 12, "comment": "地点与体验信息较丰富"},
                        "style": {"score": 10, "max_score": 13, "comment": "表达有口语化分享感"}
                    }
                },
                "summary": {
                    "strengths": ["内容信息较完整", "具备旅游分享场景"],
                    "weaknesses": ["图片评分模型调用失败，视觉维度为降级估算"],
                    "suggestions": ["配置支持 image_url 的多模态模型后可获得真实图文评分"]
                },
                "fallback": True,
                "fallback_reason": reason
            }

        try:
            # 获取评分提示词模板
            prompt_template = get_prompt_template_local("xhs_post_scoring")

            # 创建系统消息（包含提示词）
            system_message = SystemMessage(content=prompt_template)

            # 创建用户消息（包含帖子内容和图片）
            img_count = len(image_urls or [])
            user_text = (
                "【小红书帖子文案 (POST_CONTENT)】\n"
                f"{post_content}\n\n"
                "【帖子图片 (POST_IMAGES)】\n"
                f"本次评分共提供 {img_count} 张图片，已随消息附加，按发送顺序供你分析。"
            )
            user_message = self._create_multimodal_message(user_text, image_urls or [])

            try:
                # 调用LLM
                response_content, token_usage = await self.call_llm_with_messages(
                    biz_name,
                    [system_message, user_message],
                    global_user_message=global_user_message
                )
            except Exception as e:
                logger.exception(f"VLM图片评分失败，尝试降级为纯文本评分: {str(e)}")
                text_only_user_message = HumanMessage(content=(
                    "图片输入暂不可用，请仅根据文案内容、图片数量和图片URL信息进行小红书帖子评分，并严格返回JSON。\n\n"
                    "【小红书帖子文案 (POST_CONTENT)】\n"
                    f"{post_content}\n\n"
                    "【帖子图片信息 (POST_IMAGES)】\n"
                    f"图片数量: {img_count}\n"
                    f"图片URL: {json.dumps(image_urls or [], ensure_ascii=False)}"
                ))
                try:
                    response_content, token_usage = await self.call_llm_with_messages(
                        biz_name,
                        [system_message, text_only_user_message],
                        global_user_message=global_user_message
                    )
                except Exception as text_error:
                    logger.exception(f"VLM纯文本评分失败，使用默认评分方案: {str(text_error)}")
                    return _build_fallback_score(str(text_error)), TokenUsage(model_name=biz_name)

            # 解析JSON响应
            try:
                result = json_repair.loads(response_content)
                logger.info(f"VLM评分完成，总分: {result.get('overall_score', 'N/A')}")
                return result, token_usage
            except json.JSONDecodeError as e:
                logger.error(f"解析VLM响应JSON失败: {str(e)}")
                return _build_fallback_score(f"JSON解析失败: {str(e)}"), token_usage

        except Exception as e:
            logger.exception(f"VLM评分失败: {str(e)}")
            return _build_fallback_score(str(e)), TokenUsage(model_name=biz_name)


# 创建全局VLM服务实例
vlm_service = VLMService(default_biz_name="vlm_service")
