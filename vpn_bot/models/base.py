from contextlib import asynccontextmanager
from functools import wraps

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

DB_PATH = "bot.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


@asynccontextmanager
async def provide_session_scope(session: AsyncSession | None = None):
    if session is not None:
        yield session
    else:
        async with AsyncSessionLocal() as new_session:
            try:
                yield new_session
                await new_session.commit()
            except Exception:
                await new_session.rollback()
                raise


def provide_session(func_to_decorate):
    @wraps(func_to_decorate)
    async def wrapper(*args, **kwargs):
        session = kwargs.get("session")
        if session is not None:
            return await func_to_decorate(*args, **kwargs)
        async with provide_session_scope() as new_session:
            kwargs["session"] = new_session
            return await func_to_decorate(*args, **kwargs)
    return wrapper
