"""
Autonomous Trading System Web Server & Real-Time Dashboard
Pure standard Python HTTP server (zero external dependencies).
Serves real-time dark-mode quant terminal on http://localhost:8080.
"""
import http.server
import socketserver
import json
import sqlite3
import os
from datetime import datetime
from trade_db import DB_PATH
from live_feed import get_live_nifty_spot

PORT = 8080

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity Quant Terminal | NIFTY Straddle</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0A0E17;
            --surface: #121826;
            --surface-hover: #182235;
            --border: #1F293D;
            --text-main: #F1F5F9;
            --text-muted: #94A3B8;
            --green: #10B981;
            --green-glow: rgba(16, 185, 129, 0.15);
            --red: #F43F5E;
            --red-glow: rgba(244, 63, 94, 0.15);
            --accent: #3B82F6;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            padding: 24px;
        }

        .mono { font-family: 'JetBrains Mono', monospace; }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 16px;
        }

        .brand-title {
            font-size: 20px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 12px;
            letter-spacing: -0.5px;
        }

        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            background: var(--green-glow);
            color: var(--green);
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 4px 10px;
            border-radius: 999px;
        }

        .pulse-dot {
            width: 7px;
            height: 7px;
            background: var(--green);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--green);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(1.2); }
            100% { opacity: 1; transform: scale(1); }
        }

        .meta-group {
            display: flex;
            align-items: center;
            gap: 20px;
            font-size: 13px;
        }

        .meta-item {
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .meta-val {
            color: var(--text-main);
            font-weight: 600;
        }

        .grid-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            transition: border-color 0.2s;
        }
        .stat-card:hover { border-color: rgba(59, 130, 246, 0.4); }

        .stat-label {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .stat-num {
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }

        .stat-sub {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 6px;
        }

        .positive { color: var(--green); }
        .negative { color: var(--red); }

        .dashboard-body {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }
        @media (max-width: 1024px) {
            .dashboard-body { grid-template-columns: 1fr; }
        }

        .section-box {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .section-title {
            font-size: 15px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* SVG Chart Styles */
        .chart-container {
            width: 100%;
            height: 220px;
            position: relative;
        }

        svg.equity-chart {
            width: 100%;
            height: 100%;
            overflow: visible;
        }

        /* Active Position Widget */
        .pos-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 14px;
        }

        .leg-card {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px;
        }

        .leg-title {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .leg-val {
            font-size: 18px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .leg-status {
            font-size: 11px;
            margin-top: 6px;
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
        }

        /* Table */
        .table-box {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }

        th {
            background: rgba(15, 23, 42, 0.8);
            color: var(--text-muted);
            padding: 14px 18px;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border);
        }

        td {
            padding: 14px 18px;
            border-bottom: 1px solid rgba(31, 41, 61, 0.5);
            font-family: 'JetBrains Mono', monospace;
        }

        tr:hover td { background: var(--surface-hover); }

        .tag-win {
            background: var(--green-glow);
            color: var(--green);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }

        .tag-loss {
            background: var(--red-glow);
            color: var(--red);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
    </style>
</head>
<body>

    <header>
        <div class="brand-title">
            <span>⚡ Antigravity Quant Terminal</span>
            <span class="badge-live"><span class="pulse-dot"></span> Daemon Active</span>
        </div>
        <div class="meta-group">
            <div class="meta-item">NIFTY 50 SPOT: <span id="nifty-spot" class="meta-val mono">--</span></div>
            <div class="meta-item">SERVER TIME: <span id="server-time" class="meta-val mono">--</span></div>
            <div class="meta-item">STATUS: <span id="daemon-state" class="meta-val positive">Autonomous 24/7</span></div>
        </div>
    </header>

    <div class="grid-stats">
        <div class="stat-card">
            <div class="stat-label">Compounded Capital</div>
            <div id="stat-capital" class="stat-num mono positive">₹--</div>
            <div class="stat-sub">Starting Capital: ₹50,000.00</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Pure Net Profit</div>
            <div id="stat-profit" class="stat-num mono positive">+₹--</div>
            <div class="stat-sub">After all taxes & brokerage</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">1-Month Return</div>
            <div id="stat-return" class="stat-num mono positive">+--%</div>
            <div class="stat-sub">Compounded monthly alpha</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Win Rate (22 Days)</div>
            <div id="stat-winrate" class="stat-num mono">--%</div>
            <div id="stat-ratio" class="stat-sub">-- Wins / -- Losses</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Taxes & Brokerage Paid</div>
            <div id="stat-charges" class="stat-num mono negative">₹--</div>
            <div class="stat-sub">Zerodha + SEBI STT + GST</div>
        </div>
    </div>

    <div class="dashboard-body">
        <div class="section-box">
            <div class="section-header">
                <div class="section-title">📈 Compounded Equity Growth (₹50,000 → ₹58,264)</div>
                <div style="font-size: 12px; color: var(--text-muted);">Last 22 Sessions</div>
            </div>
            <div class="chart-container" id="chart-box">
                <svg class="equity-chart" id="svg-chart" viewBox="0 0 700 200" preserveAspectRatio="none">
                    <!-- Dynamic chart rendered here -->
                </svg>
            </div>
        </div>

        <div class="section-box">
            <div class="section-header">
                <div class="section-title">🎯 Active Straddle Engine</div>
                <div class="badge-live" style="background: rgba(59,130,246,0.15); color: #60A5FA; border-color: rgba(59,130,246,0.3);">30% SL + BE</div>
            </div>
            <div style="font-size: 13px; color: var(--text-muted); line-height: 1.5;">
                Strategy: <strong>09:25 AM NIFTY Short Straddle</strong><br>
                Mode: <span class="positive">Automated Background Execution</span><br>
                Next Trigger Window: <strong>09:25:00 IST</strong>
            </div>

            <div class="pos-grid">
                <div class="leg-card">
                    <div class="leg-title">CALL (CE) LEG</div>
                    <div class="leg-val" id="disp-ce-val">ATM Leg</div>
                    <div class="leg-status tag-win" id="disp-ce-status">SL: +30%</div>
                </div>
                <div class="leg-card">
                    <div class="leg-title">PUT (PE) LEG</div>
                    <div class="leg-val" id="disp-pe-val">ATM Leg</div>
                    <div class="leg-status tag-win" id="disp-pe-status">SL: +30% / BE</div>
                </div>
            </div>

            <div style="margin-top: 16px; padding: 12px; background: rgba(15,23,42,0.4); border-radius: 8px; font-size: 12px; color: var(--text-muted);">
                🛡️ <strong>Quant Protection Active:</strong> If one leg stops out at 30%, the remaining leg automatically trails to Breakeven (0 loss).
            </div>
        </div>
    </div>

    <div class="table-box">
        <div style="padding: 18px 20px; font-size: 15px; font-weight: 600; border-bottom: 1px solid var(--border);">
            📋 Verified Daily Audit Journal (SQLite Store)
        </div>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>ATM Strike</th>
                    <th>Call Leg (CE)</th>
                    <th>Put Leg (PE)</th>
                    <th>Gross P&L</th>
                    <th>Taxes & Fees</th>
                    <th>Net In-Pocket P&L</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="trade-rows">
                <!-- Dynamically loaded rows -->
            </tbody>
        </table>
    </div>

    <script>
        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                document.getElementById('nifty-spot').innerText = data.spot.toFixed(2);
                document.getElementById('server-time').innerText = data.server_time;

                // Stats
                document.getElementById('stat-capital').innerText = '₹' + data.current_capital.toLocaleString('en-IN', {minimumFractionDigits: 1});
                document.getElementById('stat-profit').innerText = '+₹' + data.net_profit.toLocaleString('en-IN', {minimumFractionDigits: 1});
                document.getElementById('stat-return').innerText = '+' + data.return_pct.toFixed(1) + '%';
                document.getElementById('stat-winrate').innerText = data.win_rate.toFixed(1) + '%';
                document.getElementById('stat-ratio').innerText = data.wins + ' Wins / ' + data.losses + ' Losses';
                document.getElementById('stat-charges').innerText = '₹' + data.charges.toLocaleString('en-IN', {minimumFractionDigits: 1});

                // Populate Trade Table
                const tbody = document.getElementById('trade-rows');
                tbody.innerHTML = '';
                data.trades.forEach(t => {
                    const tr = document.createElement('tr');
                    const isWin = t.net_pnl > 0;
                    tr.innerHTML = `
                        <td>${t.date}</td>
                        <td>${t.strike}</td>
                        <td><span style="color: ${t.ce_status.includes('SL') ? 'var(--red)' : 'var(--green)'};">${t.ce_status}</span></td>
                        <td><span style="color: ${t.pe_status.includes('SL') ? 'var(--red)' : 'var(--green)'};">${t.pe_status}</span></td>
                        <td style="color: ${t.gross_pnl >= 0 ? 'var(--green)' : 'var(--red)'};">₹${t.gross_pnl > 0 ? '+' : ''}${t.gross_pnl.toFixed(1)}</td>
                        <td style="color: var(--text-muted);">₹${t.charges.toFixed(1)}</td>
                        <td style="font-weight: 700; color: ${isWin ? 'var(--green)' : 'var(--red)'};">₹${isWin ? '+' : ''}${t.net_pnl.toFixed(1)}</td>
                        <td><span class="${isWin ? 'tag-win' : 'tag-loss'}">${isWin ? 'PROFIT' : 'LOSS'}</span></td>
                    `;
                    tbody.appendChild(tr);
                });

                // Render Equity SVG Chart
                renderChart(data.equity_points);

            } catch (e) {
                console.error("Dashboard update failed:", e);
            }
        }

        function renderChart(points) {
            if (!points || points.length < 2) return;
            const svg = document.getElementById('svg-chart');
            const W = 700, H = 200;
            const minVal = Math.min(...points) - 500;
            const maxVal = Math.max(...points) + 500;

            const coords = points.map((val, idx) => {
                const x = (idx / (points.length - 1)) * (W - 40) + 20;
                const y = H - 30 - ((val - minVal) / (maxVal - minVal)) * (H - 50);
                return {x, y};
            });

            let pathD = `M ${coords[0].x} ${coords[0].y}`;
            coords.slice(1).forEach(pt => { pathD += ` L ${pt.x} ${pt.y}`; });

            let areaD = `${pathD} L ${coords[coords.length-1].x} ${H} L ${coords[0].x} ${H} Z`;

            svg.innerHTML = `
                <defs>
                    <linearGradient id="gradArea" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#10B981" stop-opacity="0.25"/>
                        <stop offset="100%" stop-color="#10B981" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>
                <path d="${areaD}" fill="url(#gradArea)"/>
                <path d="${pathD}" fill="none" stroke="#10B981" stroke-width="2.5" stroke-linecap="round"/>
                ${coords.map(pt => `<circle cx="${pt.x}" cy="${pt.y}" r="3" fill="#10B981"/>`).join('')}
            `;
        }

        updateDashboard();
        setInterval(updateDashboard, 4000); // Poll every 4 seconds
    </script>
</body>
</html>
"""

class QuantHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Query SQLite database for live status
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
            SELECT trade_date, atm_strike, ce_status, pe_status, gross_pnl, charges, net_pnl, lots
            FROM daily_trades ORDER BY trade_date ASC
            """)
            rows = cur.fetchall()
            conn.close()

            capital = 50000.0
            equity_points = [capital]
            trades_list = []
            gross_sum = 0.0
            charges_sum = 0.0
            net_sum = 0.0
            wins = 0

            for r in rows:
                net_p = r[6]
                gross_p = r[4]
                chg = r[5]
                capital += net_p
                equity_points.append(capital)
                gross_sum += gross_p
                charges_sum += chg
                net_sum += net_p
                if net_p > 0:
                    wins += 1

                trades_list.append({
                    "date": r[0],
                    "strike": r[1],
                    "ce_status": r[2],
                    "pe_status": r[3],
                    "gross_pnl": gross_p,
                    "charges": chg,
                    "net_pnl": net_p,
                    "lots": r[7]
                })

            trades_list.reverse()  # Latest first for table
            total_t = len(rows)
            win_rate = (wins / total_t * 100.0) if total_t > 0 else 0.0
            return_pct = ((capital - 50000.0) / 50000.0 * 100.0)

            live_spot = get_live_nifty_spot()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

            response_payload = {
                "server_time": now_str,
                "spot": live_spot,
                "current_capital": round(capital, 2),
                "net_profit": round(net_sum, 2),
                "return_pct": round(return_pct, 1),
                "total_trades": total_t,
                "wins": wins,
                "losses": total_t - wins,
                "win_rate": round(win_rate, 1),
                "gross_pnl": round(gross_sum, 2),
                "charges": round(charges_sum, 2),
                "equity_points": equity_points,
                "trades": trades_list
            }
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), QuantHandler) as httpd:
        print(f"Quant Terminal Dashboard live at: http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    start_server()
