from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select,insert, or_
from jwt.exceptions import InvalidTokenError

from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr

from hashlib import sha256

import os
from dotenv import load_dotenv
from db import get_db
from models import User, RefreshTokens

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/auth")

#create these values in .env
# key generation command:
# openssl rand -hex 32 
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Validate required variables
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set in .env file")
if not ALGORITHM:
    raise RuntimeError("ALGORITHM is not set in .env file")

#data required for user registration
class UserCreate(BaseModel):
    email: EmailStr | None = None
    phone: int | None = None
    firstName: str
    lastName: str
    username: str
    password: str
    userType: str #"Client" or "Coach"

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None


password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def verify_password(password, hashed_password):
    return password_hash.verify(password, hashed_password)

def get_hashed_pass(password):
    return password_hash.hash(password)

async def get_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()

#inserts data into table and returns the new data stored in the database (including defaults)
async def add_User(db:AsyncSession, user_data: UserCreate) -> User:
    hashed_pass = get_hashed_pass(user_data.password)
    user = User(
        username = user_data.username,
        firstName = user_data.firstName,
        lastName = user_data.lastName,
        email = user_data.email,
        phone = user_data.phone,
        hashedPass = hashed_pass,
        userType = user_data.userType
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


#creates and adds refresh token to database, returns values required to make refresh cookie
async def create_refresh_token(user, db: AsyncSession):
    
    token_value = secrets.token_urlsafe(32)
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    try:
        query = (
            insert(RefreshTokens).values(
                user_id = user.user_id,
                token = sha256(token_value),
                expireTime = expire
            )
        )

        await db.execute(query)
        await db.commit()

        return {
            "token": token_value,
            "username": user.username
        }

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create session. Please try again"
        )

#gets user from jwt token
async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: AsyncSession = Depends(get_db)):
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

async def access_from_refresh(response: Response, refresh_token: Annotated[str | None, Cookie()], db: AsyncSession = Depends(get_db)):
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="No refresh token provided"
        ) 

    token = refresh_token.value
    query = (
        select(RefreshTokens)
        .where(RefreshTokens.token == token)
        .options(selectinload(RefreshTokens.user))
    )

    result = await db.execute(query)
    entry = result.scalars().first()
    if not entry:
        response.delete_cookie("refresh_token")
        raise HTTPException(status_code=401, detail="Refresh token invalid")

    if entry:
        if datetime().now(timezone.utc) > entry.expireTime:
            await db.delete(entry)
            await db.commit()
            raise HTTPException(status_code=401, detail="Refresh token expired")
        
    user = entry.user
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")
        
    
async def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]):
    #can add extra features here, if needed
    return current_user


#creates account using user inputted data
#returns jwt access token
@router.post("/register")
async def register(response: Response, userData: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    if not(userData.email or userData.phone):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone or Email required")

    query = select(User).where(
        or_(User.username == userData.username, User.email == userData.email, User.phone == userData.phone)
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

    refresh_token = create_refresh_token(user, db)

    #creates refresh token as cookie sent over HTTPS, cookie expires after defined time but methods in place for token verification aswell
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60*60*24*REFRESH_TOKEN_EXPIRE_DAYS
    )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")

#returns jwt access token if credentials are correct
@router.post("/login")
async def login(response: Response, form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: AsyncSession = Depends(get_db)) -> Token:
    user = await auth_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail= "Incorrect username or password", headers={"WWW-authenticate": "Bearer"})
    
    refresh_token = create_refresh_token(user, db)

    #creates refresh token as cookie sent over HTTPS, cookie expires after defined time but methods in place for token verification aswell
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60*60*24*REFRESH_TOKEN_EXPIRE_DAYS
    )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")

@router.post("/refresh")
async def refresh_access(token:Token = Depends(access_from_refresh)) -> Token:
    #generates new access token from refresh token
    #handles exception accordingly
    return token
