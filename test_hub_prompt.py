import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from hub.database import Base
from hub.skill_service import HubSkillService


async def main():
    # Setup in-memory sqlite for mock DB
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # Create a HubSkillService (mock user_id and connection_manager)
        class MockConnectionManager:
            def get_connected_devices(self):
                return []

        service = HubSkillService(
            db=session,
            user_id="test_user",
            connection_manager=MockConnectionManager()
        )

        prompt = await service.get_system_prompt("my_desktop")
        print("\n=== HUB PYTHON_EXEC PROMPT ===")
        print(prompt)

        prompt_native = await service.get_system_prompt("my_desktop", tool_mode="native")
        print("\n=== HUB NATIVE PROMPT ===")
        print(prompt_native)

if __name__ == "__main__":
    asyncio.run(main())
