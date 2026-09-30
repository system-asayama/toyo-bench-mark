# toyo-bench-mark — 株式会社東洋ベンチマーク 公式サイト（ブログ・管理画面付き）
# FastAPI で Web サイト(/)・管理画面(/admin)・MCP(/mcp/sse)を提供し、データは PostgreSQL に保存します。
import hashlib
import hmac
import logging
import math
import os
import secrets
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import content
from models import Image, Inquiry, Post, SessionLocal, User, engine, ensure_tables

log = logging.getLogger("uvicorn.error")
BASE_DIR = Path(__file__).parent
PER_PAGE = 9
MAX_IMAGE_BYTES = 5 * 1024 * 1024

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    # SECRET_KEY 未設定時は起動ごとに生成（再起動でログアウトされるだけ）
    secret_key=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    same_site="lax",
    max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
md = MarkdownIt("commonmark", {"html": False, "breaks": True, "linkify": False}).enable("table")


def render_markdown(src: str) -> Markup:
    # html=False なので記事中の生 HTML はエスケープされる
    return Markup(md.render(src or ""))


templates.env.filters["markdown"] = render_markdown
templates.env.filters["date"] = lambda d, f="%Y.%m.%d": d.strftime(f) if d else ""
templates.env.globals.update(
    company=content.COMPANY, services=content.SERVICES,
    blog_categories=content.BLOG_CATEGORIES, now=datetime.now,
)


# ── 共通ヘルパー ─────────────────────────────────────────

def get_db():
    ensure_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


def check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf")
    if not expected or not hmac.compare_digest(expected, token or ""):
        raise HTTPException(400, "フォームの有効期限が切れました。ページを再読み込みしてやり直してください。")


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("csrf", csrf_token(request))
    ctx.setdefault("user", request.session.get("user"))
    ctx.setdefault("flash", request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, ctx, status_code=ctx.pop("status_code", 200))


def flash(request: Request, msg: str) -> None:
    request.session["flash"] = msg


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 240_000).hex()
    return f"pbkdf2${salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 240_000).hex()
    return hmac.compare_digest(calc, h)


def published_posts():
    return (select(Post).where(Post.status == "published", Post.published_at <= datetime.now())
            .order_by(Post.published_at.desc(), Post.id.desc()))


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def save_image(db: Session, upload: UploadFile) -> Image:
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "画像は 5MB 以下にしてください。")
    ctype = sniff_image(data)
    if not ctype:
        raise HTTPException(400, "JPEG / PNG / GIF / WebP の画像を選んでください。")
    img = Image(filename=(upload.filename or "")[:255], content_type=ctype, data=data)
    db.add(img)
    db.flush()
    return img


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, exc: LoginRequired):
    return RedirectResponse("/admin/login", status_code=303)


def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise LoginRequired()
    return user


def bootstrap_admin_from_env(db: Session) -> None:
    """環境変数 ADMIN_USER / ADMIN_PASSWORD があれば、その管理者を自動作成"""
    u, p = os.environ.get("ADMIN_USER", "admin"), os.environ.get("ADMIN_PASSWORD")
    if p and not db.scalar(select(User).where(User.username == u)):
        db.add(User(username=u, password_hash=hash_password(p)))
        db.commit()


# ── 公開ページ ─────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    posts = []
    try:  # DB が落ちていてもトップページは表示する
        ensure_tables()
        with SessionLocal() as db:
            posts = db.scalars(published_posts().limit(3)).all()
    except Exception as e:  # noqa: BLE001
        log.warning("トップページの記事取得に失敗: %s", e)
    return render(request, "index.html", posts=posts, flow=content.FLOW, faq=content.FAQ)


@app.get("/services", response_class=HTMLResponse)
def services_index(request: Request):
    return render(request, "services.html", flow=content.FLOW)


@app.get("/services/{slug}", response_class=HTMLResponse)
def service_detail(request: Request, slug: str):
    svc = content.SERVICES.get(slug)
    if not svc:
        raise HTTPException(404)
    return render(request, "service_detail.html", svc=svc, flow=content.FLOW, faq=content.FAQ)


@app.get("/company", response_class=HTMLResponse)
def company(request: Request):
    return render(request, "company.html")


@app.get("/contact", response_class=HTMLResponse)
def contact_form(request: Request, topic: str = ""):
    return render(request, "contact.html", topics=content.INQUIRY_TOPICS,
                  form={"topic": topic}, errors=[])


@app.post("/contact", response_class=HTMLResponse)
def contact_submit(
    request: Request,
    db: Session = Depends(get_db),
    csrf: str = Form(""),
    name: str = Form(""),
    company_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    topic: str = Form(""),
    message: str = Form(""),
    agree: str = Form(""),
    website: str = Form(""),  # ボット対策（人には見えない項目）
):
    check_csrf(request, csrf)
    form = dict(name=name.strip(), company_name=company_name.strip(), email=email.strip(),
                phone=phone.strip(), topic=topic, message=message.strip())
    if website:  # ボットは黙って成功扱い
        return render(request, "contact_done.html")
    errors = []
    if not form["name"]:
        errors.append("お名前を入力してください。")
    if "@" not in form["email"] or len(form["email"]) > 200:
        errors.append("メールアドレスを正しく入力してください。")
    if not form["message"]:
        errors.append("お問い合わせ内容を入力してください。")
    if len(form["message"]) > 5000:
        errors.append("お問い合わせ内容は 5000 文字以内でお願いします。")
    if not agree:
        errors.append("個人情報の取り扱いへの同意が必要です。")
    if errors:
        return render(request, "contact.html", topics=content.INQUIRY_TOPICS, form=form,
                      errors=errors, status_code=400)
    db.add(Inquiry(name=form["name"][:100], company=form["company_name"][:200],
                   email=form["email"], phone=form["phone"][:50],
                   topic=form["topic"][:50], message=form["message"]))
    db.commit()
    return render(request, "contact_done.html")


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


@app.get("/blog", response_class=HTMLResponse)
def blog_list(request: Request, page: int = 1, category: str = "", db: Session = Depends(get_db)):
    q = published_posts()
    if category:
        q = q.where(Post.category == category)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    pages = max(1, math.ceil(total / PER_PAGE))
    page = min(max(1, page), pages)
    posts = db.scalars(q.offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()
    return render(request, "blog_list.html", posts=posts, page=page, pages=pages,
                  category=category, total=total)


@app.get("/blog/{post_id}", response_class=HTMLResponse)
def blog_detail(request: Request, post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    is_public = post and post.status == "published" and post.published_at and post.published_at <= datetime.now()
    if not post or (not is_public and not request.session.get("user")):
        raise HTTPException(404)
    related = db.scalars(published_posts().where(Post.id != post.id).limit(3)).all()
    return render(request, "blog_detail.html", post=post, related=related, preview=not is_public)


@app.get("/images/{image_id}")
def image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        raise HTTPException(404)
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/feed.xml")
def feed(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    items = []
    for p in db.scalars(published_posts().limit(20)):
        items.append(
            f"<item><title>{xml_escape(p.title)}</title><link>{base}/blog/{p.id}</link>"
            f"<guid>{base}/blog/{p.id}</guid><category>{xml_escape(p.category)}</category>"
            f"<description>{xml_escape(p.excerpt)}</description>"
            f"<pubDate>{p.published_at.strftime('%a, %d %b %Y %H:%M:%S +0900')}</pubDate></item>")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
           f"<title>{xml_escape(content.COMPANY['name'])} ブログ</title><link>{base}/blog</link>"
           f"<description>電力・太陽光・蓄電池の最新情報</description>{''.join(items)}</channel></rss>")
    return Response(xml, media_type="application/rss+xml")


@app.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    paths = ["/", "/services", *[f"/services/{s}" for s in content.SERVICES],
             "/company", "/blog", "/contact", "/privacy"]
    paths += [f"/blog/{pid}" for pid in db.scalars(published_posts().with_only_columns(Post.id))]
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                    media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nDisallow: /admin\nSitemap: {str(request.base_url).rstrip('/')}/sitemap.xml\n"


# ── 管理画面 ─────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    bootstrap_admin_from_env(db)
    if not db.scalar(select(func.count(User.id))):
        return RedirectResponse("/admin/setup", status_code=303)
    return render(request, "admin/login.html", error=None)


@app.post("/admin/login", response_class=HTMLResponse)
def login(request: Request, db: Session = Depends(get_db), csrf: str = Form(""),
          username: str = Form(""), password: str = Form("")):
    check_csrf(request, csrf)
    u = db.scalar(select(User).where(User.username == username.strip()))
    if not u or not verify_password(password, u.password_hash):
        return render(request, "admin/login.html", error="ユーザー名またはパスワードが違います。",
                      status_code=401)
    request.session.clear()
    request.session["user"] = u.username
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/admin/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(func.count(User.id))):
        return RedirectResponse("/admin/login", status_code=303)
    return render(request, "admin/setup.html", error=None)


@app.post("/admin/setup", response_class=HTMLResponse)
def setup(request: Request, db: Session = Depends(get_db), csrf: str = Form(""),
          username: str = Form(""), password: str = Form(""), password2: str = Form("")):
    check_csrf(request, csrf)
    if db.scalar(select(func.count(User.id))):  # 最初の 1 人だけ作成できる
        return RedirectResponse("/admin/login", status_code=303)
    username = username.strip()
    error = None
    if not username or len(username) > 64:
        error = "ユーザー名を入力してください。"
    elif len(password) < 8:
        error = "パスワードは 8 文字以上にしてください。"
    elif password != password2:
        error = "確認用パスワードが一致しません。"
    if error:
        return render(request, "admin/setup.html", error=error, status_code=400)
    db.add(User(username=username, password_hash=hash_password(password)))
    db.commit()
    request.session["user"] = username
    flash(request, "管理者アカウントを作成しました。")
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, user: str = Depends(require_login), db: Session = Depends(get_db),
               status: str = ""):
    q = select(Post).order_by(Post.updated_at.desc())
    if status in ("draft", "published"):
        q = q.where(Post.status == status)
    posts = db.scalars(q).all()
    unread = db.scalar(select(func.count(Inquiry.id)).where(Inquiry.is_read == 0))
    return render(request, "admin/posts.html", posts=posts, unread=unread, status=status,
                  now_dt=datetime.now())


def _post_form_ctx(post: Post | None, **kw):
    return dict(post=post, categories=content.BLOG_CATEGORIES, **kw)


@app.get("/admin/posts/new", response_class=HTMLResponse)
def post_new(request: Request, user: str = Depends(require_login)):
    return render(request, "admin/post_form.html", **_post_form_ctx(None))


@app.get("/admin/posts/{post_id}", response_class=HTMLResponse)
def post_edit(request: Request, post_id: int, user: str = Depends(require_login),
              db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404)
    return render(request, "admin/post_form.html", **_post_form_ctx(post))


@app.post("/admin/posts/save")
async def post_save(
    request: Request,
    user: str = Depends(require_login),
    db: Session = Depends(get_db),
    csrf: str = Form(""),
    post_id: int = Form(0),
    title: str = Form(""),
    category: str = Form(""),
    excerpt: str = Form(""),
    body: str = Form(""),
    published_at: str = Form(""),
    action: str = Form("draft"),
    remove_eyecatch: str = Form(""),
    eyecatch: UploadFile | None = File(None),
):
    check_csrf(request, csrf)
    post = db.get(Post, post_id) if post_id else Post()
    if post is None:
        raise HTTPException(404)
    title = title.strip()
    if not title:
        return render(request, "admin/post_form.html",
                      **_post_form_ctx(post if post_id else None, error="タイトルを入力してください。",
                                       draft=dict(title=title, category=category, excerpt=excerpt, body=body)),
                      status_code=400)
    post.title = title[:200]
    post.category = category if category in content.BLOG_CATEGORIES else content.BLOG_CATEGORIES[0]
    # 概要文が空欄、または前回の自動生成のままなら、本文から作り直す
    auto_prev = _auto_excerpt(post.body or "")[:300]
    excerpt = excerpt.strip()
    post.excerpt = (excerpt if excerpt and excerpt != auto_prev else _auto_excerpt(body))[:300]
    post.body = body
    if eyecatch and eyecatch.filename:
        post.eyecatch_id = (await save_image(db, eyecatch)).id
    elif remove_eyecatch:
        post.eyecatch_id = None
    if action == "publish":
        post.status = "published"
        try:
            post.published_at = datetime.fromisoformat(published_at) if published_at else None
        except ValueError:
            post.published_at = None
        post.published_at = post.published_at or datetime.now().replace(microsecond=0)
    elif action == "draft":
        post.status = "draft"
    if not post_id:
        db.add(post)
    db.commit()
    flash(request, "公開しました。" if post.status == "published" else "下書き保存しました。")
    return RedirectResponse(f"/admin/posts/{post.id}", status_code=303)


def _auto_excerpt(body: str) -> str:
    import re
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body or "")
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"[#>*_`|\-]+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:120] + ("…" if len(plain) > 120 else "")


@app.post("/admin/posts/{post_id}/delete")
def post_delete(request: Request, post_id: int, user: str = Depends(require_login),
                db: Session = Depends(get_db), csrf: str = Form("")):
    check_csrf(request, csrf)
    post = db.get(Post, post_id)
    if post:
        db.delete(post)
        db.commit()
    flash(request, "記事を削除しました。")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/images")
async def image_upload(request: Request, user: str = Depends(require_login),
                       db: Session = Depends(get_db), csrf: str = Form(""),
                       file: UploadFile = File(...)):
    check_csrf(request, csrf)
    img = await save_image(db, file)
    db.commit()
    return JSONResponse({"url": f"/images/{img.id}", "id": img.id})


@app.post("/admin/preview", response_class=HTMLResponse)
def preview(request: Request, user: str = Depends(require_login), csrf: str = Form(""),
            body: str = Form("")):
    check_csrf(request, csrf)
    return HTMLResponse(render_markdown(body))


@app.get("/admin/inquiries", response_class=HTMLResponse)
def inquiries(request: Request, user: str = Depends(require_login), db: Session = Depends(get_db)):
    items = db.scalars(select(Inquiry).order_by(Inquiry.created_at.desc())).all()
    return render(request, "admin/inquiries.html", items=items)


@app.post("/admin/inquiries/{iid}/read")
def inquiry_read(request: Request, iid: int, user: str = Depends(require_login),
                 db: Session = Depends(get_db), csrf: str = Form("")):
    check_csrf(request, csrf)
    item = db.get(Inquiry, iid)
    if item:
        item.is_read = 0 if item.is_read else 1
        db.commit()
    return RedirectResponse("/admin/inquiries", status_code=303)


@app.get("/admin/password", response_class=HTMLResponse)
def password_form(request: Request, user: str = Depends(require_login)):
    return render(request, "admin/password.html", error=None)


@app.post("/admin/password", response_class=HTMLResponse)
def password_change(request: Request, user: str = Depends(require_login),
                    db: Session = Depends(get_db), csrf: str = Form(""), current: str = Form(""),
                    password: str = Form(""), password2: str = Form("")):
    check_csrf(request, csrf)
    u = db.scalar(select(User).where(User.username == user))
    error = None
    if not u or not verify_password(current, u.password_hash):
        error = "現在のパスワードが違います。"
    elif len(password) < 8:
        error = "新しいパスワードは 8 文字以上にしてください。"
    elif password != password2:
        error = "確認用パスワードが一致しません。"
    if error:
        return render(request, "admin/password.html", error=error, status_code=400)
    u.password_hash = hash_password(password)
    db.commit()
    flash(request, "パスワードを変更しました。")
    return RedirectResponse("/admin", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith(("/mcp", "/static", "/images", "/admin/images")):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return render(request, "error.html", code=exc.status_code, detail=exc.detail,
                  status_code=exc.status_code)


# ── MCP（AIツール）は「おまけ」。ライブラリ非互換等で失敗しても
#    Web アプリは止めない（deploy のヘルスチェックを守るため）。
#    MCP は認証なしで公開されるため、読み取り専用のツールだけを置く。 ──
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("toyo-bench-mark")

    @mcp.tool()
    def db_now() -> str:
        """データベースの現在時刻を返す（DB接続の確認用）。"""
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT now()")).scalar())

    @mcp.tool()
    def list_blog_posts(limit: int = 10) -> list[dict]:
        """公開中のブログ記事を新しい順に返す。"""
        ensure_tables()
        with SessionLocal() as db:
            return [{"id": p.id, "title": p.title, "category": p.category,
                     "published_at": p.published_at.isoformat(), "url": f"/blog/{p.id}"}
                    for p in db.scalars(published_posts().limit(max(1, min(limit, 50))))]

    # sse_app() に mount_path は渡さないこと。mcp 1.9.0 以降は
    # ASGI の root_path（= マウント先の "/mcp"）が自動で前置される。
    # 渡すと /mcp/mcp/messages/ と二重になり、AI 側から接続できない。
    app.mount("/mcp", mcp.sse_app())
except Exception as _e:  # noqa: BLE001
    log.warning("MCP を無効化しました（Web アプリは稼働）: %s", _e)
