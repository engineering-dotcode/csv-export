from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import settings

async_engine = create_async_engine(settings.database_url.replace("postgresql://", "postgresql+asyncpg://"))
async_session_maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(settings.database_url)
sync_session_maker = sessionmaker(bind=sync_engine, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with async_session_maker() as session:
        yield session

def get_sync_db():
    db = sync_session_maker()
    try:
        yield db
    finally:
        db.close() 