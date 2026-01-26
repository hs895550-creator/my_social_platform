#!/bin/bash
# 遇到错误立即停止
set -e

echo "========================================"
echo "开始自动部署..."
echo "========================================"

# 1. 进入项目目录
APP_DIR="/var/www/my_social_platform"
if [ ! -d "$APP_DIR" ]; then
    echo "错误：找不到目录 $APP_DIR"
    echo "请确保您已经把代码上传到了服务器的 /var/www/ 目录下"
    exit 1
fi
cd $APP_DIR

# 2. 安装依赖
echo ">>> 正在安装 Python 依赖..."
if command -v pip3 &> /dev/null; then
    pip3 install -r requirements.txt
else
    echo "警告：未找到 pip3，尝试使用 pip..."
    pip install -r requirements.txt
fi

# 3. 配置后台服务 (Systemd)
echo ">>> 正在配置后台服务..."
cp deploy/social_platform.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable social_platform
echo ">>> 重启服务..."
systemctl restart social_platform

# 4. 配置 Nginx
echo ">>> 正在配置 Nginx..."
NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"

if [ -d "$NGINX_AVAILABLE" ]; then
    # Ubuntu/Debian 风格
    cp deploy/nginx_datamgr.conf "$NGINX_AVAILABLE/datamgr.it.com"
    # 创建软链接（如果已存在则覆盖）
    ln -sf "$NGINX_AVAILABLE/datamgr.it.com" "$NGINX_ENABLED/datamgr.it.com"
    echo ">>> 已更新 sites-available 配置"
else
    # CentOS/RHEL 风格
    cp deploy/nginx_datamgr.conf /etc/nginx/conf.d/datamgr.it.com.conf
    echo ">>> 已更新 conf.d 配置"
fi

# 5. 检查并重载 Nginx
echo ">>> 检查 Nginx 配置..."
nginx -t
echo ">>> 重载 Nginx..."
nginx -s reload

echo "========================================"
echo "✅ 部署成功！"
echo "请在浏览器访问: http://datamgr.it.com"
echo "========================================"
