#!/bin/bash
PROJECT_ROOT="/mnt/c/Users/zhi89/Desktop/cannabis_AI_BUDTENDER"
cd "$PROJECT_ROOT"

echo "=== 环境健康检查 ==="

# 1. 检查venv
if [ ! -f "venv/bin/activate" ]; then
  echo "❌ venv不存在，正在重建..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -r backend/requirements.txt
else
  source venv/bin/activate
  echo "✅ venv正常"
fi

# 2. 检查端口8000
if lsof -i :8000 > /dev/null 2>&1; then
  echo "⚠️  端口8000被占用，正在清理..."
  lsof -ti :8000 | xargs kill -9
  echo "✅ 端口已清理"
else
  echo "✅ 端口8000空闲"
fi

# 3. 检查关键依赖
python -c "import langfuse; import fastapi; import uvicorn" 2>/dev/null
if [ $? -eq 0 ]; then
  echo "✅ 关键依赖正常"
else
  echo "❌ 依赖缺失，正在安装..."
  pip install -r backend/requirements.txt
fi

echo "=== 检查完成，可以开始工作 ==="
