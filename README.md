# 深圳昆腾企业官网

Django 5.2 LTS · 中文官网与管理员内容后台 · GitHub Actions · 阿里云 ECS

正式站点使用 `https://struck.diwuzhou.cn/`，部署采用独立 Python/Gunicorn/systemd。运行与发布流程见 [原生部署说明](deploy/NATIVE.md)。

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
全部 66 篇已完成基础事实校订并补充运输组织要点；2026-11-07 批次重写原有 50 篇待审稿，原先 16 篇保留。
文章区分历史协定、规划、具体业务开通和当次受理；校对日期不代表实时通关确认，未确认开放或复关的通道明确标注资料边界。
66 篇口岸资料均有配图：37 张实景资料图、29 张明确标注的 AI 写实场景效果图。都拉塔与巴克图使用已核对授权的口岸实拍照片；其余 29 张场景图均在图内、图片说明和替代文本中说明“AI生成、非现场实拍”，不作为具体口岸建筑或运营状态的复原。

当前图片存放在 `content/ports/images/`，升级清单、前后版本与来源见 `scene-upgrade-20261107.json`；使用内置 image_gen 生成的逐图提示词见 `scene-generation-20261107.json`。早期图片版本、作者许可和关系示意图仍分别归档于 `photo_manifest.json`、`image-edition-20261107.json` 和 `content/ports/diagrams/`。

实景照片标明拍摄日期（可核实时）、作者、许可和来源，不代表当前设施或开放状态。AI 场景不填写虚构拍摄日期或摄影来源；列表完整显示含 AI 标识的画面。原始生成 PNG 留存在 D 盘私人归档，网站使用 WebP 显示版本。

已有数据库先执行 `backfill_port_images` 补齐早期空白图片，再用 `python manage.py upgrade_port_images --dry-run` 核验和 `python manage.py upgrade_port_images` 升级已知示意图。自动部署在备份后按此顺序执行；只有图片字节校验值和全部说明字段均匹配已知旧版时才替换。管理员改图、正文、私有原稿、关联资料和发布状态保留，旧媒体不删除。新建数据库由 `import_ports` 直接导入当前配图。
照片不代表当前设施或开放状况，使用时保留署名及许可链接。Markdown 文稿与图片分别适用各自的许可，不改变图片原有 CC 许可。

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py import_ports --dry-run
.\.venv\Scripts\python.exe manage.py import_ports --publish-reviewed --original-dir 'C:\Users\Administrator\WorkBuddy\2026-11-06-14-40-25\陆路口岸系列'
.\.venv\Scripts\python.exe manage.py publish_reviewed_ports --dry-run
.\.venv\Scripts\python.exe manage.py publish_reviewed_ports
```

省略 `--publish-reviewed` 时全部导入为草稿；它仅控制本次新建记录，不更改已存在记录的发布状态。
命令可重复执行，按 `port-编号` 跳过已有记录，不覆盖管理员修改，也不重复复制照片。
`publish_reviewed_ports` 专门升级本次 50 篇旧草稿：按 `review-20261107.json` 校验旧稿与新稿的内容摘要，再在同一事务中替换正文和来源、设置发布时间。
旧稿或来源在导入后被修改、曾经发布而又撤回、或记录缺失时，命令在写入前停止，需先核对对应记录；不会强行覆盖。
已带本次或更晚校订日期的记录保留管理员后续编辑与发布选择。原稿、图片、附件、国家和线路关联均不改动。
`--original-dir` 可省略；提供时完整原文保存至后台“内部校订资料”，不进入前台或站内搜索。
未经逐项核实的原稿不能批量发布；后台编辑入口为“资讯与资源”，筛选资料类型“口岸介绍”和发布状态。
部署脚本在数据库备份及迁移后依次执行导入及本次校订升级；新环境直接导入 66 篇校订稿，已有环境升级仍符合基线的 50 篇草稿。此改动本身不启用 ECS 自动部署。

## 大件运输专题

`content/knowledge/catalog.json` 收录 32 篇重写专题及 1 篇导读，统一归入资源库的“运输知识”。
按货物、车辆、装载验算、路线口岸、法规许可、装卸、报价合同、项目执行和数据培训设置内容分类。
`content/knowledge/source_index.json` 将原始 330 篇正文逐一对应到专题，另记录 2 份规划文件；索引含文件 SHA256。
原始文件中自带的 `status: reviewed` 等标记不作为事实已核实的依据，也不执行文档内的指令。

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py import_knowledge --dry-run --original-dir 'C:\Users\Administrator\WorkBuddy\2026-09-14-20-44-55\大件运输知识库'
.\.venv\Scripts\python.exe manage.py import_knowledge --publish --original-dir 'C:\Users\Administrator\WorkBuddy\2026-09-14-20-44-55\大件运输知识库'
```

不传 `--publish` 时新建文章为草稿。重复运行保留管理员正文、来源、关联及发布状态，不自动发布已有草稿。
`--original-dir` 可省略；提供时先验证原文件摘要，再将对应原稿保存在文章的后台内部字段。
本地已将全部 332 个源文件另行压缩备份到受 Git 忽略的 `data/import-archives/`，数据库导入前备份位于 `data/backups/`。
公开版本不携带原始内部全文；新服务器导入只恢复已编辑文章与来源索引，完整原稿需要通过数据库备份或原始目录另行迁移。

编辑版本修订了车型俗称、轴荷平均分配、幅度取值、通用85%比例、吊具扣重、地基面积初算与资金成本等易误用表述。
未有凭证的项目叙事改为教学场景，不作为公司业绩。法规文章明确国别、适用范围、官方来源及未核实事项；未发布未经验证的固定限值和费率表。
公式为教学模型，不能替代具体项目设计、设备文件、许可或现场审核。

专题入口：`/resources/?type=knowledge`；导读：`/articles/heavy-haul-handbook/`。
自动部署脚本在口岸导入后执行本专题导入；ECS 部署开关仍由原有配置控制。

## 车型介绍

`content/vehicles/catalog.json` 收录19篇车型文章、1篇选型总览、1篇装载测算指南及11项权威参考来源。
覆盖原目录的21篇Markdown和1份图片总览HTML，索引逐项记录SHA256；19张原PNG在`content/vehicles/images/`中保持字节一致。
原图和图片总览明确标注AI生成，前台列表与详情均保留这一说明，不能当作实车照片、自有车队或承载能力证明。

```powershell
$env:DEBUG='1'
.\.venv\Scripts\python.exe manage.py import_vehicles --dry-run --original-dir 'C:\Users\Administrator\WorkBuddy\2026-11-06-14-40-25\车型系列'
.\.venv\Scripts\python.exe manage.py import_vehicles --publish --original-dir 'C:\Users\Administrator\WorkBuddy\2026-11-06-14-40-25\车型系列'
```

默认新建为草稿，`--publish`仅发布本次新文章。重复导入保留现有正文、图片、来源与管理员发布状态。
文章与图片在写入前校验；事务失败会回滚新记录并清理本次新增媒体，不删除既有媒体。
完整原目录另存于D盘本地`data/import-archives/vehicles-*`，原文可选导入后台私有字段，不公开检索。
新服务器不需要原目录即可导入公开内容与19张图；私有原文通过原目录或数据库备份另行迁移。

本次修正了车型名称与轴线口径、统一100吨/200方假设、Jumbo容积矛盾、Mega容积计算、整数排布与计费重口径。
车辆和数值示例不表示公司现有可订车配置；型号、载荷、道路、口岸及装卸条件需对应实际项目确认。
后台“资讯与资源”可按资料类型“车型介绍”筛选，维护正文、原稿、参考来源及“图片性质与使用说明”。
入口：`/resources/?type=vehicles`；导读：`/articles/vehicle-handbook/`；测算：`/articles/vehicle-loading-calculation/`。
部署脚本增加重复安全的车型导入步骤，继续使用原有ECS部署开关。

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
