# データベース定義（SQLAlchemy）
import os
from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Integer, LargeBinary, String,
                        Text, create_engine)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            sessionmaker)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@db:5432/toyo_bench_mark")
# ドライバを psycopg（v3）に固定。SQLAlchemy のバージョンで既定ドライバが変わっても起動できるようにする
if DATABASE_URL.startswith(("postgresql://", "postgres://")):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
# pool_pre_ping=True で接続は使う時まで遅延（起動時にDB未起動でも落ちない）
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    """管理画面にログインできるユーザー"""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Image(Base):
    """ブログに使う画像（DB に保存するので再デプロイしても消えない）"""
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Post(Base):
    """ブログ記事"""
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32), default="お知らせ")
    excerpt: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")  # Markdown
    eyecatch_id: Mapped[int | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / published
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now)


class Inquiry(Base):
    """お問い合わせフォームの送信内容"""
    __tablename__ = "inquiries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    company: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50), default="")
    topic: Mapped[str] = mapped_column(String(50), default="")
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


_tables_ready = False


def ensure_tables() -> None:
    """初回アクセス時にテーブルを作成（DB が後から起動しても大丈夫なように遅延実行）"""
    global _tables_ready
    if not _tables_ready:
        Base.metadata.create_all(engine)
        _tables_ready = True
