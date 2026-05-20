import asyncio
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)


class ASRService:
    """ASR语音识别服务类"""

    def __init__(self, appid="8673773070", token="9YJA-ogXkggXN43F0p6UnXUvx7FwtPh7"):
        self.appid = appid
        self.token = token
        self.submit_url = "https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/submit"
        self.query_url = "https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/query"

    async def submit_task(self, audio_url):
        """提交ASR任务"""
        task_id = audio_url
        headers = {
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.token,
            "X-Api-Resource-Id": "volc.bigasr.auc",
            "X-Api-Request-Id": audio_url,
            "X-Api-Sequence": "-1"
        }

        request = {
            "user": {
                "uid": "fake_uid"
            },
            "audio": {
                "url": audio_url,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_channel_split": True,
                "enable_ddc": True,
                "enable_speaker_info": True,
                "enable_punc": True,
                "enable_itn": True,
                "enable_emotion_detection": True,
                "corpus": {
                    "correct_table_name": "",
                    "context": ""
                }
            }
        }

        logger.info(f'Submit task id: {task_id}')

        async with aiohttp.ClientSession() as session:
            async with session.post(self.submit_url, data=json.dumps(request), headers=headers) as response:
                response_headers = response.headers

                if 'X-Api-Status-Code' in response_headers and response_headers["X-Api-Status-Code"] == "20000000":
                    logger.info(f'Submit task success: {response_headers["X-Api-Message"]}')
                    x_tt_logid = response_headers.get("X-Tt-Logid", "")
                    return task_id, x_tt_logid
                else:
                    logger.error(f'Submit task failed: {response_headers}')
                    raise Exception(f'Submit task failed: {response_headers}')

    async def query_task(self, task_id, x_tt_logid):
        """查询ASR任务状态"""
        headers = {
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.token,
            "X-Api-Resource-Id": "volc.bigasr.auc",
            "X-Api-Request-Id": task_id,
            "X-Tt-Logid": x_tt_logid
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.query_url, data=json.dumps({}), headers=headers) as response:
                response_headers = response.headers

                if 'X-Api-Status-Code' not in response_headers:
                    logger.error(f'Query task failed: {response_headers}')
                    raise Exception(f'Query task failed: {response_headers}')

                # 返回响应对象的必要信息
                response_data = await response.json()
                return {
                    'headers': dict(response_headers),
                    'json': response_data
                }

    def transform_asr_response(self, response_data):
        """将ASR响应数据转换为简洁的数组格式"""
        result = []

        if 'result' in response_data and 'utterances' in response_data['result']:
            utterances = response_data['result']['utterances']

            for utterance in utterances:
                item = {
                    "start_time": utterance.get("start_time", 0),
                    "end_time": utterance.get("end_time", 0),
                    "text": utterance.get("text", "")
                }

                # 添加情感相关信息（如果存在）
                if 'additions' in utterance:
                    additions = utterance['additions']
                    item.update({
                        "emotion": additions.get("emotion", ""),
                        "emotion_degree": additions.get("emotion_degree", ""),
                        "emotion_degree_score": additions.get("emotion_degree_score", ""),
                        "emotion_score": additions.get("emotion_score", ""),
                        "speaker": additions.get("speaker", "")
                    })

                result.append(item)

        return result

    async def process_audio(self, audio_url, max_wait_time=300):
        """
        处理音频文件，返回转换后的简洁格式数据
        
        Args:
            audio_url: 音频文件URL
            max_wait_time: 最大等待时间（秒）
            
        Returns:
            list: 转换后的简洁格式数据
        """
        try:
            # 提交任务
            task_id, x_tt_logid = await self.submit_task(audio_url)

            # 轮询查询结果
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < max_wait_time:
                query_response = await self.query_task(task_id, x_tt_logid)
                code = query_response['headers'].get('X-Api-Status-Code', "")

                if code == '20000000':  # 任务完成
                    original_data = query_response['json']
                    transformed_data = self.transform_asr_response(original_data)
                    logger.info(f'ASR processing completed for task: {task_id}')
                    return transformed_data
                elif code != '20000001' and code != '20000002':  # 任务失败
                    logger.error(f'ASR task failed with code: {code}')
                    raise Exception(f'ASR task failed with code: {code}')

                await asyncio.sleep(1)

            # 超时
            logger.error(f'ASR task timeout after {max_wait_time} seconds')
            raise Exception(f'ASR task timeout after {max_wait_time} seconds')

        except Exception as e:
            logger.error(f'ASR processing error: {str(e)}')
            raise


asr_service = ASRService()


async def main():
    """测试ASR服务"""
    try:
        # 使用新的ASRService类
        result = await asr_service.process_audio(
            "https://hackathon.obs.cn-north-4.myhuaweicloud.com/uploads/20251026_205839_test_audio.mp3")

        print("转换后的简洁格式:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("SUCCESS!")

    except Exception as e:
        print(f"FAILED: {str(e)}")
        exit(1)


if __name__ == '__main__':
    asyncio.run(main())
