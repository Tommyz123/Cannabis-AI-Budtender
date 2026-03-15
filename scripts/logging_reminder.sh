#!/bin/bash
input=$(cat)
file_path=$(echo "$input" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" \
  2>/dev/null)

if echo "$file_path" | grep -qE "(backend/|tests/)"; then
  echo "⚠️  [LOGGING] 修改了代码文件 → 任务完成后请追加 planning/logging.md"
  echo "    格式：## [$(date +%Y-%m-%d)] 类型 | 简述"
  echo "⚠️  [CONTEXT] 若改了公开接口（参数、返回值、方法名）或新增/删除文件 → 请同步更新 planning/context.md"
fi
