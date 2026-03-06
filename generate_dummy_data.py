import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_db, Base
from models import User, Preference, Activity, CoachLink, Biometric, Item, AuthProvider, BiometricType
from datetime import datetime
import random

async def create_dummy_data(session: AsyncSession):

    # Items
    items = [Item(name=f"Item {i}") for i in range(5)]
    session.add_all(items)

    # Users
    users = []
    for i in range(10):
        user = User(
            username=f"user{i}",
            firstName=f"First{i}",
            lastName=f"Last{i}",
            email=f"user{i}@example.com",
            phone=1000000000 + i,
            hashedPass="hashedpassword",
            is_coach=(i % 2 == 0),
            authProvider=AuthProvider.LOCAL,
            google_id=None
        )
        users.append(user)
    session.add_all(users)
    await session.flush()

    # Preferences
    for user in users:
        pref = Preference(user_id=user.id, preference_info="Likes running")
        session.add(pref)

    # Activities
    for user in users:
        for j in range(2):
            activity = Activity(
                name=f"Activity {j} for {user.username}",
                description="Sample activity",
                user_id=user.id
            )
            session.add(activity)

    # Link every coach to a client
    coaches = [u for u in users if u.is_coach]
    clients = [u for u in users if not u.is_coach]
    for coach in coaches:
        for client in clients:
            link = CoachLink(coach_id=coach.id, client_id=client.id)
            session.add(link)

    # Biometrics
    for user in users:
        for btype in BiometricType:
            bio = Biometric(
                user_id=user.id,
                biometric_type=btype,
                recorded_at=datetime.utcnow(),
                value_float=random.uniform(50, 200),
                value_int=random.randint(1000, 10000)
            )
            session.add(bio)

    await session.commit()

async def main():
    async for session in get_db():
        await create_dummy_data(session)

if __name__ == "__main__":
    asyncio.run(main())
