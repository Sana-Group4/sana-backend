from __future__ import annotations

import strawberry
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Item


@strawberry.type
class ItemType:
    id: int
    name: str


@strawberry.type
class Query:
    @strawberry.field
    async def items(self, info) -> List[ItemType]:
        db: AsyncSession = info.context["db"]
        result = await db.execute(select(Item))
        return [ItemType(id=i.id, name=i.name) for i in result.scalars().all()]


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_item(self, info, name: str) -> ItemType:
        db: AsyncSession = info.context["db"]
        item = Item(name=name)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return ItemType(id=item.id, name=item.name)


schema = strawberry.Schema(query=Query, mutation=Mutation)
