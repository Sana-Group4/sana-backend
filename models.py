from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String
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
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashedPass: Mapped[str] = mapped_column(String(255), unique=False, nullable=False)