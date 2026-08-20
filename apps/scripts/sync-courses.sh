#!/bin/bash
# 把后端课件产物(CSL JSON + 音频 + 图形资产)同步到前端 public,供 dev server 静态服务
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$ROOT/web/public/courses"
cp -r "$ROOT/api/courses" "$ROOT/web/public/courses"
echo "✅ courses 已同步到 $ROOT/web/public/courses"
