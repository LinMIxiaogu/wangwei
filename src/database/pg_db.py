import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL

db = {
    "database": os.getenv("PG_DATABASE"),
    "user": os.getenv("PG_USER"),
    "password": os.getenv("PG_PASSWORD"),
    "host": os.getenv("PG_HOST"),
    "port": int(os.getenv("PG_PORT") or 5432),
    "options": {
        "target_session_attrs": os.getenv("PG_OPTIONS_TARGET_SESSION_ATTRS"),
        "connect_timeout": int(os.getenv("PG_OPTIONS_CONNECT_TIMEOUT") or 10),
        "tcp_user_timeout": int(os.getenv("PG_OPTIONS_TCP_USER_TIMEOUT") or 10),
    }
}
options = (db["options"] or {})

# 常见可放入 DSN 查询参数（libpq）的键，避免把未知键塞进 URL 导致错误
URL_QUERY_WHITELIST = {
    "connect_timeout",
    "target_session_attrs",
    "sslmode",
    "application_name",
    "tcp_user_timeout",
}

# 构建 URL 查询参数：仅白名单键，并转换为字符串
extra_query = {k: str(v) for k, v in options.items() if k in URL_QUERY_WHITELIST and v is not None}

url = URL.create(
    "postgresql+psycopg2",
    username=db["user"],
    password=db["password"],
    host=db["host"],
    port=db["port"],
    database=db["database"],
    query=extra_query or None,
)

connect_args = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}

# 将所有 options 合并到 connect_args
for k, v in options.items():
    if v is not None:
        connect_args[k] = v

engine = create_engine(
    url,
    pool_size=20,
    max_overflow=0,  # 不超出上限
    pool_pre_ping=True,  # 用前探活，自动丢弃坏连接
    pool_recycle=1800,  # 30 分钟回收，避免服务端关闭
    isolation_level="AUTOCOMMIT",
    connect_args=connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def set_session_params(dbapi_conn, conn_record):
    # 针对向量检索的会话调优
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("SET hnsw.iterative_scan = 'strict_order';")
        cursor.execute("SET hnsw.ef_search = 100;")
    finally:
        cursor.close()
        # 在非自动提交模式下提交，避免 SET 语句滞留在事务中
        try:
            autocommit = getattr(dbapi_conn, "autocommit", None)
            if autocommit is False and hasattr(dbapi_conn, "commit"):
                dbapi_conn.commit()
        except Exception:
            # 某些 DBAPI 在自动提交模式下不允许调用 commit；忽略以兼容
            pass
