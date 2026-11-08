# 阿里云 ECS 部署与 CI/CD

## 2026-11-07 原生部署

正式域名为 `truck.diwuzhou.cn`；早期误配的 `struck.diwuzhou.cn` 保留永久跳转。服务器为 Ubuntu 22.04，现有站点采用 Nginx/systemd，未安装 Docker，因此实际部署采用独立 Python 3.13、Gunicorn 与 systemd。
当前流程见 [原生部署说明](NATIVE.md)。`deploy.yml` 通过专用受限 SSH 账号传送已经通过 CI 的源代码归档；下方 Docker 方案仅作可选参考，不是该服务器正在使用的发布方式。

## 当前边界

网站与多式联运系统共用 ECS。本目录只提供独立服务方案，不替换已有配置、不重启已有应用。必须先确认 OS、Docker Compose 版本、现有反向代理、端口和资源。若不是 Linux + Docker，应按实际环境调整后再执行。

## 1. 只读检查

通过已配置的 SSH 连接服务器，检查：

```bash
uname -a
free -h
df -h
ss -lntp
docker version
docker compose version
docker ps
sudo nginx -T
```

Nginx 输出可能含内部信息，不要公开粘贴完整配置。确认 18086 端口空闲、域名 DNS 指向该 ECS，并有适用的 HTTPS 证书。18086 只绑定本机，不需要在安全组开放。

## 2. 独立应用目录

从 GitHub 获取本项目的 `compose.yml` 与 `deploy/`，放到 `/opt/kunteng-truck`，不要覆盖其他项目目录。复制 `.env.example` 为 `.env`，使用 `python3 -c 'import secrets; print(secrets.token_urlsafe(64))'` 生成 SECRET_KEY 并填入（不要将输出贴入聊天或提交）。`.env` 权限设为 600。

```bash
cd /opt/kunteng-truck
mkdir -p data
sudo chown 10001:10001 data
chmod 700 data
chmod 600 .env
```

从仓库 Actions 找到成功构建的完整 commit SHA，镜像为 `ghcr.io/object-tao/carnews:<完整SHA>`。GitHub 包默认可能为私有：在 ECS 通过 Docker 的标准交互方式登录 GHCR，或在明确希望公开镜像时调整包可见性。不要把令牌写入仓库。

首次执行：

```bash
bash deploy/release.sh ghcr.io/object-tao/carnews:<完整SHA>
export APP_IMAGE=$(cat .current-image)
docker compose exec web python manage.py createsuperuser
```

先验证 `curl -H 'Host: truck.diwuzhou.cn' -H 'X-Forwarded-Proto: https' http://127.0.0.1:18086/healthz/`。

## 3. 接入现有 Nginx

`nginx.conf` 为独立域名配置样例。替换证书路径，根据现有环境合并，先检查是否已有同名 server。只在 `nginx -t` 成功后 reload。应用要求 HTTPS；代理须覆盖设置 `X-Forwarded-Proto`。

二维码通过应用 `/contact/qr/` 提供，无需 Nginx 读取受保护的数据目录；样例 `/media/contact/` location 可省略。资源附件仅经 `/download/<slug>/` 提供，`/media/` 保持拒绝访问。

上线前由管理员补充备案号、联系方式，检查业务文案；用手机验收并验证现有多式联运系统仍正常。

## 4. GitHub 自动化

`ci.yml`：推送 main/PR 后运行测试、迁移检查、静态资源构建和生产配置检查；仅 main 成功后推送带完整 SHA 的 GHCR 镜像。CI 不接触服务器。

`deploy.yml`：镜像工作流成功后部署，但只有配置仓库变量 `ECS_DEPLOY_ENABLED=true` 才会启用。初始保持未启用，避免在服务器尚未检查和初始化时执行。

在 GitHub Settings → Environments 建立 `production`，按需要设置审核规则。添加以下 Environment secrets：

| 名称 | 内容 |
| --- | --- |
| ECS_HOST | ECS 主机地址 |
| ECS_USER | 专用部署用户 |
| ECS_PORT | SSH 端口，可填 22 |
| ECS_SSH_KEY | 专用部署私钥 |
| ECS_KNOWN_HOSTS | 经独立可信渠道核实的 SSH 主机公钥记录 |

不要只依赖未经校验的 `ssh-keyscan` 输出建立信任。部署用户需能运行该服务的 Docker 命令；Docker 访问权限相当于高权限，应使用专用账号及密钥。

手动部署工作流支持输入完整 SHA，仅接受已在 main 成功构建的提交。工作流不自动复制服务器脚本；变更部署脚本或 compose 时需同步审核后的文件再启用相关发布。

## 5. 备份与回退

每次发布前通过 SQLite backup API 生成一致性数据库快照到 `backups/`。迁移成功后启动新容器，检查健康状态；失败时尝试恢复上一应用镜像。迁移失败会立即停止，不会替换正在运行的容器。

数据库不会自动回退。若新迁移与旧版本不兼容，应人工评估恢复。`data/media/` 上传文件需要另外做定期异地备份；本脚本的数据库快照不包含上传文件。备份可能包含业务数据，不放进公开目录或 GitHub。

手动回退兼容版本：

```bash
cd /opt/kunteng-truck
export APP_IMAGE=$(cat .previous-image)
test -n "$APP_IMAGE"
docker compose up -d --no-deps web
docker compose ps
```

应用未启用父域全站 HSTS 子域策略与预加载；仅对本站提供短期 HSTS，避免对共用域名的其他系统施加未经确认的要求。
