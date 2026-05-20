#!/usr/bin/env python3
"""
openclaw-peer-discovery Registry Server — 轻量级中心注册表。

所有 OpenClaw 实例可通过此服务器互相发现（WAN / 跨网络）。

启动:
  python3 registry_server.py --port 8080

API 端点:
  POST /api/v1/register   — 注册/续期实例
  GET  /api/v1/peers      — 获取所有在线实例
  GET  /api/v1/peers/:id  — 获取指定实例详情
  GET  /health            — 健康检查

环境变量:
  REGISTRY_AUTH_TOKEN     — 可选，设置后注册需要 Bearer token
  REGISTRY_DATA_DIR       — 持久化路径 (默认: ./data/)
"""

import json
import os
import sys
import time
import hashlib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

VERSION = "1"
API_PATH = f"/api/v{os.environ.get('API_VERSION', VERSION)}"
DATA_DIR = os.environ.get("REGISTRY_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
AUTH_TOKEN = os.environ.get("REGISTRY_AUTH_TOKEN", "")
os.makedirs(DATA_DIR, exist_ok=True)

# In-memory store — peers.json for persistence
PEERS_FILE = os.path.join(DATA_DIR, "peers.json")
peers: dict[str, dict] = {}  # id -> peer record
peers_lock = threading.Lock()


def load_peers():
    global peers
    if os.path.exists(PEERS_FILE):
        try:
            with open(PEERS_FILE) as f:
                peers = json.load(f)
        except Exception:
            peers = {}


def save_peers():
    with open(PEERS_FILE, "w") as f:
        json.dump(peers, f, indent=2, ensure_ascii=False)


def generate_id(gateway_url: str, name: str) -> str:
    raw = f"{gateway_url}|{name}|{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def prune_expired():
    """Remove expired registrations."""
    now = time.time()
    expired = [pid for pid, p in peers.items() if p.get("expiresAt", 0) < now]
    for pid in expired:
        del peers[pid]
    if expired:
        save_peers()


class RegistryHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[registry] {args[0]} {args[1]} {args[2]}\n")

    def _send(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _check_auth(self):
        if not AUTH_TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {AUTH_TOKEN}"

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            return self._send({
                "status": "ok",
                "uptime": time.time() - start_time,
                "peersCount": len(peers),
            })

        if path == f"{API_PATH}/peers":
            prune_expired()
            with peers_lock:
                peer_list = list(peers.values())
            return self._send({"peers": peer_list, "count": len(peer_list)})

        # /api/v1/peers/<id>
        if path.startswith(f"{API_PATH}/peers/"):
            peer_id = path.split("/")[-1]
            with peers_lock:
                p = peers.get(peer_id)
            if not p:
                return self._send({"error": "not_found"}, 404)
            return self._send(p)

        self._send({"error": "not_found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path != f"{API_PATH}/register":
            return self._send({"error": "not_found"}, 404)

        if not self._check_auth():
            return self._send({"error": "unauthorized"}, 401)

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode()) if length else {}

        gateway_url = body.get("gatewayUrl")
        if not gateway_url:
            return self._send({"error": "gatewayUrl required"}, 400)

        name = body.get("name", "unknown")
        pid = generate_id(gateway_url, name)
        now = time.time()
        ttl = max(60, min(86400, body.get("ttl", 300)))
        record = {
            "id": pid,
            "name": name,
            "gatewayUrl": gateway_url,
            "hostname": body.get("hostname", ""),
            "port": body.get("port", 18789),
            "localIps": body.get("localIps", []),
            "tags": body.get("tags", []),
            "publicKey": body.get("publicKey", ""),
            "registeredAt": now,
            "expiresAt": now + ttl,
            "ttl": ttl,
        }

        with peers_lock:
            peers[pid] = record
            save_peers()
            peer_list = list(peers.values())

        self._send({"status": "ok", "id": pid, "peers": peer_list})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith(f"{API_PATH}/peers/"):
            if not self._check_auth():
                return self._send({"error": "unauthorized"}, 401)
            peer_id = path.split("/")[-1]
            with peers_lock:
                if peer_id in peers:
                    del peers[peer_id]
                    save_peers()
                    return self._send({"status": "deleted", "id": peer_id})
            return self._send({"error": "not_found"}, 404)
        self._send({"error": "not_found"}, 404)


def start_cleanup_thread(interval=60):
    def loop():
        while True:
            time.sleep(interval)
            prune_expired()
    t = threading.Thread(target=loop, daemon=True)
    t.start()


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8080

    load_peers()
    start_cleanup_thread()

    start_time = time.time()
    server = HTTPServer(("0.0.0.0", port), RegistryHandler)

    print(f"🦞 OpenClaw Peer Registry Server", file=sys.stderr)
    print(f"   API:      http://0.0.0.0:{port}{API_PATH}", file=sys.stderr)
    print(f"   Peers:    {len(peers)} 个已加载", file=sys.stderr)
    print(f"   Auth:     {'🔒 已启用' if AUTH_TOKEN else '🔓 未设置'}", file=sys.stderr)
    print(f"   Data:     {PEERS_FILE}", file=sys.stderr)
    print(f"   按 Ctrl+C 停止\n", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭...", file=sys.stderr)
        server.shutdown()
