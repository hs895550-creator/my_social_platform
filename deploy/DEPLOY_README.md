# 部署指南：将社交平台挂载到 datamgr.it.com

本指南将指导您如何在 Linux 服务器上部署该平台，并配置域名访问。

## 1. 准备工作

确保您的服务器上已经安装了：
- Python 3.8+
- Nginx
- Git (可选，用于拉取代码)

## 2. 上传代码

将整个项目文件夹上传到服务器，例如上传到 `/var/www/my_social_platform`。

```bash
# 示例：在本地执行 scp 命令上传 (假设服务器 IP 为 1.2.3.4)
scp -r /Users/huangsiwen/Desktop/my_social_platform root@1.2.3.4:/var/www/
```

## 3. 安装依赖

登录服务器，进入项目目录并安装依赖：

```bash
ssh root@1.2.3.4
cd /var/www/my_social_platform
pip3 install -r requirements.txt
```

## 4. 配置后台服务 (Systemd)

为了让程序在后台稳定运行，我们需要配置一个系统服务。

1. 修改 `deploy/social_platform.service` 文件中的路径，确保与实际路径一致。
2. 将服务文件复制到系统目录：

```bash
cp deploy/social_platform.service /etc/systemd/system/
```

3. 启动服务并设置开机自启：

```bash
systemctl daemon-reload
systemctl start social_platform
systemctl enable social_platform
```

4. 检查服务状态：

```bash
systemctl status social_platform
```
如果看到 `Active: active (running)`，说明服务已启动，正在监听 8080 端口。

## 5. 配置域名转发 (Nginx)

我们需要告诉 Nginx，当用户访问 `datamgr.it.com` 时，把请求转给我们的 8080 端口服务。

1. 将 `deploy/nginx_datamgr.conf` 的内容复制到 Nginx 配置目录：

```bash
cp deploy/nginx_datamgr.conf /etc/nginx/conf.d/datamgr.it.com.conf
# 或者如果是 Ubuntu 系统：
# cp deploy/nginx_datamgr.conf /etc/nginx/sites-available/datamgr.it.com
# ln -s /etc/nginx/sites-available/datamgr.it.com /etc/nginx/sites-enabled/
```

2. 测试并重载 Nginx：

```bash
nginx -t
nginx -s reload
```

## 6. 验证

在浏览器访问 `http://datamgr.it.com`，您应该能看到社交平台的登录/注册页面。

---

## 常见问题排查

**Q: 访问域名显示 502 Bad Gateway**
A: 说明 Nginx 运行正常，但后端的 Python 服务没启动或端口不对。
- 检查服务状态: `systemctl status social_platform`
- 检查端口占用: `netstat -tulpn | grep 8080`

**Q: 两个平台冲突**
A: 确保另一个平台没有占用 8080 端口。如果另一个平台也用 8080，您需要修改其中一个的端口（例如改为 8081），并同步修改 Nginx 配置中的 `proxy_pass` 地址。
