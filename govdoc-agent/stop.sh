#!/bin/bash
# stop.sh
if [ -f uvicorn.pid ]; then
    PID=$(cat uvicorn.pid)
    # 杀掉进程组（包括所有子进程）
    pkill -P $PID 2>/dev/null  # 先杀子进程
    kill -9 $PID 2>/dev/null   # 再杀父进程
    rm -f uvicorn.pid
    echo "服务已停止"
else
    # 备用方案：直接杀端口
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    echo "服务已停止（强制清理端口）"
fi