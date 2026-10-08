import asyncpg
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from backend.app.core.config import settings

logger = logging.getLogger("labtrack.db")

_pool: Optional[asyncpg.Pool] = None

async def init_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        try:
            # Connect via unix socket or fallback to tcp localhost
            _pool = await asyncpg.create_pool(
                user=settings.POSTGRES_USER,
                database=settings.POSTGRES_DB,
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                min_size=2,
                max_size=20,
            )
            logger.info("Initialized asyncpg database connection pool.")
        except Exception as e:
            logger.warning(f"Connection via unix socket {settings.POSTGRES_HOST} failed ({e}), trying TCP localhost...")
            _pool = await asyncpg.create_pool(
                user=settings.POSTGRES_USER,
                database=settings.POSTGRES_DB,
                host="127.0.0.1",
                port=settings.POSTGRES_PORT,
                min_size=2,
                max_size=20,
            )
            logger.info("Initialized asyncpg database connection pool via TCP localhost.")
    return _pool

async def close_db_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Closed asyncpg database connection pool.")

@asynccontextmanager
async def get_connection():
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        yield conn

async def fetch_all(query: str, *args) -> List[Dict[str, Any]]:
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(query, *args)
        return [dict(r) for r in records]

async def fetch_one(query: str, *args) -> Optional[Dict[str, Any]]:
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(query, *args)
        return dict(record) if record else None

async def fetch_val(query: str, *args) -> Any:
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def execute(query: str, *args) -> str:
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
