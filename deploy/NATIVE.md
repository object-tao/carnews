# 原生部署与持续发布

正式域名：`https://struck.diwuzhou.cn/`，后台：`/admin/`。阿里云 ECS 为 `39.107.139.55`。
本服务只监听 `127.0.0.1:18086`，由独立 Nginx 虚拟主机代理。原有 IMT 和其他站点继续使用各自服务、端口、数据库与配置。

## 目录与进程

| 项目 | 位置 |
| --- | --- |
| 项目根目录 | `/opt/kunteng-truck` |
| 独立 Python 3.13 | `runtime/python/bin/python3` |
| 版本目录与当前链接 | `releases/`、`current` |
| 网站数据库、上传媒体 | `shared/data/` |
| 生产环境 | `shared/app.env`，root:kunteng-web 0640 |
| 应用服务 | `kunteng-truck.service`，用户 `kunteng-web` |
| 私有备份 | `backups/`，root 专用 |
| 当前版本记录 | `current-release.json` |
| Nginx 站点 | `/etc/nginx/sites-available/struck.diwuzhou.cn` |

运行环境独立安装，不替换系统 Python。版本内的依赖严格使用 `requirements.txt`，安装及应用准备命令以 `kunteng-web` 身份运行。
原始文稿保留在后台私有字段；数据库、媒体、环境密钥和管理员凭据不进入 GitHub 或公开下载目录。

## HTTPS

域名 A 记录指向服务器后，以 `nginx-bootstrap.conf` 提供 `/.well-known/acme-challenge/`，使用已有 Certbot 账户、webroot `/var/www/letsencrypt` 为新域名单独申请证书。
证书签发后启用 `nginx.conf`；所有 Nginx 变更先运行 `nginx -t`，再平滑 reload。生产配置始终启用 Django HTTPS 和安全 Cookie，不通过关闭安全配置来临时提供后台 HTTP 登录。

## GitHub Actions

`ci.yml` 执行测试、迁移检查、静态资源和生产配置检查，并保留版本化容器镜像产物。当前 ECS 通过原生源代码包发布，不依赖 Docker 或 GHCR 下载。

`deploy.yml` 在 CI 成功后使用准确的提交 SHA 生成 `git archive`，经受限 SSH 账号发送到服务器。手动发布也必须指定曾在 main 通过 CI 的完整 SHA。

GitHub `production` 环境包含 `ECS_HOST`、`ECS_USER`、`ECS_PORT`、`ECS_SSH_KEY`、`ECS_KNOWN_HOSTS`。仓库变量 `ECS_DEPLOY_ENABLED=true` 启用自动发布。
部署使用新建专用密钥；已有服务器 root 运维密钥不上传 GitHub。账号被强制限制为 `deploy <40位SHA>`，不允许交互 Shell、端口转发或任意命令。

服务器受控入口为 `/usr/local/bin/kunteng-deploy-entrypoint`、`/usr/local/sbin/kunteng-release` 和 `/usr/local/lib/kunteng-native-release.py`。入口文件由 root 管理，不能由部署账号或运行中的网站更改。
`native_release.py` 拒绝路径穿越、链接、设备节点、重复文件和私有数据目录；先安装独立版本、备份，再运行 `prepare_release.py` 的迁移及重复安全内容导入，最后切换当前链接并检查健康状态。
失败时可恢复先前应用版本；数据库不会自动降级。涉及不兼容迁移时，需要结合当次备份评估恢复。

## 备份和运维

`kunteng-truck-backup.timer` 每日北京时间 03:30 后随机延迟最多 5 分钟执行；每次版本发布也先备份。
备份包含 SQLite 一致性快照、媒体、生产环境与版本记录，附带 SHA-256。归档仅允许 root 读取，恢复时按私有数据管理。备份保存在同一 ECS，异地副本另行配置。

常用检查：

```bash
systemctl status kunteng-truck --no-pager
systemctl list-timers kunteng-truck-backup.timer
journalctl -u kunteng-truck -n 50 --no-pager
curl -H 'Host: struck.diwuzhou.cn' -H 'X-Forwarded-Proto: https' http://127.0.0.1:18086/healthz/
```

后台管理员在首次部署时创建，凭据单独保存，不存在代码中的默认密码。管理员可在“网站设置”维护咨询电话、微信、二维码、备案号和公司介绍。
