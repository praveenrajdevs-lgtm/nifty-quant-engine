"""
Clean Backend API & Static Asset Server for Antigravity Quant Engine
Serves:
  - GET  /api/dashboard       -> Full 2-Year (110-Week, 518-Session) Multi-Strategy Benchmark & Live Telemetry
  - GET  /api/trades          -> Filterable Trade Ledger (?strategy=combined|pr_sundar|institutional|rolling_straddle|baseline)
  - POST /api/recompute       -> Re-runs the 2-Year Backtest Engine and refreshes JSON cache
  - GET  /api/status          -> Legacy status endpoint for CLI/daemon compatibility
  - Static Frontend Assets    -> Serves built Vite + shadcn/ui Light-Theme app from frontend/dist (if built)
"""
import http.server
import json
import mimetypes
import os
import socketserver
import sqlite3
import urllib.parse
from datetime import datetime
from trade_db import DB_PATH, get_live_state
from live_feed import get_live_nifty_spot
from run_2year_upstox_backtest import OUTPUT_JSON, run_2year_suite

PORT = int(os.environ.get("PORT", "8080"))
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
PR_SUNDAR_JSON = os.path.join(os.path.dirname(__file__), "data_cache", "pr_sundar_brain.json")
PR_SUNDAR_DB = os.path.join(os.path.dirname(__file__), "data_cache", "pr_sundar_brain.db")


def load_dashboard_payload() -> dict:
    if not os.path.exists(OUTPUT_JSON):
        return run_2year_suite()
    with open(OUTPUT_JSON, "r") as f:
        return json.load(f)


def load_pr_sundar_brain() -> dict:
    if not os.path.exists(PR_SUNDAR_JSON):
        return {"error": "Brain index not yet generated", "videos": [], "synthesized_playbook": []}
    with open(PR_SUNDAR_JSON, "r") as f:
        return json.load(f)


def search_pr_sundar_db(q_str: str, category: str = "all", limit: int = 40) -> list:
    if not os.path.exists(PR_SUNDAR_DB):
        return []
    conn = sqlite3.connect(PR_SUNDAR_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    q_clean = (q_str or "").strip()
    cat_clean = (category or "all").strip()

    rows = []
    if q_clean:
        like_pat = f"%{q_clean}%"
        sql = """
            SELECT video_id, title, publish_date, published_text, duration, views,
                   categories, description, word_count, transcript, key_quotes_json
            FROM videos
            WHERE (title LIKE ? OR transcript LIKE ? OR description LIKE ? OR categories LIKE ?)
        """
        params = [like_pat, like_pat, like_pat, like_pat]
        if cat_clean and cat_clean != "all":
            sql += " AND categories LIKE ?"
            params.append(f"%{cat_clean}%")
        sql += " ORDER BY CASE WHEN title LIKE ? THEN 1 ELSE 0 END DESC, word_count > 0 DESC, views DESC LIMIT ?"
        params.extend([like_pat, limit])
        rows = cur.execute(sql, params).fetchall()
    else:
        sql = """
            SELECT video_id, title, publish_date, published_text, duration, views,
                   categories, description, word_count, transcript, key_quotes_json
            FROM videos
            WHERE word_count > 0
        """
        params = []
        if cat_clean and cat_clean != "all":
            sql += " AND categories LIKE ?"
            params.append(f"%{cat_clean}%")
        sql += " ORDER BY views DESC LIMIT ?"
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()

    results = []
    for r in rows:
        tr = r["transcript"] or ""
        preview = tr[:650]
        if q_clean and q_clean.lower() in tr.lower():
            idx = tr.lower().find(q_clean.lower())
            start = max(0, idx - 180)
            end = min(len(tr), idx + 420)
            preview = ("..." if start > 0 else "") + tr[start:end] + ("..." if end < len(tr) else "")
        results.append({
            "video_id": r["video_id"],
            "url": f"https://www.youtube.com/watch?v={r['video_id']}",
            "title": r["title"] or f"P R Sundar Video ({r['video_id']})",
            "publish_date": r["publish_date"] or r["published_text"] or "",
            "duration": r["duration"] or "",
            "views": r["views"] or 0,
            "categories": r["categories"].split(",") if r["categories"] else [],
            "word_count": r["word_count"] or 0,
            "quotes": json.loads(r["key_quotes_json"] or "[]"),
            "transcript_preview": preview,
        })
    conn.close()
    return results


class QuantAPIHandler(http.server.SimpleHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/recompute":
            payload = run_2year_suite()
            self._send_json({"status": "ok", "generated_at": payload["generated_at"]})
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/dashboard":
            data = load_dashboard_payload()
            live_spot = get_live_nifty_spot()
            live_state = get_live_state()
            token_file = os.path.expanduser("~/SoftKnack/platform/keys/upstox_token")
            token_mtime = None
            if os.path.exists(token_file):
                token_mtime = datetime.fromtimestamp(os.path.getmtime(token_file)).strftime("%Y-%m-%d %H:%M IST")

            self._send_json({
                **data,
                "live_spot": live_spot,
                "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
                "upstox_token_updated_at": token_mtime,
                "live_state": live_state,
            })
            return

        if path == "/api/trades":
            data = load_dashboard_payload()
            strat_key = query.get("strategy", ["combined"])[0]
            limit = int(query.get("limit", ["150"])[0])
            strat = data.get("strategies", {}).get(strat_key) or data["strategies"]["combined"]
            self._send_json({
                "strategy": strat_key,
                "title": strat["title"],
                "trades": strat["recent_trades"][:limit],
            })
            return

        if path == "/api/pr-sundar-brain":
            self._send_json(load_pr_sundar_brain())
            return

        if path == "/api/pr-sundar-search":
            q_str = query.get("q", [""])[0]
            cat_str = query.get("category", ["all"])[0]
            limit = int(query.get("limit", ["40"])[0])
            self._send_json({
                "query": q_str,
                "category": cat_str,
                "results": search_pr_sundar_db(q_str, cat_str, limit),
            })
            return

        if path == "/api/status":
            data = load_dashboard_payload()
            comb = data["strategies"]["combined"]
            live_spot = get_live_nifty_spot()
            self._send_json({
                "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
                "spot": live_spot,
                "current_capital": comb["ending_capital"],
                "net_profit": comb["net_pnl"],
                "return_pct": comb["return_pct"],
                "total_trades": comb["total_trades"],
                "wins": comb["wins"],
                "losses": comb["losses"],
                "win_rate": comb["win_rate"],
                "gross_pnl": comb["gross_pnl"],
                "charges": comb["charges"],
                "equity_points": [pt["equity"] for pt in comb["equity_curve"]],
                "trades": comb["recent_trades"][:50],
                "live_state": get_live_state(),
            })
            return

        # Serve static frontend from frontend/dist if available
        if os.path.isdir(FRONTEND_DIST):
            rel_path = path.lstrip("/") or "index.html"
            candidate = os.path.join(FRONTEND_DIST, rel_path)
            if not os.path.isfile(candidate):
                candidate = os.path.join(FRONTEND_DIST, "index.html")
            if os.path.isfile(candidate):
                ctype, _ = mimetypes.guess_type(candidate)
                with open(candidate, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype or "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        self._send_json({"message": "Antigravity Quant API Server Running. Use /api/dashboard or open Frontend on http://localhost:5173"}, status=200)

    def log_message(self, fmt, *args):
        pass


def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), QuantAPIHandler) as httpd:
        print(f"Clean Quant Backend API Server running at: http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    start_server()
