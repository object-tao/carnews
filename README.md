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
- 资讯与资源：按栏目、分类编辑纯文本或 Markdown，支持表格、草稿、发布时间、作者、多个参考来源和下载附件。发布时间晚于当前时间的内容不公开。
- 网址标识请使用唯一英文短语，例如 `china-kazakhstan`。正文按白名单清理或自动转义，不执行 HTML 脚本。
- 资源附件通过受发布状态控制的下载入口提供，不公开媒体目录。
- 初始化提供四个业务区域与六篇一般性运输知识，不编造新闻、价格、资质或案例。行业资讯初始为空，等待真实资料。
- 初始化命令可重复执行，不覆盖管理员已有修改。

## 口岸资料导入

`content/ports/catalog.json` 包含 66 篇资料：新疆 14、内蒙古 11、东北 22、广西 9、云南 10。
其中 16 篇是基础事实校订与运输要点补充版，50 篇保留为待审草稿。校对日期不代表实时通关确认。
12 张实景资料图存放在 `content/ports/images/`；作者、许可、来源与历史照片说明见同目录的 `photo_manifest.json`。
照片不代表当前设施或开放状况，使用时保留署名及许可链接。Markdown 文稿与图片分别适用各自的许可，不改变图片原有 CC 许可。

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py import_ports --dry-run
.\.venv\Scripts\python.exe manage.py import_ports --publish-reviewed --original-dir 'C:\Users\Administrator\WorkBuddy\2026-11-06-14-40-25\陆路口岸系列'
```

省略 `--publish-reviewed` 时全部导入为草稿；它仅控制本次新建记录，不更改已存在记录的发布状态。
命令可重复执行，按 `port-编号` 跳过已有记录，不覆盖管理员修改，也不重复复制照片。
`--original-dir` 可省略；提供时完整原文保存至后台“内部校订资料”，不进入前台或站内搜索。
未经逐项核实的原稿不能批量发布；后台编辑入口为“资讯与资源”，筛选资料类型“口岸介绍”和发布状态。
部署脚本在数据库备份及迁移后执行导入，仍保留现有管理员编辑；此改动本身不启用 ECS 自动部署。

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


## 资源库与行业资讯（本次更新）

- 国家与地区：后台独立维护。口岸等资料可关联多个国家，例如同一跨境口岸同时归属中国和哈萨克斯坦检索结果。
- 资源类型：口岸介绍、车型介绍、桥梁介绍、运输知识、其他资料；管理员可新增类型。`routes` 标识保留给共用线路资料。
- 线路介绍：资源库直接读取运输线路记录；修改、发布或下架一次，两处同步，不建立副本。
- 资料详情：按需填写位置、规格参数、开放及通行信息、单证要求和限制条件；关联国家、口岸/车型/桥梁文章及运输线路。仅展示已发布关联内容。
- 分类筛选：资源类型、国家、内容分类与关键词组合搜索，分页保留筛选条件。区域概览不会自动推断所有国家，管理员需在具体线路中维护国家关联。
- 行业资讯 `/news/` 下分行业新闻与参考运价 `/prices/`。运价由管理员核实并发布，不接入未经授权的自动价格来源。
- 运价包括装卸地、车型、货物条件、单价/区间、币种、计价单位、费用范围、来源、有效期及更新时间。默认草稿；发布时自动填写发布时间，也支持定时发布。
- 运价有效期按北京时间日期计算，结束当日仍有效。过期运价标明“历史参考”和“不作为当前报价”，未来有效期标明“尚未生效”；可按状态筛选。
- 升级使用新增字段的数据迁移，原有文章、发布状态和管理员修改保留；原资源库文章归入运输知识。不初始化真实口岸事实或示例报价。

资料支持 PNG/JPG/WebP 图片上传（后台校验图片格式）；图片经发布状态校验后提供访问，草稿图片不公开。
