# toyo-bench-mark — DB付き Web アプリ + MCP サーバー（両方入り）
# FastAPI で Web ページ(/)と MCP(/mcp/sse)を提供し、PostgreSQL も使えます。
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@db:5432/toyo_bench_mark")
# pool_pre_ping=True で接続は使う時まで遅延（起動時にDB未起動でも落ちない）
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

# ── 通常の Web アプリ（これは必ず起動する） ──
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>🗄️ toyo-bench-mark</h1><p>DB付き Web アプリ + MCP（接続先: /mcp/sse）が動作中です。</p>"

@app.get("/health")
def health():
    return {"ok": True}

# ── MCP（AIツール）は「おまけ」。ライブラリ非互換等で失敗しても
#    Web アプリは止めない（deploy のヘルスチェックを守るため）。 ──
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("toyo-bench-mark")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """2つの整数を足し算して返す（サンプル）。"""
        return a + b

    @mcp.tool()
    def db_now() -> str:
        """データベースの現在時刻を返す（DB接続のサンプル）。"""
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT now()")).scalar())

    # sse_app() に mount_path は渡さないこと。mcp 1.9.0 以降は
    # ASGI の root_path（= マウント先の "/mcp"）が自動で前置される。
    # 渡すと /mcp/mcp/messages/ と二重になり、AI 側から接続できない。
    app.mount("/mcp", mcp.sse_app())
except Exception as _e:  # noqa: BLE001
    import logging
    logging.getLogger("uvicorn.error").warning(
        "MCP を無効化しました（Web アプリは稼働）: %s", _e)
