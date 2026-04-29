#!/bin/bash
if [ -f uvicorn.pid ]; then
    kill $(cat uvicorn.pid)
    rm uvicorn.pid
    echo "服务已停止"
else
    echo "未找到 PID 文件"
fi
