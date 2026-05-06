#!/bin/bash

# 启动服务（使用进程组管理）
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > ./logs/MADW.log 2>&1 &

# 保存 PID
echo $! > uvicorn.pid
echo "服务已启动，PID: $(cat uvicorn.pid)"