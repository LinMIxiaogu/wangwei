import random
import os
import time
import uuid

from langgraph.types import Command

from src.config.local_dynamic_config import LOCAL_XHS_HOT_KEYWORDS, LOCAL_XHS_HOT_DOT_TITLES
from src.graph.event.manager import event_manager
from src.graph.state.types import State
from src.service import xhs_hot_leaderboard
from src.service.xhs_hot_keyword_service import get_default_xhs_hot_keyword_service


# 全局事件管理器实例（本地配置已移至 src.config.local_dynamic_config）
async def xhs_hot_content_node(state: State):
    message_id = str(uuid.uuid4())
    # 本地配置随机选取20条（不足则全量）用于流式预览
    local_key_sample = random.sample(LOCAL_XHS_HOT_KEYWORDS, k=min(20, len(LOCAL_XHS_HOT_KEYWORDS)))
    local_dot_sample = random.sample(LOCAL_XHS_HOT_DOT_TITLES, k=min(20, len(LOCAL_XHS_HOT_DOT_TITLES)))
    await event_manager.send_event(
        state=state,
        event="xhs_hot_content_node_start",
        data={
            "message": f"正在进行匹配热词、热点相关内容~",
            "message_id": message_id
        }
    )

    await event_manager.send_event(
        state=state,
        event="xhs_hot_content_node_key_stream",
        data={
            "message": f"正在扫描热词相关数据~",
            "message_id": message_id,
            "xhs_hot_key_result": local_key_sample
        }
    )
    ## 2. 获取热帖
    await event_manager.send_event(
        state=state,
        event="xhs_hot_content_node_dot_stream",
        data={
            "message": f"正在扫描热点相关数据~",
            "message_id": message_id,
            "xhs_hot_dot_result": local_dot_sample
        }
    )
    time.sleep(5)
    video_full_transcript = state.get("video_full_transcript",
                                      "分享一条江苏昆山的古镇一日游路线，一共三站，30公里路程，全程不收门票，风景非常漂亮，适合周末自驾一日游。第一站歇马桥古镇，这是一座半小时就能逛完的古镇，规模不大，但是风景非常漂亮。古镇商业氛围不重，小桥流水，环境很清幽。适合拍照打卡，拍照巨出片。第二站，千灯古镇。这座千年古镇依水而建，是非常典型的传统江南水乡。七座明清时期的古桥连接两岸，为古镇增加了浓厚的历史感。位于古镇中心，始建于梁代的秦峰塔和石板街是古镇的必打卡景点。石板街商业齐全，沿途有很多当地传统美食，适合边吃边逛。最后一站锦溪古镇，江苏少有的一眼就能感受到悠闲的古镇。古镇内环境清幽，风景非常漂亮。在这里你可以漫步在古街古桥上，品尝江南美食。也可以乘坐摇橹船去邂逅江南水乡的温柔，环境不错，非常值得一逛。走到这里，昆山古镇一日游就走完了。我是侠客行，关注我，下个视频更精彩。")
    service = get_default_xhs_hot_keyword_service()
    # 使用文本->向量->相似检索
    xhs_hot_keywords = []
    if video_full_transcript:
        search_result = service.search_by_text(
            query=video_full_transcript,
            top_k=20,
            similarity_threshold=0.8
        )
        xhs_hot_keywords = [it.get("keyword") for it in search_result if isinstance(it, dict) and it.get("keyword")]

    enable_realtime_hot = os.getenv("ENABLE_XHS_REALTIME_HOT", "false").lower() == "true"
    xhs_hot_dot_result = LOCAL_XHS_HOT_DOT_TITLES
    if enable_realtime_hot:
        realtime_hot_dot_result = await xhs_hot_leaderboard.get_xhs_hot_leaderboard()
        if realtime_hot_dot_result:
            xhs_hot_dot_result = realtime_hot_dot_result

    # 仅取前10条（不足10条则全量）
    xhs_hot_key_top10 = xhs_hot_keywords[:10]
    xhs_hot_dot_top10 = xhs_hot_dot_result[:10]

    await event_manager.send_event(
        state=state,
        event="xhs_hot_content_node_end",
        data={
            "message": f"成功匹配到热词、热点相关内容~",
            "message_id": message_id,
            "xhs_hot_key_result": xhs_hot_keywords,
            "xhs_hot_dot_result": xhs_hot_dot_result,
            "xhs_hot_key_final_result": xhs_hot_key_top10,
            "xhs_hot_dot_final_result": xhs_hot_dot_top10
        }
    )
    result_data = {
        "xhs_hot_key_result": xhs_hot_keywords,
        "xhs_hot_dot_result": xhs_hot_dot_top10,
        "xhs_hot_key_final_result": xhs_hot_key_top10,
        "xhs_hot_dot_final_result": xhs_hot_dot_top10,
    }
    # 更新state，保存选择结果
    return Command(
        update={
            "xhs_hot_content_node_result": result_data,
        },
        goto=["generate"],
    )
