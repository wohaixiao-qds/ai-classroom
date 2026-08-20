#!/bin/bash
# 把后端课件产物(CSL JSON + 音频 + 图形资产)同步到前端 public,供 dev server 静态服务
set -e
cd "$(dirname "$0")"
mkdir -p web/public
rm -rf web/public/courses
cp -r ../api/courses web/public/courses
echo "✅ courses 已同步到 web/public/courses"
