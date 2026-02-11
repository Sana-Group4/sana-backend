from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String,Integer,DateTime,ForeignKey
from db import Base

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    firstName: Mapped[str] = mapped_column(String(50), unique=False, nullable=False)
    lastName: Mapped[str] = mapped_column(String(50), unique=False, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=True)
    phone: Mapped[int] = mapped_column(Integer(), unique = True, nullable = True)
    hashedPass: Mapped[str] = mapped_column(String(255), unique=False, nullable=False)
    userType: Mapped[str] = mapped_column(String(15), unique = False, nullable=False)

    #deletes databse entries when user removed
    refresh_tokens = relationship("RefreshTokens", back_populates="user", cascade="all, delete-orphan")
    activities = relationship("Activity", back_populates="user", cascade="all, delete-orphan")

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

class RefreshTokens(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String(255))
    expireTime: Mapped[DateTime] = mapped_column(DateTime(), nullable=False)

    #allows for 'instance.user' to get user entry
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
