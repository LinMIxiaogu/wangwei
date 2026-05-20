"""
MySQL数据库连接池管理模块
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, AsyncContextManager, Any

import aiomysql
import pymysql
from aiomysql import Pool, Connection, Cursor

from .config import db_config, connection_info

logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """数据库连接池管理器"""

    def __init__(self):
        self._pool: Optional[Pool] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """初始化数据库连接池"""
        if self._pool is not None:
            logger.warning("数据库连接池已经初始化")
            return

        async with self._lock:
            if self._pool is not None:
                return

            try:
                logger.info("正在初始化MySQL连接池...")

                # 获取连接参数
                conn_params = connection_info.get_aiomysql_params()

                # 添加连接池配置
                pool_params = {
                    **conn_params,
                    "minsize": 1,
                    "maxsize": db_config.pool_size,
                    "pool_recycle": db_config.pool_recycle,
                    "connect_timeout": db_config.connect_timeout,
                    "echo": False,
                }

                # 创建连接池
                self._pool = await aiomysql.create_pool(**pool_params)

                # 测试连接
                await self._test_connection()

                logger.info(f"MySQL连接池初始化成功，池大小: {db_config.pool_size}")

            except Exception as e:
                logger.error(f"MySQL连接池初始化失败: {e}")
                raise

    async def _test_connection(self) -> None:
        """测试数据库连接"""
        try:
            async with self.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1 as test_value")
                    result = await cursor.fetchone()
                    # 使用DictCursor时，结果是字典格式
                    if result.get('test_value') != 1:
                        raise Exception("数据库连接测试失败")
            logger.info("数据库连接测试成功")
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            raise

    @asynccontextmanager
    async def get_connection(self) -> AsyncContextManager[Connection]:
        """获取数据库连接（上下文管理器）"""
        if self._pool is None:
            await self.initialize()

        connection = None
        try:
            # 从连接池获取连接
            connection = await self._pool.acquire()
            yield connection
        except Exception as e:
            logger.error(f"获取数据库连接失败: {e}")
            raise
        finally:
            if connection:
                # 将连接返回到连接池
                self._pool.release(connection)

    @asynccontextmanager
    async def get_cursor(self, connection: Connection = None) -> AsyncContextManager[Cursor]:
        """获取数据库游标（上下文管理器）"""
        if connection:
            # 使用提供的连接
            cursor = await connection.cursor()
            try:
                yield cursor
            finally:
                await cursor.close()
        else:
            # 获取新连接
            async with self.get_connection() as conn:
                cursor = await conn.cursor()
                try:
                    yield cursor
                finally:
                    await cursor.close()

    async def execute_with_retry(self,
                                 sql: str,
                                 params: tuple = None,
                                 connection: Connection = None,
                                 fetch_type: str = "none") -> Any:
        """
        执行SQL语句，带重试机制
        
        Args:
            sql: SQL语句
            params: 参数
            connection: 数据库连接（可选）
            fetch_type: 获取结果类型 ("none", "one", "all")
        
        Returns:
            查询结果或影响行数
        """
        last_exception = None

        for attempt in range(db_config.max_retries):
            try:
                if connection:
                    # 使用提供的连接
                    async with self.get_cursor(connection) as cursor:
                        await cursor.execute(sql, params)

                        if fetch_type == "one":
                            return await cursor.fetchone()
                        elif fetch_type == "all":
                            return await cursor.fetchall()
                        else:
                            # ✅ 对于写操作，在返回前确保提交（即使autocommit=True也不影响）
                            rowcount = cursor.rowcount
                            # 显式提交以确保数据可见（在事务模式下）
                            await connection.commit()
                            return rowcount
                else:
                    # 获取新连接
                    async with self.get_connection() as conn:
                        async with self.get_cursor(conn) as cursor:
                            await cursor.execute(sql, params)

                            if fetch_type == "one":
                                return await cursor.fetchone()
                            elif fetch_type == "all":
                                return await cursor.fetchall()
                            else:
                                # ✅ 对于写操作，在返回前确保提交
                                rowcount = cursor.rowcount
                                await conn.commit()
                                return rowcount

            except (aiomysql.Error, pymysql.Error) as e:
                last_exception = e
                logger.warning(f"SQL执行失败 (尝试 {attempt + 1}/{db_config.max_retries}): {e}")

                if attempt < db_config.max_retries - 1:
                    await asyncio.sleep(db_config.retry_delay * (attempt + 1))
                    continue
                else:
                    break
            except Exception as e:
                logger.error(f"SQL执行出现未知错误: {e}")
                raise

        # 所有重试都失败了
        logger.error(f"SQL执行失败，已重试 {db_config.max_retries} 次: {last_exception}")
        raise last_exception

    @asynccontextmanager
    async def transaction(self) -> AsyncContextManager[Connection]:
        """事务上下文管理器"""
        async with self.get_connection() as connection:
            try:
                # 开始事务
                await connection.begin()
                yield connection
                # 提交事务
                await connection.commit()
            except Exception as e:
                # 回滚事务
                await connection.rollback()
                logger.error(f"事务执行失败，已回滚: {e}")
                raise

    async def close(self) -> None:
        """关闭连接池"""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.info("数据库连接池已关闭")

    @property
    def is_initialized(self) -> bool:
        """检查连接池是否已初始化"""
        return self._pool is not None


# 全局数据库连接管理器实例
db_manager = DatabaseConnectionManager()
