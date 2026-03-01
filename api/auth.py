from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select,delete,insert, or_
from jwt.exceptions import InvalidTokenError

from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr

import hashlib
import json
import httpx

import os
from dotenv import load_dotenv
from db import get_db
from models import User, RefreshTokens, UserType, AuthProvider

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
    email: EmailStr
    firstName: str
    lastName: str
    username: str
    password: str
    userType: UserType #Enum containing "CLIENT" and "COACH"

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
        userType = UserType.user_data.userType
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
                user_id = user.id,
                token = hashlib.sha256(token_value.encode()).hexdigest(),
                expireTime = expire
            )
        )

        await db.execute(query)
        await db.commit()

        return token_value

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


async def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]):
    #can add extra features here, if needed
    return current_user


#uses login code to fetch access_token
#uses access token to get user profile
async def get_google_user_data(code):
    async with httpx.AsyncClient() as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": "Sana_Backend_V1",
            "client_secret": "SECRET",
            "redirect_uri": "http://localhost:8000/auth/google/callback"
        })
        user_data = response.json()

        profile_response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {user_data['access_token']}"}
        )
    
    return profile_response.json()

@router.get("/auth/google/login")
async def google_login():
    google_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": "Sana_Backend_V1",
        "redirect_uri": "http://localhost:8000/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
    }
    #redirects to google login API
    #callback goes to "/auth/google/callback"
    return RedirectResponse(f"{google_url}?{'&'.join([f'{k}={v}' for k,v in params])}")


@router.get("/auth/google/callback")
async def google_callback(response: Response, code: str, db: AsyncSession = Depends(get_db)):
    google_user = await get_google_user_data(code)

    query = (
        select(User)
        .where(User.email == google_user['email'] and User.authProvider == AuthProvider.GOOGLE)
    )

    result = await db.execute(query)
    user = result.scalars().first()


    #user doesnt exist so add to database
    if not user:
        user = User(
            email = google_user['email'],
            username = google_user['name'],
            firstName = google_user['given_name'],
            lastName = google_user['family_name'],
            UserType = UserType.CLIENT,
            authProvider = AuthProvider.GOOGLE,
            google_id = google_user['sub'],
            hashedPass = None
        )

        query = insert(User).values(user)

        success = await db.execute(query)
        if not success:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="error registering user, please try again")
        

    refresh = create_refresh_token(user, db)

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60*60*24*REFRESH_TOKEN_EXPIRE_DAYS
    )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)

    return Token(access_token= access_token, token_type="bearer")
       


#creates account using user inputted data
#returns jwt access token
@router.post("/register")
async def register(response: Response, userData: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    query = select(User).where(
        or_(User.username == userData.username, User.email == userData.email)
    )
    res = await db.execute(query)
    existing_user = res.scalars().first()

    if existing_user:
        detail_msg = "username or email already in use"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail= detail_msg)
    

    user = await add_User(db, userData)

    refresh_token = await create_refresh_token(user, db)

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
    
    refresh_token = await create_refresh_token(user, db)

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
async def refresh_access(response: Response, refresh_token: Annotated[str | None, Cookie()] = None, db: AsyncSession = Depends(get_db)):

    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="No refresh token provided"
        ) 

   
    #match hashed token, return token+user instance (joined)
    token_hashed = hashlib.sha256(refresh_token.encode()).hexdigest()
    query = (
        select(RefreshTokens)
        .where(RefreshTokens.token == token_hashed)
        .options(selectinload(RefreshTokens.user))
    )

    result = await db.execute(query)
    entry = result.scalars().first()
    if not entry:
        response.delete_cookie("refresh_token")
        raise HTTPException(status_code=401, detail="Refresh token invalid")

    if entry:
        if datetime.now(timezone.utc) > entry.expireTime.replace(tzinfo=timezone.utc):
            await db.delete(entry)
            await db.commit()
            raise HTTPException(status_code=401, detail="Refresh token expired")
        
    user = entry.user
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expire_delta=access_token_expires)
    return Token(access_token= access_token, token_type="bearer")

@router.post("/logout")
async def logout(response: Response, refresh_token: Annotated[str | None, Cookie()]= None, db:AsyncSession = Depends(get_db)):

    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No Cookie found")

    #match hashed token, return token+user instance (joined)
    token_hashed = hashlib.sha256(refresh_token.encode()).hexdigest()
    query = (
        delete(RefreshTokens)
        .where(RefreshTokens.token == token_hashed)
    )
    result = await db.execute(query)
    await db.commit()

    response.delete_cookie(
        key="refresh_token"
    )
    
    if result.rowcount == 0:
        return{"detail": "Token invalid, Cookie cleared"}

    return{"detail":"refresh token removed succesfully"}


    

