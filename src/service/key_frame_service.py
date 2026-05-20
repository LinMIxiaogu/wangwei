#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
key_frame_service.py

一个可重用的底层服务，用于从视频提取关键帧。

功能:
1. 使用 MiniBatchKMeans 从视频采样帧中聚类提取关键帧
2. 支持进度事件发送
3. 上传提取后的关键帧
"""

import asyncio
import logging
import os
import time
from typing import List, Optional, Dict, Tuple, Callable

import cv2
import numpy as np

from src.graph.state.types import State
from ..graph.event.manager import event_manager

logger = logging.getLogger(__name__)

try:
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.metrics import pairwise_distances_argmin_min
except ImportError:
    print("错误: 缺少 'scikit-learn' 库。请运行: pip install scikit-learn")
    exit()

# =============================================================================
# 新方法：KMeans 关键帧提取 (核心逻辑)
# =============================================================================

KMEANS_CONFIG = {
    # 每个视频提取多少个关键帧
    'num_keyframes': 20,

    # 每秒采样几帧 (调高会更慢但更准, 调低更快但可能错过镜头)
    'sampling_fps': 2,

    # 直方图维度 (H, S)
    # (32, 32) = 1024 维，非常快
    # (50, 60) = 3000 维，中等
    'hist_bins': (50, 60)
}


# =============================================================================
# 核心功能函数
# =============================================================================

def extract_features(frame, bins: Tuple[int, int]) -> np.ndarray:
    """
    从视频帧中提取特征（HSV 颜色直方图）
    bins: (H_bins, S_bins) - 直方图的维度
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 使用传入的 bins 参数
    hist = cv2.calcHist([hsv], [0, 1], None, bins, [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()


def run_kmeans_extraction(
        video_path: str,
        output_dir: str,
        num_keyframes: int,
        sampling_fps: int,
        hist_bins: Tuple[int, int],
        progress_callback: Optional[Callable] = None  # <-- 接收回调
) -> List[str]:
    """
    (同步) K-Means 关键帧提取的核心逻辑。
    这个函数会阻塞，直到所有帧被提取和保存。
    它被设计为在 asyncio.to_thread 中运行。

    Args:
        ...
        progress_callback (Optional[Callable]): 用于报告进度的线程安全回调。

    返回:
        List[str]: 保存的本地文件路径列表
    """

    start_time = time.time()

    # --- 1. 设置输出目录 ---
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"已创建目录: {output_dir}")
    else:
        logger.info(f"输出目录已存在: {output_dir}")

    logger.info(f"开始处理视频: {video_path}")
    logger.info(f"提取 {num_keyframes} 帧, 每秒采样 {sampling_fps} 帧, 直方图维度 {hist_bins}")

    # --- 2. 采样并提取特征 ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"错误: 无法打开视频文件 {video_path}")
        return []

    original_fps = cap.get(cv2.CAP_PROP_FPS)
    if original_fps <= 0:
        logger.warning("警告: 无法获取视频 FPS，将使用默认值 30。")
        original_fps = 30

    # --- 新增：获取总帧数用于计算进度 ---
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        logger.warning("警告: 无法获取总帧数, 采样进度可能不准确。")

    sampling_rate = max(1, int(original_fps / sampling_fps))
    logger.info(f"视频原始 FPS: {original_fps:.2f}，采样间隔: 每 {sampling_rate} 帧提取 1 帧。")

    features = []
    frame_indices = []
    frame_count = 0

    # 报告进度的频率
    report_interval_frames = max(100, int(original_fps * 2))  # 大约每 100 帧或每 2 秒的采样量报告一次

    while True:
        success, frame = cap.read()
        if not success:
            break

        # --- 2.1. 调用回调：特征提取 (0% -> 50%) ---
        if total_frames > 0 and frame_count % report_interval_frames == 0 and progress_callback:
            percent = (frame_count / total_frames) * 50
            progress_callback(percent, "⚙️ 正在采样和分析视频帧...")

        if frame_count % sampling_rate == 0:
            feature = extract_features(frame, bins=hist_bins)
            features.append(feature)
            frame_indices.append(frame_count)  # 存储原始帧编号

        frame_count += 1

    cap.release()

    if not features:
        logger.error("错误: 未能从视频中提取任何特征。")
        return []

    if num_keyframes > len(features):
        logger.warning(f"请求的关键帧数 ({num_keyframes}) 多于采样帧数 ({len(features)})。")
        num_keyframes = len(features)

    if num_keyframes == 0:
        logger.error("错误: 无法提取 0 帧。")
        return []

    features_np = np.array(features)
    logger.info(f"特征提取完成。总共采样 {len(features_np)} 帧。 (耗时: {time.time() - start_time:.2f} 秒)")

    # --- 3. MiniBatchKMeans 聚类 ---
    logger.info("开始 MiniBatchKMeans 聚类...")

    # --- 3.1. 调用回调：聚类 (50% -> 70%) ---
    if progress_callback:
        progress_callback(50, "🚀 开始 K-Means 聚类...")

    cluster_start_time = time.time()
    kmeans = MiniBatchKMeans(
        n_clusters=num_keyframes,
        random_state=42,
        n_init=10,
        batch_size=256
    )
    kmeans.fit(features_np)
    logger.info(f"聚类完成。(耗时: {time.time() - cluster_start_time:.2f} 秒)")

    if progress_callback:
        progress_callback(70, "✅ 聚类完成，正在保存关键帧...")

    # --- 4. 找到最接近簇中心的帧 ---
    closest_indices, _ = pairwise_distances_argmin_min(kmeans.cluster_centers_, features_np)
    keyframe_indices_in_video = sorted(list(set([frame_indices[i] for i in closest_indices])))
    logger.info(f"找到的关键帧索引: {keyframe_indices_in_video}")

    # --- 5. 保存关键帧图像 ---
    logger.info("开始保存关键帧...")
    save_start_time = time.time()
    cap = cv2.VideoCapture(video_path)  # 重新打开视频

    saved_count = 0
    frame_idx_to_save = 0
    current_frame = 0
    saved_file_paths = []

    if not keyframe_indices_in_video:
        cap.release()
        return []

    target_frame = keyframe_indices_in_video[frame_idx_to_save]
    total_keyframes_to_save = len(keyframe_indices_in_video)

    while True:
        success, frame = cap.read()
        if not success:
            break

        if current_frame == target_frame:
            timestamp_ms = (current_frame / original_fps) * 1000
            # 1. 定义缺失的变量
            best_sharpness = 0.0

            # 2. 创建新格式的文件名
            filename = os.path.join(
                output_dir,
                (f"scene_{saved_count + 1:04d}_frame_{current_frame}_"
                 f"time_{timestamp_ms:.1f}_sharp_{best_sharpness:.0f}.jpg")
            )

            cv2.imwrite(filename, frame)
            saved_file_paths.append(filename)

            saved_count += 1
            frame_idx_to_save += 1

            # --- 5.1. 调用回调：保存 (70% -> 80%) ---
            if progress_callback and total_keyframes_to_save > 0:
                percent = 70 + (saved_count / total_keyframes_to_save) * 10
                progress_callback(percent, "💾 正在保存关键帧...")

            if frame_idx_to_save >= len(keyframe_indices_in_video):
                break

            target_frame = keyframe_indices_in_video[frame_idx_to_save]

        current_frame += 1

    cap.release()

    # --- 6. 调用回调：本地处理完成 (80%) ---
    if progress_callback:
        progress_callback(80, "🎉 本地处理完成，准备上传...")

    logger.info(f"关键帧保存完毕。(耗时: {time.time() - save_start_time:.2f} 秒)")
    logger.info(f"--- 视频 {video_path} 处理完毕，总耗时: {time.time() - start_time:.2f} 秒 ---")

    return saved_file_paths


# =============================================================================
# 主要接口函数 (异步)
# =============================================================================

async def find_best_keyframe_in_scenes_k(
        video_path: str,
        output_dir: str,
        state: 'State' = None,
        obs_service: 'ObsService' = None,  # 接收 ObsService 实例
        message_id: str = None
) -> List[Dict[str, str]]:
    """
    (重构版) 从视频中提取关键帧，使用 KMeans 聚类方法。
    此函数保留了原始的异步接口，用于上传和状态报告。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        state: 状态对象，用于发送进度事件
        obs_service: ObsService实例，用于上传文件
        message_id: 消息ID

    Returns:
        List[Dict[str, str]]: 保存的关键帧信息列表，每个元素包含 local_path 和 oss_url
    """
    logger.info("🚀 开始 KMeans 关键帧提取任务")

    # 验证文件存在
    if not os.path.exists(video_path):
        logger.error(f"❌ 视频文件不存在: {video_path}")
        return []

    logger.info(f"🖼️ 视频路径: {video_path}")
    logger.info(f"💾 输出目录: {output_dir}")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # --- 异步执行 KMeans 提取 ---
    logger.info(f"⚙️ 正在启动 KMeans 分析线程...")

    # --- 新增：创建线程安全的回调 ---
    progress_callback = None
    if state and event_manager:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("警告: 无法获取正在运行的事件循环。进度回调将不可用。")
            loop = None

        if loop:
            last_reported_percent = -1

            def _create_callback():
                nonlocal last_reported_percent

                def _thread_safe_callback(percent: float, message: str):
                    nonlocal last_reported_percent
                    int_percent = int(percent)

                    # 限制事件发送频率，只在百分比变化时发送
                    if int_percent <= last_reported_percent:
                        return

                    last_reported_percent = int_percent

                    event_data = {
                        "message": f"⬆️ 关键帧提取处理进度 - {int_percent}%",
                        "progress": int_percent,
                        "current": int_percent,  # 保持简单，用百分比作为进度
                        "total": 100,
                        "message_id": message_id
                    }

                    # 关键：从工作线程安全地调度异步任务到主事件循环
                    asyncio.run_coroutine_threadsafe(
                        event_manager.send_event(
                            state=state,
                            event="key_frame_detect_node_stream",
                            data=event_data
                        ),
                        loop
                    )

                return _thread_safe_callback

            progress_callback = _create_callback()

    try:
        # 在线程池中运行阻塞函数，并传入回调
        local_paths = await asyncio.to_thread(
            run_kmeans_extraction,
            video_path=video_path,
            output_dir=output_dir,
            num_keyframes=KMEANS_CONFIG['num_keyframes'],
            sampling_fps=KMEANS_CONFIG['sampling_fps'],
            hist_bins=KMEANS_CONFIG['hist_bins'],
            progress_callback=progress_callback  # <-- 传递回调
        )
    except Exception as e:
        logger.error(f"❌ KMeans 提取过程中发生严重错误: {e}")
        if state and event_manager:
            try:
                await event_manager.send_event(
                    state=state,
                    event="key_frame_detect_node_stream",
                    data={"message": f"❌ 提取失败: {e}", "progress": 100, "message_id": message_id}
                )
            except Exception as e_inner:
                logger.warning(f"⚠️ 发送错误事件失败: {e_inner}")
        return []

    if not local_paths:
        logger.warning(f"⚠️ KMeans 未返回任何关键帧路径。")
        return []

    logger.info(f"✅ KMeans 分析完成，找到 {len(local_paths)} 个本地关键帧。")
    logger.info(f"⬆️ 开始上传到 OBS...")

    # --- 异步上传和报告 ---
    saved_keyframe_info = []
    total_files = len(local_paths)

    # --- 修改：上传进度现在从 80% 开始到 100% ---
    upload_progress_start = 80

    for i, local_path in enumerate(local_paths):
        oss_url = None

        # 1. 上传文件 (如果提供了 obs_service)
        if obs_service:
            try:
                image_base_name = os.path.basename(local_path)
                # 假设 output_dir 是 '.../data/k_02/1'
                video_id_folder = os.path.basename(output_dir)
                oss_path = f"keyframe/{video_id_folder}/{image_base_name}"

                oss_url = await obs_service.upload_file_for_path(local_path, oss_path)
                logger.info(f"⬆️ ({i + 1}/{total_files}) 已上传到OSS: {oss_url}")

                saved_keyframe_info.append({
                    "local_path": local_path,
                    "oss_url": oss_url
                })
            except Exception as e:
                logger.error(f"❌ ({i + 1}/{total_files}) 上传到OSS失败: {e}")
        else:
            # 如果没有 obs_service，只保存本地路径
            logger.info(f"ℹ️ ({i + 1}/{total_files}) 未提供 OBS 服务，跳过上传。")
            saved_keyframe_info.append({"local_path": local_path, "oss_url": None})

        # 2. 发送进度事件
        if state and event_manager:
            try:
                # --- 修改：重新映射进度百分比 ---
                progress_percent = upload_progress_start + int(((i + 1) / total_files) * (100 - upload_progress_start))

                event_data = {
                    "message": f"⬆️ 关键帧提取处理进度 - {progress_percent}%",
                    "progress": progress_percent,
                    "current": i + 1,
                    "total": total_files,
                    "message_id": message_id
                }
                if oss_url:
                    event_data["key_frame"] = {
                        "local_path": local_path,
                        "oss_url": oss_url
                    }

                await event_manager.send_event(
                    state=state,
                    event="key_frame_detect_node_stream",
                    data=event_data
                )
            except Exception as e:
                logger.warning(f"⚠️ 发送上传进度事件失败: {e}")

    logger.info(f"🎉 KMeans 关键帧提取与上传全部完成！")
    logger.info(f"✅ 成功处理 {len(saved_keyframe_info)} 个关键帧")

    return saved_keyframe_info
