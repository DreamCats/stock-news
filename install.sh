#!/bin/bash
# stock-news 安装脚本

set -e

echo "安装 stock-news..."

if ! command -v uv &> /dev/null; then
    echo "错误: uv 未安装"
    echo "请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "清理旧构建..."
rm -rf dist build

echo "构建 wheel..."
uv build --wheel

echo "卸载旧版本..."
uv tool uninstall stock-news 2>/dev/null || true

echo "全局安装 sn 命令..."
uv tool install dist/*.whl

echo ""
echo "安装完成！"
echo ""
echo "使用方法："
echo "  sn --help                    # 查看帮助"
echo "  sn config show               # 查看配置"
echo "  sn fetch --source all --last 30m"
echo "  sn analyze show --date today"
echo ""
echo "定时调度："
echo "  sn schedule install          # 安装 launchd 定时 tick"
echo "  sn schedule status           # 查看调度状态"
echo "  sn schedule uninstall        # 卸载定时调度"
