from fastapi import FastAPI, Depends
from strawberry.fastapi import GraphQLRouter

from rest import router as rest_router
from db import get_db
from graphql_schema import schema

app = FastAPI()

app.include_router(rest_router)

async def get_context(db=Depends(get_db)):
    return {"db": db}

graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")