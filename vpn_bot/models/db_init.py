
from .base import AsyncSessionLocal, Base, engine
async def init_db_async():
    from vpn_bot.database import Service, User, Service
    async with engine.begin() as conn:
        # await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        # await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        await conn.run_sync(Base.metadata.create_all)
