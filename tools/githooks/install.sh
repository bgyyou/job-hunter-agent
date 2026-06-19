#!/bin/sh
# 把 tools/githooks/* 安装到 .git/hooks/
# 用法：bash tools/githooks/install.sh

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
SRC="$REPO_ROOT/tools/githooks"
DST="$REPO_ROOT/.git/hooks"

for hook in pre-commit; do
    if [ -f "$SRC/$hook" ]; then
        cp "$SRC/$hook" "$DST/$hook"
        chmod +x "$DST/$hook"
        echo "✅ 已安装 .git/hooks/$hook"
    fi
done

echo ""
echo "提示：今后每次 git commit 会自动扫描密钥。"
echo "      如果误报，请检查 tools/githooks/pre-commit 的 case 例外清单。"
