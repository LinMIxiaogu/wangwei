"""
视频工作流记录数据访问对象(DAO)
提供video_workflow_record表的CRUD操作
"""
import logging
from datetime import datetime
from typing import Optional, List, Tuple

from .connection import db_manager
from .models import (
    VideoWorkflowRecord,
    VideoWorkflowRecordCreate,
    VideoWorkflowRecordUpdate,
    VideoWorkflowRecordQuery,
)

logger = logging.getLogger(__name__)


class VideoWorkflowRecordDAO:
    """视频工作流记录数据访问对象"""

    def __init__(self):
        self.table_name = "video_workflow_record"
        self.columns = [
            "id", "session_id", "workflow_id", "task_name", "video_url", "username",
            "ext", "status", "create_time", "update_time"
        ]

    async def create_record(self, record_data: VideoWorkflowRecordCreate) -> Optional[
        VideoWorkflowRecord]:
        """
        创建新的视频工作流记录
        
        Args:
            record_data: 创建记录的数据
            
        Returns:
            创建成功的记录对象，失败返回None
        """
        try:
            # 准备插入数据
            now = datetime.now()
            # record_data.ext已经是JSON字符串，不需要再次json.dumps
            ext_json = record_data.ext

            sql = f"""
            INSERT INTO {self.table_name} 
            (session_id, workflow_id, task_name, video_url, username, ext, status, create_time, update_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            params = (
                record_data.session_id,
                record_data.workflow_id,
                record_data.task_name,
                record_data.video_url,
                record_data.username,
                ext_json,
                record_data.status,
                now,
                now
            )

            # ✅ 使用事务确保数据一致性和立即提交
            async with db_manager.transaction() as conn:
                async with db_manager.get_cursor(conn) as cursor:
                    await cursor.execute(sql, params)
                    record_id = cursor.lastrowid

            # 事务自动提交

            logger.info(f"成功创建视频工作流记录，ID: {record_id}")

            # 返回创建的记录
            return await self.get_record_by_id(record_id)

        except Exception as e:
            logger.error(f"创建视频工作流记录失败: {e}")
            raise

    async def get_record_by_id(self, record_id: int) -> Optional[VideoWorkflowRecord]:
        """
        根据ID查询单个记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            查询到的记录对象，不存在返回None
        """
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE id = %s
            """

            row = await db_manager.execute_with_retry(sql, (record_id,), fetch_type="one")

            if row:
                record = VideoWorkflowRecord.from_db_row(row)
                logger.info(f"成功获取记录，ID: {record_id}")
                return record
            else:
                logger.warning(f"记录不存在，ID: {record_id}")
                return None

        except Exception as e:
            logger.error(f"根据ID查询记录失败: {e}")
            raise

    async def get_record_by_session_id_and_workflow_id(self, session_id: str) -> \
            Optional[VideoWorkflowRecord]:
        """
        根据会话ID查询记录
        
        Args:
            session_id: 会话ID
            workflow_id: 工作流ID
            
        Returns:
            查询到的记录对象，不存在返回None
        """
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE session_id = %s 
            ORDER BY create_time DESC
            LIMIT 1
            """

            row = await db_manager.execute_with_retry(sql, (session_id),
                                                      fetch_type="one")

            if row:
                record = VideoWorkflowRecord.from_db_row(row)
                logger.info(f"成功获取记录，会话ID: {session_id}")
                return record
            else:
                logger.warning(f"记录不存在，会话ID: {session_id}")
                return None

        except Exception as e:
            logger.error(f"根据会话ID查询记录失败: {e}")
            raise

    async def query_records(self, query_params: VideoWorkflowRecordQuery) -> Tuple[
        List[VideoWorkflowRecord], int]:
        """
        条件查询记录
        
        Args:
            query_params: 查询参数
            
        Returns:
            (记录列表, 总数量)
        """
        try:
            # 构建WHERE条件
            where_conditions = []
            params = []

            if query_params.session_id:
                where_conditions.append("session_id = %s")
                params.append(query_params.session_id)

            if query_params.workflow_id:
                where_conditions.append("workflow_id = %s")
                params.append(query_params.workflow_id)

            if query_params.task_name:
                where_conditions.append("task_name LIKE %s")
                params.append(f"%{query_params.task_name}%")

            if query_params.video_url:
                where_conditions.append("video_url LIKE %s")
                params.append(f"%{query_params.video_url}%")

            if query_params.status is not None:
                where_conditions.append("status = %s")
                params.append(query_params.status)

            where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""

            # 查询总数
            count_sql = f"SELECT COUNT(*) as total FROM {self.table_name}{where_clause}"
            count_result = await db_manager.execute_with_retry(count_sql, tuple(params),
                                                               fetch_type="one")
            total_count = count_result.get('total', 0) if count_result else 0

            # 查询记录
            sql = f"""
        SELECT {', '.join(self.columns)}
            FROM {self.table_name}{where_clause}
            ORDER BY create_time DESC 
            """

            rows = await db_manager.execute_with_retry(sql, tuple(params), fetch_type="all")

            records = [VideoWorkflowRecord.from_db_row(row) for row in rows] if rows else []

            logger.info(f"条件查询返回 {len(records)} 条记录，总数: {total_count}")
            return records, total_count

        except Exception as e:
            logger.error(f"条件查询记录失败: {e}")
            raise

    async def update_record(self, record_id: int, update_data: VideoWorkflowRecordUpdate) -> \
            Optional[VideoWorkflowRecord]:
        """
        更新记录
        
        Args:
            record_id: 记录ID
            update_data: 更新数据
            
        Returns:
            更新后的记录对象，失败返回None
        """
        try:
            # 构建更新字段
            update_fields = []
            params = []

            update_dict = update_data.dict(exclude_unset=True)

            for field, value in update_dict.items():
                if field == "ext" and value is not None:
                    update_fields.append("ext = %s")
                    # value已经是JSON字符串，不需要再次json.dumps
                    params.append(value)
                else:
                    update_fields.append(f"{field} = %s")
                    params.append(value)

            if not update_fields:
                logger.warning("没有需要更新的字段")
                return await self.get_record_by_id(record_id)

            # 添加更新时间
            update_fields.append("update_time = %s")
            params.append(datetime.now())

            # 添加WHERE条件
            params.append(record_id)

            sql = f"""
            UPDATE {self.table_name} 
            SET {', '.join(update_fields)}
            WHERE id = %s
            """

            # ✅ 使用事务确保提交
            async with db_manager.transaction() as conn:
                rows_affected = await db_manager.execute_with_retry(sql, tuple(params), connection=conn)

            if rows_affected > 0:
                logger.info(f"成功更新记录，ID: {record_id}")
                return await self.get_record_by_id(record_id)
            else:
                logger.warning(f"记录不存在或未更新，ID: {record_id}")
                return None

        except Exception as e:
            logger.error(f"更新记录失败: {e}")
            raise

    async def delete_record(self, record_id: int) -> bool:
        """
        删除记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            删除成功返回True，失败返回False
        """
        try:
            sql = f"DELETE FROM {self.table_name} WHERE id = %s"

            # ✅ 使用事务确保提交
            async with db_manager.transaction() as conn:
                rows_affected = await db_manager.execute_with_retry(sql, (record_id,), connection=conn)

            if rows_affected > 0:
                logger.info(f"成功删除记录，ID: {record_id}")
                return True
            else:
                logger.warning(f"记录不存在或未删除，ID: {record_id}")
                return False

        except Exception as e:
            logger.error(f"删除记录失败: {e}")
            raise

    async def update_status(self, record_id: int, status: str) -> Optional[VideoWorkflowRecord]:
        """
        更新记录状态
        
        Args:
            record_id: 记录ID
            status: 新状态
            
        Returns:
            更新后的记录对象，失败返回None
        """
        try:
            sql = f"""
            UPDATE {self.table_name} 
            SET status = %s, update_time = %s
            WHERE id = %s
            """

            params = (status, datetime.now(), record_id)
            # ✅ 使用事务确保提交
            async with db_manager.transaction() as conn:
                rows_affected = await db_manager.execute_with_retry(sql, params, connection=conn)

            if rows_affected > 0:
                logger.info(f"成功更新记录状态，ID: {record_id}, 状态: {status}")
                return await self.get_record_by_id(record_id)
            else:
                logger.warning(f"记录不存在或状态未更新，ID: {record_id}")
                return None

        except Exception as e:
            logger.error(f"更新记录状态失败: {e}")
            raise

    async def batch_update_status(self, record_ids: List[int], status: str) -> int:
        """
        批量更新记录状态
        
        Args:
            record_ids: 记录ID列表
            status: 新状态
            
        Returns:
            更新的记录数量
        """
        try:
            if not record_ids:
                return 0

            placeholders = ','.join(['%s'] * len(record_ids))
            sql = f"""
            UPDATE {self.table_name} 
            SET status = %s, update_time = %s
            WHERE id IN ({placeholders})
            """

            params = [status, datetime.now()] + record_ids
            # ✅ 使用事务确保批量操作的原子性和提交
            async with db_manager.transaction() as conn:
                rows_affected = await db_manager.execute_with_retry(sql, tuple(params), connection=conn)

            logger.info(f"批量更新状态成功，更新了 {rows_affected} 条记录")
            return rows_affected

        except Exception as e:
            logger.error(f"批量更新状态失败: {e}")
            raise

    async def get_records_by_status(self, status: str, limit: int = 100) -> List[
        VideoWorkflowRecord]:
        """
        根据状态获取记录列表
        
        Args:
            status: 状态值
            limit: 限制数量
            
        Returns:
            记录列表
        """
        try:
            sql = f"""
            SELECT {', '.join(self.columns)}
            FROM {self.table_name}
            WHERE status = %s
            ORDER BY create_time DESC
            LIMIT %s
            """

            rows = await db_manager.execute_with_retry(sql, (status, limit), fetch_type="all")

            records = [VideoWorkflowRecord.from_db_row(row) for row in rows] if rows else []

            logger.info(f"根据状态查询返回 {len(records)} 条记录")
            return records

        except Exception as e:
            logger.error(f"根据状态查询记录失败: {e}")
            raise


# 全局DAO实例
video_workflow_record_dao = VideoWorkflowRecordDAO()
