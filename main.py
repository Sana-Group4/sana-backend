from fastapi import FastAPI, Depends
from strawberry.fastapi import GraphQLRouter

from api.rest import router as rest_router
from api.auth import auth_lifespan, router as auth_router


from db import get_db
from graphql_schema import schema

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(lifespan=auth_lifespan)

origins = [
    "http://127.0.0.1:5500",
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(auth_router)

async def get_context(db=Depends(get_db)):
    return {"db": db}

graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")