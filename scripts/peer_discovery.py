#!/usr/bin/env python3
"""
openclaw-peer-discovery — 发现同一网络（LAN）或注册表上的其他 OpenClaw 实例。

功能：
  1) publish  — 将本机 OpenClaw Gateway 广播到局域网（mDNS）
  2) discover — 扫描局域网，发现其他 OpenClaw 实例
  3) register — 向远程注册表注册本机信息（WAN 发现）
  4) query    — 从远程注册表查询所有已注册的 OpenClaw 实例

输出格式（stdout）：JSON lines (每行一个 JSON 对象)
  发现事件：{"type":"discovered","name":"...","host":"...","port":...,"gatewayUrl":"...","ipVersions":[...]}
  注册响应：{"type":"registered","id":"...","peers":[...]}

用法示例：
  # 广播本机（前台运行）
  python3 peer_discovery.py publish --name "Office-Gateway" --port 18789

  # 扫描局域网 10 秒
  python3 peer_discovery.py discover --timeout 10

  # 注册到远程注册表
  python3 peer_discovery.py register --registry http://hub.example.com:8080 \\
    --name "Home-Gateway" --gateway-url "http://192.168.1.100:18789"

  # 查询注册表
  python3 peer_discovery.py query --registry http://hub.example.com:8080
"""

import argparse
import json
import os
import platform
import signal
import socket
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------
def info(msg):
    print(json.dumps({"level": "info", "msg": msg}), file=sys.stderr)

def error(msg):
    print(json.dumps({"level": "error", "msg": msg}), file=sys.stderr)

def emit(record):
    """Write a JSON line to stdout — the agent reads this."""
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Helper: get local IPs
# ---------------------------------------------------------------------------
def get_local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    # Also enumerate interfaces
    try:
        import subprocess
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            ips.extend(r.stdout.strip().split())
    except Exception:
        pass
    return ips or ["127.0.0.1"]


# ---------------------------------------------------------------------------
# Mode 1: Publish (mDNS broadcast)
# ---------------------------------------------------------------------------
def cmd_publish(args):
    """Broadcast this gateway via mDNS so other OpenClaw can find it."""
    service_type = "_openclaw-gateway._tcp"
    service_name = args.name or f"OpenClaw-{platform.node()}"
    port = args.port

    info(f"正在广播 mDNS 服务: {service_type}")
    info(f"  服务名: {service_name}")
    info(f"  端口:   {port}")
    info(f"  TXT 记录: gatewayUrl={args.gateway_url or 'auto'}, " +
          f"hostname={platform.node()}, version=1")
    info("按 Ctrl+C 停止广播\n")

    # Method A: Avahi CLI (Linux)
    if args.method == "avahi":
        import subprocess
        txt = [
            f"gatewayUrl={args.gateway_url or 'auto'}",
            f"hostname={platform.node()}",
            "version=1",
        ]
        cmd = [
            "avahi-publish", "-s", service_name, service_type,
            str(port), *[f"--sub={t}" for t in txt],
        ]
        os.execvp("avahi-publish", cmd)

    # Method B: Python zeroconf
    if args.method == "zeroconf" or args.method is None:
        try:
            from zeroconf import Zeroconf, ServiceInfo
        except ImportError:
            error("Python 'zeroconf' 库未安装。运行: pip3 install zeroconf")
            sys.exit(1)

        ips = get_local_ips()
        gateway_url = args.gateway_url or f"http://{ips[0]}:{port}"

        info = ServiceInfo(
            type_=f"{service_type}.local.",
            name=f"{service_name}.{service_type}.local.",
            port=port,
            properties={
                "gatewayUrl": gateway_url,
                "hostname": platform.node(),
                "version": "1",
            },
            server=f"{platform.node()}.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        try:
            signal.pause()
        except KeyboardInterrupt:
            pass
        finally:
            zc.unregister_service(info)
            zc.close()

    # Method C: Legacy avahi-browse approach — shouldn't reach here
    error("不支持的发现方法，请使用 --method avahi 或 --method zeroconf")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Mode 2: Discover (mDNS scan)
# ---------------------------------------------------------------------------
class OpenClawListener:
    """Callback-based listener for zeroconf service browser."""

    def __init__(self):
        self.found = set()

    def remove_service(self, zc, type_, name):
        pass

    def add_service(self, zc, type_, name):
        info_obj = zc.get_service_info(type_, name)
        if not info_obj:
            return
        host = socket.inet_ntoa(info_obj.addresses[0]) if info_obj.addresses else "?"
        port = info_obj.port
        props = {k.decode(): v.decode() if isinstance(v, bytes) else v
                 for k, v in info_obj.properties.items()}
        gateway_url = props.get("gatewayUrl", f"http://{host}:{port}")
        hostname = props.get("hostname", name)

        key = f"{host}:{port}"
        if key not in self.found:
            self.found.add(key)
            emit({
                "type": "discovered",
                "name": hostname,
                "host": host,
                "port": port,
                "gatewayUrl": gateway_url,
                "ipVersions": ["v4"],
                "properties": props,
            })


def cmd_discover(args):
    """Scan the LAN for other OpenClaw instances advertising via mDNS."""
    service_type = "_openclaw-gateway._tcp"
    timeout = args.timeout
    method = args.method

    info(f"🔍 正在扫描局域网 OpenClaw 实例 (服务类型: {service_type})")
    info(f"   超时: {timeout} 秒\n")

    if method == "avahi" and platform.system() == "Linux":
        _discover_avahi(service_type, timeout)
    else:
        _discover_zeroconf(service_type, timeout)

    info(f"扫描完成，共发现 {len(_discover_zeroconf_state.get('found', set()))} 个实例")


_discover_zeroconf_state = {"found": set()}

def _discover_zeroconf(service_type, timeout):
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        error("Python 'zeroconf' 库未安装。运行: pip3 install zeroconf")
        sys.exit(1)

    zc = Zeroconf()
    listener = OpenClawListener()
    browser = ServiceBrowser(zc, f"{service_type}.local.", listener)
    _discover_zeroconf_state["found"] = listener.found

    try:
        time.sleep(timeout)
    except KeyboardInterrupt:
        pass
    finally:
        zc.close()


def _discover_avahi(service_type, timeout):
    import subprocess
    try:
        result = subprocess.run(
            ["avahi-browse", "-rtp", service_type],
            capture_output=True, text=True, timeout=timeout,
        )
        for line in result.stdout.splitlines():
            if not line.startswith("="):
                continue
            parts = line.split(";")
            if len(parts) < 8:
                continue
            name = parts[3]
            host = parts[7]
            port_str = parts[8]
            try:
                port = int(port_str)
            except ValueError:
                port = 18789

            # Resolve to get TXT records
            resolve = subprocess.run(
                ["avahi-resolve", "-n", host],
                capture_output=True, text=True, timeout=5,
            )
            resolved_ip = resolve.stdout.strip().split("\t")[-1] if resolve.returncode == 0 else host

            emit({
                "type": "discovered",
                "name": name,
                "host": resolved_ip,
                "port": port,
                "gatewayUrl": f"http://{resolved_ip}:{port}",
                "ipVersions": ["v4"],
                "properties": {},
            })
    except subprocess.TimeoutExpired:
        pass


# ---------------------------------------------------------------------------
# Mode 3: Register (WAN registry)
# ---------------------------------------------------------------------------
REGISTRY_API_VERSION = "v1"

def cmd_register(args):
    """Register this gateway with a central registry for WAN discovery."""
    registry_url = args.registry.rstrip("/")
    payload = {
        "name": args.name or f"OpenClaw-{platform.node()}",
        "gatewayUrl": args.gateway_url,
        "hostname": platform.node(),
        "localIps": get_local_ips(),
        "port": args.port,
        "version": "1",
        "tags": args.tags.split(",") if args.tags else [],
        "publicKey": args.public_key or "",
        "ttl": args.ttl,
    }

    url = f"{registry_url}/api/{REGISTRY_API_VERSION}/register"
    info(f"正在注册到 {url}")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            emit({
                "type": "registered",
                "id": body.get("id", "?"),
                "peers": body.get("peers", []),
                "registryUrl": registry_url,
            })
            info(f"注册成功！实例 ID: {body.get('id', '?')}")
            peers = body.get("peers", [])
            if peers:
                info(f"当前已知的在线实例: {len(peers)} 个")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        error(f"注册失败 (HTTP {e.code}): {body}")
        sys.exit(1)
    except Exception as e:
        error(f"注册失败: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Mode 4: Query (WAN registry)
# ---------------------------------------------------------------------------
def cmd_query(args):
    """Query a central registry for all registered OpenClaw instances."""
    registry_url = args.registry.rstrip("/")
    url = f"{registry_url}/api/{REGISTRY_API_VERSION}/peers"

    info(f"正在查询注册表: {url}")

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            peers = body.get("peers", [])
            emit({
                "type": "query_result",
                "count": len(peers),
                "peers": peers,
                "registryUrl": registry_url,
            })
            info(f"查询完成，共 {len(peers)} 个在线实例")
    except urllib.error.HTTPError as e:
        error(f"查询失败 (HTTP {e.code})")
        sys.exit(1)
    except Exception as e:
        error(f"查询失败: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw Peer Discovery — 发现其他 OpenClaw 实例",
    )
    parser.add_argument("--method", choices=["avahi", "zeroconf"],
                        default="zeroconf" if platform.system() != "Linux" else "avahi",
                        help="mDNS 实现方式 (默认: Linux avahi, 其他 zeroconf)")

    sub = parser.add_subparsers(dest="mode", required=True)

    # publish
    p = sub.add_parser("publish", help="广播本机 Gateway 到局域网")
    p.add_argument("--name", help="服务名称 (默认: OpenClaw-<hostname>)")
    p.add_argument("--port", type=int, default=18789, help="Gateway 端口 (默认: 18789)")
    p.add_argument("--gateway-url", help="可被外部访问的 Gateway URL，留空则自动推断")

    # discover
    p = sub.add_parser("discover", help="扫描局域网发现其他 OpenClaw 实例")
    p.add_argument("--timeout", type=int, default=10, help="扫描超时秒数 (默认: 10)")

    # register
    p = sub.add_parser("register", help="向远程注册表注册")
    p.add_argument("--registry", required=True, help="注册表 URL (如 http://hub.example.com:8080)")
    p.add_argument("--name", help="实例名称")
    p.add_argument("--gateway-url", required=True, help="可被公开访问的 Gateway URL")
    p.add_argument("--port", type=int, default=18789, help="Gateway 端口")
    p.add_argument("--tags", default="", help="逗号分隔的标签 (如: home,office)")
    p.add_argument("--public-key", help="Gateway 公钥 (如需要)")
    p.add_argument("--ttl", type=int, default=300, help="注册有效期秒数 (默认: 300)")

    # query
    p = sub.add_parser("query", help="查询注册表获取所有在线实例")
    p.add_argument("--registry", required=True, help="注册表 URL (如 http://hub.example.com:8080)")

    args = parser.parse_args()
    if args.method is None:
        args.method = "zeroconf" if platform.system() != "Linux" else "avahi"

    {
        "publish": cmd_publish,
        "discover": cmd_discover,
        "register": cmd_register,
        "query": cmd_query,
    }[args.mode](args)


if __name__ == "__main__":
    main()
