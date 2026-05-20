#!/usr/bin/env bash
set -euo pipefail

# openclaw-peer-discovery: Install dependencies
# Supports both pip3 (Python zeroconf) and apt (Avahi CLI tools)

echo "🦞 openclaw-peer-discovery — 安装依赖..."

# Try Python zeroconf (preferred — cross-platform)
if command -v pip3 &>/dev/null; then
    echo "[✓] pip3 可用，安装 Python zeroconf 库..."
    pip3 install zeroconf --quiet --break-system-packages 2>/dev/null || \
    pip3 install zeroconf --quiet
else
    echo "[!] pip3 不可用，尝试系统包管理器..."
fi

# Also ensure Avahi is available for mDNS (Linux)
if [[ "$(uname)" == "Linux" ]]; then
    if ! command -v avahi-publish &>/dev/null; then
        echo "[!] Avahi 未安装，尝试安装..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y -qq avahi-utils avahi-daemon
            echo "[✓] Avahi 已安装"
        elif command -v apk &>/dev/null; then
            apk add avahi-tools avahi
            echo "[✓] Avahi 已安装"
        else
            echo "[!] 无法自动安装 Avahi，请手动安装。mDNS 发现将使用 Python zeroconf。"
        fi
    else
        echo "[✓] Avahi 已就绪"
    fi
fi

echo
echo "✅ 安装完成！运行以下命令查看帮助："
echo "   python3 peer_discovery.py --help"
echo "   python3 peer_discovery.py discover --timeout 10"
