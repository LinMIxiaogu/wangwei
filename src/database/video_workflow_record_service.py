"""
视频工作流记录服务层
提供事务支持和业务逻辑封装
"""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from .connection import db_manager
from .models import (
    VideoWorkflowRecord,
    VideoWorkflowRecordCreate,
    VideoWorkflowRecordUpdate,
    VideoWorkflowRecordQuery, ExtendData,
)
from .video_workflow_record_dao import video_workflow_record_dao
from .ext_utils import parse_state_from_ext

logger = logging.getLogger(__name__)


class VideoWorkflowRecordService:
    """视频工作流记录服务类"""

    def __init__(self):
        self.dao = video_workflow_record_dao

    async def initialize(self) -> None:
        """初始化服务（初始化数据库连接池）"""
        await db_manager.initialize()
        logger.info("视频工作流记录服务初始化完成")

    async def create_workflow_record(self, record_data: VideoWorkflowRecordCreate) -> Optional[
        VideoWorkflowRecord]:
        """
        创建工作流记录
        
        Args:
            record_data: 记录数据
            
        Returns:
            创建的记录对象
        """
        try:
            # 验证数据
            if not record_data.session_id or not record_data.workflow_id or not record_data.video_url:
                raise ValueError("session_id, workflow_id和video_url是必填字段")

            # 检查是否已存在相同session_id的记录
            existing_record = await self.dao.get_record_by_session_id_and_workflow_id(record_data.session_id)
            if existing_record:
                logger.warning(
                    f"会话ID {record_data.session_id} 工作流ID {record_data.workflow_id} 已存在记录，ID: {existing_record.id}")
                # 可以选择更新现有记录或返回现有记录
                return existing_record

            # 创建新记录
            record = await self.dao.create_record(record_data)
            logger.info(f"成功创建工作流记录: {record.id}")
            return record

        except Exception as e:
            logger.error(f"创建工作流记录失败: {e}")
            raise

    async def get_workflow_record(self, record_id: int) -> Optional[VideoWorkflowRecord]:
        """
        获取工作流记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            记录对象
        """
        try:
            return await self.dao.get_record_by_id(record_id)
        except Exception as e:
            logger.error(f"获取工作流记录失败: {e}")
            raise

    async def get_workflow_record_by_session_and_workflow(self, session_id: str) -> Optional[
        VideoWorkflowRecord]:
        """
        根据会话ID获取工作流记录
        
        Args:
            session_id: 会话ID
            workflow_id: 工作流ID
            
        Returns:
            记录对象
        """
        try:
            return await self.dao.get_record_by_session_id_and_workflow_id(session_id)
        except Exception as e:
            logger.error(f"根据会话ID获取工作流记录失败: {e}")
            raise

    async def query_workflow_records(self, query_params: VideoWorkflowRecordQuery) -> Tuple[
        List[VideoWorkflowRecord], int]:
        """
        查询工作流记录
        
        Args:
            query_params: 查询参数
            
        Returns:
            (记录列表, 总数量)
        """
        try:
            return await self.dao.query_records(query_params)
        except Exception as e:
            logger.error(f"查询工作流记录失败: {e}")
            raise

    async def update_workflow_record(self, record_id: int,
                                     update_data: VideoWorkflowRecordUpdate) -> Optional[
        VideoWorkflowRecord]:
        """
        更新工作流记录
        
        Args:
            record_id: 记录ID
            update_data: 更新数据
            
        Returns:
            更新后的记录对象
        """
        try:
            return await self.dao.update_record(record_id, update_data)
        except Exception as e:
            logger.error(f"更新工作流记录失败: {e}")
            raise

    async def delete_workflow_record(self, record_id: int) -> bool:
        """
        删除工作流记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            删除成功返回True
        """
        try:
            return await self.dao.delete_record(record_id)
        except Exception as e:
            logger.error(f"删除工作流记录失败: {e}")
            raise

    async def update_workflow_status(self, record_id: int, status: int,
                                     ext_data: Optional[Dict[str, Any]] = None) -> Optional[
        VideoWorkflowRecord]:
        """
        更新工作流状态
        
        Args:
            record_id: 记录ID
            status: 新状态
            ext_data: 扩展数据（可选）
            
        Returns:
            更新后的记录对象
        """
        try:
            if ext_data:
                # 如果有扩展数据，使用完整更新
                update_data = VideoWorkflowRecordUpdate(status=status, ext=ext_data)
                return await self.dao.update_record(record_id, update_data)
            else:
                # 只更新状态
                return await self.dao.update_status(record_id, status)
        except Exception as e:
            logger.error(f"更新工作流状态失败: {e}")
            raise

    async def update_workflow_progress(self,
                                       session_id: str,
                                       workflow_id: str,
                                       status: int,
                                       progress_data: Dict[str, Any]) -> Optional[
        VideoWorkflowRecord]:
        """
        更新工作流进度
        
        Args:
            session_id: 会话ID
            workflow_id: 工作流ID
            status: 状态
            progress_data: 进度数据
            
        Returns:
            更新后的记录对象
        """
        try:
            # 先获取记录
            record = await self.dao.get_record_by_session_id_and_workflow_id(session_id)
            if not record:
                logger.error(f"未找到会话ID {session_id} 工作流ID {workflow_id} 的记录")
                return None

            # 合并扩展数据
            current_ext = record.ext or {}
            current_ext.update(progress_data)

            # 更新记录
            update_data = VideoWorkflowRecordUpdate(status=status, ext=current_ext)
            return await self.dao.update_record(record.id, update_data)

        except Exception as e:
            logger.error(f"更新工作流进度失败: {e}")
            raise

    async def batch_update_status(self, record_ids: List[int], status: int) -> int:
        """
        批量更新状态
        
        Args:
            record_ids: 记录ID列表
            status: 新状态
            
        Returns:
            更新成功的记录数量
        """
        try:
            return await self.dao.batch_update_status(record_ids, status)
        except Exception as e:
            logger.error(f"批量更新状态失败: {e}")
            raise

    async def get_records_by_status(self, status: int, limit: int = 100) -> List[
        VideoWorkflowRecord]:
        """
        根据状态获取记录
        
        Args:
            status: 状态
            limit: 限制数量
            
        Returns:
            记录列表
        """
        try:
            return await self.dao.get_records_by_status(status, limit)
        except Exception as e:
            logger.error(f"根据状态获取记录失败: {e}")
            raise

    async def create_or_update_workflow_record(self,
                                               session_id: str,
                                               workflow_id: str,
                                               record_data: VideoWorkflowRecordCreate) -> VideoWorkflowRecord:
        """
        创建或更新工作流记录（事务操作）
        
        Args:
            session_id: 会话ID
            workflow_id: 工作流ID
            record_data: 记录数据
            
        Returns:
            记录对象
        """
        try:
            async with db_manager.transaction() as conn:
                # 检查是否存在
                existing_record = await self.dao.get_record_by_session_id_and_workflow_id(session_id)

                if existing_record:

                    # 在事务中更新
                    sql = """
                          UPDATE video_workflow_record
                          SET status      = %s,
                              ext         = %s,
                              update_time = %s
                          WHERE id = %s \
                          """

                    ext_json = json.dumps(record_data.ext,
                                          ensure_ascii=False) if record_data.ext else None
                    params = (
                        record_data.status,
                        ext_json,
                        datetime.now(),
                        existing_record.id
                    )

                    await db_manager.execute_with_retry(sql, params, connection=conn)

                    # 返回更新后的记录
                    return await self.dao.get_record_by_id(existing_record.id)
                else:
                    # 创建新记录
                    now = datetime.now()
                    ext_json = json.dumps(record_data.ext,
                                          ensure_ascii=False) if record_data.ext else None

                    sql = """
                          INSERT INTO video_workflow_record
                          (session_id, video_url, workflow_id, username, status, task_name, ext, create_time,
                           update_time)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) \
                          """

                    params = (
                        record_data.session_id,
                        record_data.video_url,
                        record_data.workflow_id,
                        record_data.username,
                        record_data.status,
                        record_data.task_name,
                        ext_json,
                        now,
                        now
                    )

                    async with db_manager.get_cursor(conn) as cursor:
                        await cursor.execute(sql, params)
                        record_id = cursor.lastrowid

                    # 返回创建的记录
                    return await self.dao.get_record_by_id(record_id)

        except Exception as e:
            logger.error(f"创建或更新工作流记录失败: {e}")
            raise

    async def cleanup_old_records(self, days: int = 30) -> int:
        """
        清理旧记录
        
        Args:
            days: 保留天数
            
        Returns:
            删除的记录数量
        """
        try:
            sql = """
                  DELETE
                  FROM video_workflow_record
                  WHERE create_time < DATE_SUB(NOW(), INTERVAL %s DAY) \
                  """

            rows_affected = await db_manager.execute_with_retry(sql, (days,))
            logger.info(f"清理了 {rows_affected} 条旧记录")
            return rows_affected

        except Exception as e:
            logger.error(f"清理旧记录失败: {e}")
            raise

    async def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计数据
        """
        try:
            # 总记录数
            total_sql = "SELECT COUNT(*) FROM video_workflow_record"
            total_result = await db_manager.execute_with_retry(total_sql, fetch_type="one")
            total_count = total_result[0] if total_result else 0

            # 按状态统计
            status_sql = """
                         SELECT status, COUNT(*) as count
                         FROM video_workflow_record
                         GROUP BY status \
                         """
            status_results = await db_manager.execute_with_retry(status_sql, fetch_type="all")
            status_stats = {row[0]: row[1] for row in status_results} if status_results else {}

            # 今日新增
            today_sql = """
                        SELECT COUNT(*)
                        FROM video_workflow_record
                        WHERE DATE (create_time) = CURDATE() \
                        """
            today_result = await db_manager.execute_with_retry(today_sql, fetch_type="one")
            today_count = today_result[0] if today_result else 0

            return {
                "total_records": total_count,
                "status_distribution": status_stats,
                "today_new_records": today_count,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            raise

    async def update_note_content(
            self,
            session_id: str,
            username: Optional[str],
            title: str,
            content: str,
            tag_list: List[str],
            image_list: List[str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        更新笔记内容
        
        Args:
            session_id: 会话ID
            username: 用户名，如果为None或空则使用"global"
            title: 标题
            content: 内容
            tag_list: 标签列表
            image_list: 图片列表
            
        Returns:
            (成功标志, 消息, 数据字典)
        """
        try:
            # 处理 username，如果为空则设为 "global"
            username = username if username else "global"
            
            # 构建查询参数
            query_params = VideoWorkflowRecordQuery(
                session_id=session_id,
                username=username,
                limit=1,
                offset=0
            )
            
            # 查询记录
            records, total_count = await self.query_workflow_records(query_params)
            
            if not records or total_count == 0:
                return (
                    False,
                    f"未找到会话ID为 {session_id}、用户名为 {username} 的记录",
                    None
                )
            
            # 获取第一条记录
            record = records[0]

            state = parse_state_from_ext(record.ext)
            
            # 获取 xhs_final_text_node_result 字段
            xhs_final_text_node_result = state.get("xhs_final_text_node_result", {})
            logger.debug(f"xhs_final_text_node_result 类型: {type(xhs_final_text_node_result)}")
            
            # 如果 xhs_final_text_node_result 是字符串，需要再次解析
            if isinstance(xhs_final_text_node_result, str):
                logger.warning(f"xhs_final_text_node_result 是字符串类型，尝试再次解析")
                try:
                    xhs_final_text_node_result = json.loads(xhs_final_text_node_result)
                    logger.info(f"xhs_final_text_node_result 再次解析成功，类型: {type(xhs_final_text_node_result)}")
                except json.JSONDecodeError as e:
                    logger.error(f"解析 xhs_final_text_node_result 字段失败: {e}")
                    return (
                        False,
                        f"xhs_final_text_node_result 字段格式错误: {str(e)}",
                        None
                    )
            
            # 确保 xhs_final_text_node_result 是字典
            if not isinstance(xhs_final_text_node_result, dict):
                logger.warning(f"xhs_final_text_node_result 不是字典类型: {type(xhs_final_text_node_result)}, 创建新的对象")
                xhs_final_text_node_result = {}
            
            # 记录更新前的值（用于日志）
            old_values = {
                "title": xhs_final_text_node_result.get("title"),
                "full_caption": xhs_final_text_node_result.get("full_caption"),
                "hashtags": xhs_final_text_node_result.get("hashtags"),
                "images": xhs_final_text_node_result.get("images")
            }
            
            # 更新字段
            xhs_final_text_node_result["title"] = title
            xhs_final_text_node_result["full_caption"] = content
            xhs_final_text_node_result["hashtags"] = tag_list
            xhs_final_text_node_result["images"] = image_list
            
            # 写回 state
            state["xhs_final_text_node_result"] = xhs_final_text_node_result
            
            # 创建更新数据 - ExtMixin 的 validator 会自动处理 ExtendData 对象的 JSON 序列化
            update_data = VideoWorkflowRecordUpdate(ext=ExtendData(state=state))
            
            # 更新记录
            updated_record = await self.update_workflow_record(record.id, update_data)
            
            if not updated_record:
                return (
                    False,
                    "更新记录失败",
                    None
                )
            
            # 记录日志
            logger.info(
                f"成功更新笔记内容: session_id={session_id}, username={username}, "
                f"record_id={record.id}, title='{title}', "
                f"tags={len(tag_list)}, images={len(image_list)}"
            )
            
            # 返回成功响应
            return (
                True,
                f"成功更新会话 {session_id} 的笔记内容",
                {
                    "session_id": session_id,
                    "username": username,
                    "record_id": record.id,
                    "old_values": old_values,
                    "updated_fields": {
                        "title": title,
                        "content": content,
                        "tag_list": tag_list,
                        "image_list": image_list
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"更新笔记内容失败: session_id={session_id}, username={username}, error={e}", exc_info=True)
            return (
                False,
                f"更新失败: {str(e)}",
                None
            )

    async def close(self) -> None:
        """关闭服务"""
        await db_manager.close()
        logger.info("视频工作流记录服务已关闭")


# 全局服务实例
video_workflow_record_service = VideoWorkflowRecordService()
