"""异步引擎与会话工厂。

引擎在导入时构造但**不建立连接**（asyncpg 惰性连接），因此无数据库环境
也能导入应用与运行单元测试。`/ready` 是唯一主动探测数据库的地方。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，退出时自动关闭。"""

    async with session_factory() as session:
        yield session
