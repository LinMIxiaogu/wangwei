"""
MySQL数据库配置模块
"""
import aiomysql
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_settings import BaseSettings

# 加载 .env 文件
load_dotenv()


class DatabaseConfig(BaseSettings):
    """数据库配置类"""

    # MySQL连接配置 - 直接使用环境变量名
    DB_MYSQL_HOST: str = "localhost"
    DB_MYSQL_PORT: int = 3306
    DB_MYSQL_USER: str = "root"
    DB_MYSQL_PASSWORD: str = ""
    DB_MYSQL_DATABASE: str = "test"
    DB_MYSQL_CHARSET: str = "utf8mb4"

    # 连接池配置
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # 连接超时配置
    DB_CONNECT_TIMEOUT: int = 10
    DB_READ_TIMEOUT: int = 30
    DB_WRITE_TIMEOUT: int = 30

    # 重试配置
    DB_MAX_RETRIES: int = 3
    DB_RETRY_DELAY: float = 1.0

    # 为了保持向后兼容，添加属性方法
    @property
    def mysql_host(self) -> str:
        return self.DB_MYSQL_HOST

    @property
    def mysql_port(self) -> int:
        return self.DB_MYSQL_PORT

    @property
    def mysql_user(self) -> str:
        return self.DB_MYSQL_USER

    @property
    def mysql_password(self) -> str:
        return self.DB_MYSQL_PASSWORD

    @property
    def mysql_database(self) -> str:
        return self.DB_MYSQL_DATABASE

    @property
    def mysql_charset(self) -> str:
        return self.DB_MYSQL_CHARSET

    @property
    def pool_size(self) -> int:
        return self.DB_POOL_SIZE

    @property
    def max_overflow(self) -> int:
        return self.DB_MAX_OVERFLOW

    @property
    def pool_timeout(self) -> int:
        return self.DB_POOL_TIMEOUT

    @property
    def pool_recycle(self) -> int:
        return self.DB_POOL_RECYCLE

    @property
    def connect_timeout(self) -> int:
        return self.DB_CONNECT_TIMEOUT

    @property
    def read_timeout(self) -> int:
        return self.DB_READ_TIMEOUT

    @property
    def write_timeout(self) -> int:
        return self.DB_WRITE_TIMEOUT

    @property
    def max_retries(self) -> int:
        return self.DB_MAX_RETRIES

    @property
    def retry_delay(self) -> float:
        return self.DB_RETRY_DELAY

    class Config:
        case_sensitive = True
        extra = "ignore"  # 忽略额外的环境变量


class ConnectionInfo(BaseModel):
    """数据库连接信息"""
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"

    def get_dsn(self) -> str:
        """获取数据库连接字符串"""
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?charset={self.charset}"

    def get_aiomysql_params(self) -> dict:
        """获取aiomysql连接参数"""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "db": self.database,
            "charset": self.charset,
            "autocommit": True,  # ✅ 启用自动提交模式，确保每条语句立即生效
            "cursorclass": aiomysql.DictCursor  # 使用字典游标类
        }


# 全局数据库配置实例
db_config = DatabaseConfig()

# 数据库连接信息
connection_info = ConnectionInfo(
    host=db_config.mysql_host,
    port=db_config.mysql_port,
    user=db_config.mysql_user,
    password=db_config.mysql_password,
    database=db_config.mysql_database,
    charset=db_config.mysql_charset
)
