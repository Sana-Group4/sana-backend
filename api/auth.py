from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from jwt.exceptions import InvalidTokenError

from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr

import os
from db import get_db
from models import User

router = APIRouter(prefix="/auth")

#create these values in .env
# key generation command:
# openssl rand -hex 32 
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))

#data required for user registration
class UserCreate(BaseModel):
    email: EmailStr
    firstName: str
    lastName: str
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None


password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(password, hashed_password):
    return password_hash.verify(password, hashed_password)

def get_hashed_pass(password):
    return password_hash.hash(password)

async def get_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()

#inserts data into table and returns the new data stored in the database (including defaults)
async def add_User(db:AsyncSession, user_data: UserCreate) -> Token:
    hashed_pass = get_hashed_pass(user_data.password)
    user = User(
        username = user_data.username,
        firstName = user_data.firstName,
        lastName = user_data.lastName,
        email = user_data.email,
        hashedPass = hashed_pass
    )
    db.add(user)
    await(db.commit())
    await(db.refresh(user))

    return user

async def auth_user(db, username, password):
    user = await get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashedPass):
        return False
    return user

def create_access_token(data: dict, expire_delta: timedelta | None = None):
    to_encode = data.copy()
    if expire_delta:
        expire = datetime.now(timezone.utc) + expire_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp" : expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

#gets user from jwt token
async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db:AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate" : "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except jwt.PyJWKError:
        raise credentials_exception
    user = await get_user(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]):
    #can add extra features here, if needed
    return current_user
    
#creates account using user inputted data
#returns jwt access token
@router.post("/register")
async def register(userData: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    query = select(User).where(
        or_(User.username == userData.username, User.email == userData.email)
    )
    res = await db.execute(query)
    existing_user = res.scalars().first()

    if existing_user:
        if existing_user.username == userData.username:
            detail_msg = "Username already in use"
        else:
            detail_msg = "Email already in use"

        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail= detail_msg)
    

    user = await add_User(db, userData)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")

#returns jwt access token if credentials are correct
@router.post("/login")
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: AsyncSession = Depends(get_db)) -> Token:
    user = await auth_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail= "Incorrect username or password", headers={"WWW-authenticate": "Bearer"})
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")
