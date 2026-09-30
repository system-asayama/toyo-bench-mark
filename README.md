# toyo-bench-mark（DB付き Web アプリ + MCP サーバー）

1つの Python アプリ（FastAPI）で、Web ページ・PostgreSQL・
AI から使えるツール（MCP）の全部を提供します。

## 構成
- `web` … FastAPI（Web: `/`、MCP: `/mcp/sse`、内部 8000 番）
- `db`  … PostgreSQL（データ保存先）

## デプロイ
「環境別デプロイ設定」→「自動セットアップを実行」で本番反映されます。

## Web / MCP
- Web: `https://<あなたのドメイン>/`
- MCP: `https://<あなたのドメイン>/mcp/sse` を Claude Desktop に登録
- `db_now` ツールは DB に接続して現在時刻を返すサンプルです。
  `@mcp.tool()` を足せば、DB を読み書きするツールを自由に増やせます。
