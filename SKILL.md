---
name: openclaw-peer-discovery
description: "让多个 OpenClaw 网关实例彼此发现对方。支持局域网（mDNS）自动发现和跨网络（中心注册表）远程发现。当用户想连接多个 OpenClaw 实例、或需要让不同机器上的 OpenClaw 互相感知时使用。"
---

# OpenClaw Peer Discovery Skill

## 概述

**openclaw-peer-discovery** 让所有 OpenClaw 网关（Gateway）实例能够互相发现对方，形成一个松散的 Peer 网络。

### 两种发现模式

| 模式 | 适用场景 | 原理 |
|------|---------|------|
| **LAN 发现** | 同一局域网内（家庭、办公网络） | mDNS / Bonjour 广播和扫描 |
| **WAN 发现** | 不同网络（VPS ↔ 家庭服务器） | 中心注册表（轻量 HTTP 服务） |

### 何时使用

- 你有**多台设备**分别运行 OpenClaw（如：VPS + 家庭服务器 + 笔记本）
- 你想让它们**互相知晓**对方的地址、名称、capabilities
- 你想建立多个 OpenClaw 实例之间的**协作/路由**

## 前置条件

- Python 3.8+
- Linux 推荐安装 Avahi（mDNS 支持），macOS/Windows 使用 Python zeroconf
- 跨网络发现需要**一台公开可达的注册服务器**（可用免费 VPS 或 Cloudflare Tunnel）

## 安装

```bash
cd ~/.openclaw/workspace/skills/openclaw-peer-discovery/scripts
bash install.sh
```

会自动安装：
- Python `zeroconf` 库（跨平台 mDNS）
- Linux: `avahi-utils`（系统级 mDNS 工具）

## 用法

### 1️⃣ LAN 发现（同一局域网）

**A 机器 — 广播自己：**
```bash
cd ~/.openclaw/workspace/skills/openclaw-peer-discovery/scripts

# 前台广播（按 Ctrl+C 停止）
python3 peer_discovery.py publish \
  --name "Home-Server" \
  --port 18789
```

**B 机器 — 扫描并发现：**
```bash
cd ~/.openclaw/workspace/skills/openclaw-peer-discovery/scripts

# 扫描局域网（10 秒超时）
python3 peer_discovery.py discover --timeout 10

# 输出示例（JSON lines）：
# {"type":"discovered","name":"Home-Server","host":"192.168.1.100","port":18789,"gatewayUrl":"http://192.168.1.100:18789","ipVersions":["v4"]}
```

> 💡 mDNS 只在同一个广播域生效（通常即同一交换机/路由器下的设备）

### 2️⃣ WAN 发现（跨网络 / 注册表模式）

**第一步：启动注册服务器**

在任意公网可访问的机器上：

```bash
cd ~/.openclaw/workspace/skills/openclaw-peer-discovery/scripts

# 无认证启动（端口 8080）
python3 registry_server.py --port 8080

# 带 Token 认证启动
REGISTRY_AUTH_TOKEN="your-secret-token" python3 registry_server.py --port 8080
```

> 建议使用 Tailscale Funnel、Cloudflare Tunnel 或 Nginx 反向代理暴露该服务。

**第二步：各实例注册自己**

```bash
# A 机器
python3 peer_discovery.py register \
  --registry "http://your-registry:8080" \
  --name "VPS-Gateway" \
  --gateway-url "http://1.2.3.4:18789" \
  --tags "vps,production"

# B 机器
python3 peer_discovery.py register \
  --registry "http://your-registry:8080" \
  --name "Home-Server" \
  --gateway-url "http://192.168.1.100:18789" \
  --tags "home,dev"
```

**第三步：查询所有在线实例**

```bash
# 任何机器上查询
python3 peer_discovery.py query --registry "http://your-registry:8080"

# 输出示例：
# {"type":"query_result","count":2,"peers":[
#   {"id":"a1b2c3d4e5f6","name":"VPS-Gateway","gatewayUrl":"http://1.2.3.4:18789","tags":["vps","production"]},
#   {"id":"b7c8d9e0f1a2","name":"Home-Server","gatewayUrl":"http://192.168.1.100:18789","tags":["home","dev"]}
# ]}
```

## 协议细节

### Peer Info JSON 格式

```json
{
  "id": "a1b2c3d4e5f6",
  "name": "Home-Server",
  "gatewayUrl": "http://192.168.1.100:18789",
  "hostname": "ubuntu-server",
  "port": 18789,
  "localIps": ["192.168.1.100", "10.0.0.2"],
  "tags": ["home", "dev"],
  "publicKey": "",
  "registeredAt": 1747698900,
  "expiresAt": 1747699200,
  "ttl": 300
}
```

### mDNS 服务类型

- 类型：`_openclaw-gateway._tcp`
- TXT 字段：
  - `gatewayUrl` — 外部可达的 Gateway URL
  - `hostname` — 机器主机名
  - `version` — 协议版本号

## 脚本参考

### `peer_discovery.py`

| 子命令 | 功能 |
|-------|------|
| `publish` | 通过 mDNS 广播本机 OpenClaw Gateway |
| `discover` | 扫描局域网发现其他 Peer |
| `register` | 向远程注册表注册本机 |
| `query` | 从注册表查询所有在线 Peer |

### `registry_server.py`

轻量 HTTP 注册表服务。无外部依赖（仅 Python 标准库）。

### `install.sh`

一键安装依赖（zeroconf + avahi）。

## 故障排查

**mDNS 不工作？**
- 检查是否在同一子网
- 某些 Wi-Fi 路由器禁止 mDNS 多播，可切换 WAN 模式
- Linux 上确认 `avahi-daemon` 在运行

**注册失败？**
- 确认注册服务器可达
- 如果启用了 Token 认证，检查 `Authorization: Bearer <token>` 是否正确
- 检查防火墙是否放行了端口

## 安全注意事项

- mDNS TXT 记录是**未认证**的，不能作为信任依据
- 注册表建议启用 `REGISTRY_AUTH_TOKEN` 防止未授权注册
- Peer 间的实际通信应使用 OpenClaw Gateway 自有的认证机制（配对 token）
