#!/bin/bash

# 打印调试信息
echo "=== Starting application via start.sh ==="
echo "Current Directory: $(pwd)"
echo "User: $(whoami)"
echo "Environment PORT variable: '$PORT'"

# 如果 PORT 为空，强制设置为 8080
if [ -z "$PORT" ]; then
    echo "WARNING: PORT variable is empty. Defaulting to 8080."
    export PORT=8080
else
    echo "Using provided PORT: $PORT"
fi

# 启动应用
# 使用 exec 让 python 进程替代 shell 进程，确保能接收到关闭信号
echo "Executing: python main.py"
exec python main.py
