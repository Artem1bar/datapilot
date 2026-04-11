"""Seed the database with test data for local development."""

import asyncio
import uuid

from sqlalchemy import select

from app.db.engine import async_session
from app.models.user import User


async def seed():
    async with async_session() as session:
        # Check if test user already exists
        result = await session.execute(
            select(User).where(User.clerk_id == "user_test_dev")
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Test user already exists: {existing.email}")
            return

        user = User(
            id=uuid.uuid4(),
            clerk_id="user_test_dev",
            email="dev@datapilot.local",
            plan="pro",
            credits_remaining=1000,
        )
        session.add(user)
        await session.commit()
        print(f"Created test user: {user.email} (plan={user.plan})")


if __name__ == "__main__":
    asyncio.run(seed())
