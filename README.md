# 🦞 OpenClaw Peer Discovery

> **让所有龙虾找到彼此。**  
> 多 OpenClaw 网关实例自动发现与组网工具。

## 简介

**openclaw-peer-discovery** 为 OpenClaw 网关实例提供两种发现机制：

- **🏠 LAN 发现** — 同一局域网内通过 mDNS 自动广播和扫描
- **🌐 WAN 发现** — 跨网络通过轻量中心注册表注册和查询

## 快速开始

```bash
# 安装依赖
bash scripts/install.sh

# LAN 模式：广播自己
python3 scripts/peer_discovery.py publish --name "My-Gateway" --port 18789

# LAN 模式：扫描邻居
python3 scripts/peer_discovery.py discover --timeout 10

# WAN 模式：启动注册服务器
python3 scripts/registry_server.py --port 8080

# WAN 模式：注册到注册表
python3 scripts/peer_discovery.py register \
  --registry "http://your-registry:8080" \
  --name "My-Gateway" \
  --gateway-url "http://1.2.3.4:18789" \
  --tags "vps,production"
```

## 项目结构

```
openclaw-peer-discovery/
├── README.md
├── SKILL.md              # OpenClaw 技能描述
├── LICENSE
├── scripts/
│   ├── install.sh         # 依赖安装脚本
│   ├── peer_discovery.py  # 发现工具（publish/discover/register/query）
│   └── registry_server.py # 中心注册表服务
└── references/            # 参考文档（预留）
```

## 协议

### Peer JSON 格式

```json
{
  "id": "唯一标识",
  "name": "节点名称",
  "gatewayUrl": "外部可达 Gateway URL",
  "hostname": "机器主机名",
  "port": 18789,
  "localIps": ["本机 IP 列表"],
  "tags": ["自定义标签"],
  "publicKey": "",
  "registeredAt": 1747698900,
  "expiresAt": 1747699200,
  "ttl": 300
}
```

### mDNS 服务类型

- 类型：`_openclaw-gateway._tcp`
- TXT 字段：`gatewayUrl`、`hostname`、`version`

## License

MIT
