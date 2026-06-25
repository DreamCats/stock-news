#!/bin/bash
# stock-news 安装脚本

set -e

echo "安装 stock-news..."

if ! command -v uv &> /dev/null; then
    echo "错误: uv 未安装"
    echo "请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

REPO_URL="${STOCK_NEWS_REPO_URL:-https://github.com/DreamCats/stock-news.git}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ -f "$SCRIPT_DIR/pyproject.toml" ] && grep -q 'name = "stock-news"' "$SCRIPT_DIR/pyproject.toml"; then
    PROJECT_DIR="$SCRIPT_DIR"
else
    if ! command -v git &> /dev/null; then
        echo "错误: git 未安装"
        exit 1
    fi
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT
    echo "拉取源码..."
    git clone --depth 1 "$REPO_URL" "$TMP_DIR/stock-news"
    PROJECT_DIR="$TMP_DIR/stock-news"
fi

cd "$PROJECT_DIR"

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
echo "  sn config set wechat.timeout 60"
