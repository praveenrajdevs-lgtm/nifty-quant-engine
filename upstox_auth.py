"""
Upstox OAuth Login (Zero Dependencies)
Opens the Upstox login page, catches the redirect on 127.0.0.1:5055 and saves
the day's access token. Upstox tokens expire every morning ~03:30 IST, so run daily.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

KEYS_FILE = os.environ.get("UPSTOX_KEYS_FILE", os.path.expanduser("~/SoftKnack/platform/keys/upstox"))
TOKEN_FILE = os.path.join(os.path.dirname(KEYS_FILE), "upstox_token")
# Upstox app redirect URI is registered as http://127.0.0.1:5000/callback
# Binding specifically to 127.0.0.1:5000 takes precedence over macOS wildcard *:5000
REDIRECT_PORT = 5000
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
API = "https://api.upstox.com/v2"
# Browser agent: API hosts often block urllib's default "Python-urllib" agent
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def send(req: urllib.request.Request) -> dict:
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Upstox {e.code} on {req.full_url.split('?')[0]}: {e.read().decode('utf-8', 'replace')}") from None


def load_keys() -> dict:
    keys = {}
    with open(KEYS_FILE) as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def load_token() -> str:
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def api_get(path: str, params: dict = None) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {load_token()}",
    })
    return send(req)


def exchange_code(code: str, keys: dict) -> str:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": keys["UPSTOX_API_KEY"],
        "client_secret": keys["UPSTOX_API_SECRET"],
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(f"{API}/login/authorization/token", data=body, headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    return send(req)["access_token"]


def login():
    keys = load_keys()
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            captured["code"] = query.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Upstox login received. You can close this tab.".encode())

        def log_message(self, *args):
            pass

    auth_url = f"{API}/login/authorization/dialog?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": keys["UPSTOX_API_KEY"],
        "redirect_uri": REDIRECT_URI,
    })
    print(f"Opening Upstox login:\n{auth_url}")
    webbrowser.open(auth_url)

    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    while not captured.get("code"):
        server.handle_request()
    server.server_close()

    token = exchange_code(captured["code"], keys)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    os.chmod(TOKEN_FILE, 0o600)
    print(f"Access token saved to {TOKEN_FILE}")

    # Proves Plus is active: expired-contract expiries only come back on Upstox Plus
    expiries = api_get("/expired-instruments/expiries", {"instrument_key": "NSE_INDEX|Nifty 50"})
    dates = expiries.get("data", [])
    print(f"Expired NIFTY expiries available: {len(dates)} (oldest {dates[0] if dates else '-'}, latest {dates[-1] if dates else '-'})")


if __name__ == "__main__":
    login()
