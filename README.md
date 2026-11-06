# 深圳昆腾企业官网

Django 5.2 LTS · 中文官网与管理员内容后台 · GitHub Actions · 阿里云 ECS

## 本地开发（Windows）

工作目录：`D:\CodexSessionArchive\carnews`。虚拟环境、数据库、缓存均放在 D 盘。

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_content
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:18087
```

首次安装：`python -m venv .venv`，然后 `.\.venv\Scripts\python.exe -m pip install --cache-dir D:\CodexSessionArchive\pip-cache -r requirements.txt`。

前台 http://127.0.0.1:18087/，后台 `/admin/`。管理员密码由交互式命令设置，不存在默认管理员和默认密码。

## 内容管理

- 网站设置：公司介绍、电话、微信、二维码和备案号。尚缺联系方式及备案号，正式上线前补齐。
- 运输线路：后台新增记录，选择区域，填写覆盖国家、网址标识及说明；勾选公开展示后前台可见。
- 资讯与资源：按栏目、分类编辑纯文本，支持草稿、发布时间、作者、来源和下载附件。发布时间晚于当前时间的内容不公开。
- 网址标识请使用唯一英文短语，例如 `china-kazakhstan`。正文自动转义，不执行 HTML。
- 资源附件通过受发布状态控制的下载入口提供，不公开媒体目录。
- 初始化提供四个业务区域与六篇一般性运输知识，不编造新闻、价格、资质或案例。行业资讯初始为空，等待真实资料。
- 初始化命令可重复执行，不覆盖管理员已有修改。

## 验证

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

测试覆盖公共页、详情页、搜索、区域筛选、草稿与定时发布隔离、附件授权、脚本转义、初始化幂等性、后台登录及 CSRF。

## 部署

见 [部署说明](deploy/README.md)。部署前需要服务器连接、资源及现有 Nginx 配置检查。仓库内不保存 SSH 私钥、环境密钥、数据库或上传文件。

SEO 基础包含服务端 HTML、页面标题和摘要、规范链接、站点地图、robots、文章结构化数据、发布时间与作者。不承诺搜索排名或 AI 引用。

## 持久化与维护

SQLite 适合当前低写入量的单服务器内容站。`data/` 必须持久化，附件与二维码也在此目录。未来多实例或高并发写入时迁移至 PostgreSQL。镜像回退不等于数据库回退，数据库迁移需保持向后兼容。
