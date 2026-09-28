# 实施与验收状态

- 更新日期：2026-09-28。
- 文档基线：用户已明确接受 v0.2 文档基线；[MVP_SPEC](MVP_SPEC.md) 为首版执行权威。D-56 至 D-59 的分项范围已逐题确认；前五项后端功能均获用户验收。已同步 [PRD](../PRD.md)、[DECISIONS](DECISIONS.md)、[API_CONTRACT](API_CONTRACT.md)、[前端流程](FRONTEND_END_TO_END_FLOW.md)、[后端流程](BACKEND_END_TO_END_FLOW.md) 和 [README](../README.md)。文档验收与具体功能、真实联调及运行验收分别记录。
- 仓库：本地 Git 初始化，尚无提交或远程地址。未修改 `.env`、密钥、证书或 CI/CD 配置，未提交或推送。
- 文档自检：13 个 Markdown 文件中的 128 个本地链接均有目标，16 个锚点均匹配标题；已核对文档验收、规则与推迟事项的状态表述。链接检查不构成功能验收。

## 当前功能：本地账户、会话与项目权限

| 项目 | 当前证据与状态 |
| --- | --- |
| 需求与通过标准 | [SPEC 角色与业务规则](MVP_SPEC.md#角色与业务规则)：具名账户、受管密码、服务端会话、安全 Cookie/CSRF、项目列表与逐请求项目成员校验；[接口契约](API_CONTRACT.md#1-登录项目与工作台)给出请求与响应。 |
| 代码 | [API](../etl_agent/app.py)、[PostgreSQL 存储](../etl_agent/db.py)、[安全规则](../etl_agent/security.py)、[数据库结构](../etl_agent/schema.sql)、[管理员命令行](../etl_agent/bootstrap.py)、[离线弱密码表](../etl_agent/weak_passwords_v1.md)。本项实现会话、项目列表和项目访问校验；工作台另见下表，审批与 ETL 仍未实现。 |
| 静态与自动化验证 | `python -m compileall -q etl_agent tests` 通过；`python -m unittest discover -s tests -v` 6/6 通过，覆盖登录/登出、锁定与时限、Cookie/CSRF、跨项目与成员撤销的接口边界、敏感输入不回显、HTTPS 拒绝及 OpenAPI 3.1。测试使用内存替身，不连接 PostgreSQL；OpenAPI 生成不证明真实数据库可用。 |
| 真实环境与运行 | PostgreSQL 驱动未在当前解释器安装；用户稍后提供非敏感测试库，测试环境搭建、授权和故障排查的具名负责人尚未指定。数据库建表、密码哈希持久化、真实并发锁定/事务、HTTPS 入口、浏览器和前端联调均 `UNVERIFIED`。不得据当前测试宣称真实运行通过。 |
| 用户功能验收 | 用户于 2026-09-28 明确回复“验收通过，请继续下一项”，首个账户、会话与项目权限功能记为用户验收通过。该确认不构成真实 PostgreSQL、HTTPS 入口、浏览器或前端联调的技术证据；这些项目仍待按 [README 自测流程](../README.md#首个后端功能用户自测)核实。 |

## 当前功能：项目内未就绪连接草稿

| 项目 | 当前证据与状态 |
| --- | --- |
| 需求与通过标准 | [SPEC 角色与业务规则](MVP_SPEC.md#角色与业务规则)与 D-56：项目 Maker 保存五类非密元数据、逐次项目权限校验、无别名不得探查；Web 业务写入有具名审计。接口输入与阻断见 [API 契约](API_CONTRACT.md#2-凭据别名连接与只读探查)。 |
| 代码 | [API](../etl_agent/app.py)实现草稿创建、列表、详情、部分修改和明确探查阻断；[PostgreSQL 存储](../etl_agent/db.py)在事务中复核 Maker 成员关系并写草稿与审计；[结构](../etl_agent/schema.sql)新增连接与审计表。没有接入 Vault、源/目标库或探查 Worker。 |
| 静态与自动化验证 | `python -m compileall -q etl_agent tests` 通过；`python -m unittest discover -s tests -v` 7/7 通过，新增测试覆盖字段拒绝、CSRF、跨项目、非 Maker、成员撤销、草稿读写、审计请求标识和无别名探查阻断。测试使用内存替身，未验证 PostgreSQL SQL、事务或审计持久化。 |
| 真实环境与运行 | PostgreSQL 测试环境与具名负责人仍未就绪；真实数据库建表、权限并发、持久化、HTTPS 请求、外部无副作用及浏览器操作均 `UNVERIFIED`。 |
| 用户功能验收 | 用户于 2026-09-28 明确回复“验收通过，允许进入下一功能”，第二项连接草稿功能记为用户验收通过。该确认不构成真实 PostgreSQL、HTTPS 入口或浏览器联调证据；这些项目仍待按 [README 草稿自测](../README.md#第二项后端功能未就绪连接草稿自测)核实。 |

## 当前功能：项目工作台现有数据

| 项目 | 当前证据与状态 |
| --- | --- |
| 需求与通过标准 | D-57 与 [SPEC](MVP_SPEC.md#角色与业务规则)：返回本项目及已实现操作的 `allowed_actions`；仅 Maker 可见本项目未就绪连接草稿数量与入口；尚未接入的概况明确标示，不填零。响应和权限边界见 [API 契约](API_CONTRACT.md#1-登录项目与工作台)。 |
| 代码 | [API](../etl_agent/app.py)新增 `GET /api/v1/projects/{project_id}/workbench`；[PostgreSQL 存储](../etl_agent/db.py)查询当前成员角色，并仅在 Maker 时统计本项目 `draft_unready` 连接。没有前端页面、待办或运行记录。 |
| 静态与自动化验证 | `python -m compileall -q etl_agent tests` 通过；`python -m unittest discover -s tests -v` 8/8 通过。新增内存替身测试覆盖未登录、跨项目、Maker 零值与建草稿后计数、Auditor 不可见及成员撤销；OpenAPI 包含工作台路径。测试不连接 PostgreSQL。 |
| 真实环境与运行 | PostgreSQL 测试环境与具名负责人未就绪；真实 SQL、事务和成员并发变更、HTTPS 请求及浏览器页面均 `UNVERIFIED`。测试步骤见 [README 工作台自测](../README.md#第三项后端功能工作台现有数据自测)。 |
| 用户功能验收 | 用户于 2026-09-28 明确回复“验收通过，允许进入下一功能”，第三项工作台现有数据功能记为用户验收通过。该确认不构成真实 PostgreSQL、HTTPS 或页面联调证据，仍须按 [README 自测](../README.md#第三项后端功能工作台现有数据自测)核实。 |

## 第四项：项目 Auditor 连接审计只读查询

| 项目 | 当前证据与状态 |
| --- | --- |
| 需求与通过标准 | D-58 与 [SPEC](MVP_SPEC.md#角色与业务规则)：仅本项目 Auditor 可读现有连接创建/修改事件；逐请求鉴权、分页、过滤，不返回连接详情或 Secret。接口见 [API 契约](API_CONTRACT.md#6-审计与-benchmark)。 |
| 代码 | [API](../etl_agent/app.py)新增 `GET /api/v1/projects/{project_id}/audit-events`，工作台为 Auditor 增加 `audit_events.read`；[存储](../etl_agent/db.py)在查询事务内复核活动账户与 Auditor 成员关系，按创建时间和事件 ID 倒序分页。沿用现有连接写入的审计表，未增加外部依赖或写入动作。 |
| 静态与自动化验证 | `python -m compileall -q etl_agent tests` 通过；`python -m unittest discover -s tests -v` 9/9 通过。新增内存替身测试覆盖未登录、非 Auditor、跨项目、无效游标/动作、事件类型及敏感信息过滤、分页无重复、成员撤销；OpenAPI 3.1 包含该路径。测试不连接 PostgreSQL。 |
| 真实环境与运行 | PostgreSQL 测试库及具名环境负责人尚未就绪；真实 SQL、事务/并发权限、HTTPS 请求与浏览器页面均 `UNVERIFIED`。用户自测步骤见 [README](../README.md#第四项后端功能连接审计只读查询自测)。 |
| 用户功能验收 | 用户于 2026-09-28 明确回复“验收成功，请进入下一项”，第四项连接审计只读查询记为用户验收通过。此确认不构成真实 PostgreSQL、HTTPS 或页面联调证据，仍须按 [README 自测](../README.md#第四项后端功能连接审计只读查询自测)核实。 |

## 第五项：项目内非执行 Pipeline 草稿

| 项目 | 当前证据与状态 |
| --- | --- |
| 需求与通过标准 | D-59 与 [SPEC](MVP_SPEC.md#角色与业务规则)：仅本项目 Maker 维护引用本项目 MySQL 源/Doris 目标的未就绪草稿；保存订单/用户表及非排程的周期说明，阈值与预算保持未填写。请求及错误见 [API 契约](API_CONTRACT.md#3-pipeline澄清候选与冻结)。 |
| 代码 | [API](../etl_agent/app.py)提供草稿创建、详情、部分修改；[存储](../etl_agent/db.py)在写入事务内复核 Maker、连接项目与类型并追加审计；[结构](../etl_agent/schema.sql)新增 Pipeline 表。无列表、生成、冻结、Prepare、排程或执行能力；工作台 Pipeline 概况仍未接入。 |
| 静态与自动化验证 | `python -m compileall -q etl_agent tests` 通过；`python -m unittest discover -s tests -v` 10/10 通过。新增内存替身测试覆盖未登录、CSRF、项目与角色隔离、错误/跨项目连接、扩展字段拒绝、创建/读取/修改、修订版、审计请求标识及 OpenAPI 路径。测试未连接 PostgreSQL。 |
| 真实环境与运行 | PostgreSQL 测试库及具名环境负责人尚未就绪；真实外键、事务、并发连接变更、HTTPS 请求、页面及排程行为均 `UNVERIFIED`。实际自测步骤见 [README](../README.md#第五项后端功能非执行-pipeline-草稿自测)。 |
| 用户功能验收 | 用户于 2026-09-28 明确回复“验收成功，请进行下一项”，第五项非执行 Pipeline 草稿记为用户验收通过。此确认不构成真实 PostgreSQL、HTTPS 或页面联调证据，仍须按 [README 自测](../README.md#第五项后端功能非执行-pipeline-草稿自测)核实。 |

## 后续链路与明确阻断

- 风险 P0–P3、迟到/并发读取、发布后回滚水位和前轮准备单受管关闭规则已确认但尚无代码及真实验证；对应业务链路仍阻断。
- Benchmark 达标值须在版本化测试集与判定口径确认后设定；各 Pipeline 质量阈值和运行预算须在首次 Prepare 前获批；正式容量负载、环境规格及完成时限须在容量验收前明确。参考负载非正式门槛，也无实测。
- 脱敏样例查看/下载上限未批准前功能阻断；旧版清理须先确定保留、存储与批准策略，现阶段不自动清理。
- 多 Provider 适配与模型自主修改/启用安全策略推迟；进入实施前另定接口、审核与回滚控制。首版单 Provider 仍须在相关实现前选定。pen.dev 画板及视觉基准推迟到页面视觉实施前确认。
- PostgreSQL 测试环境具名负责人、凭据轮换、源/目标数据库、控制面环境及 SeaTunnel 连接器负责人尚未指定，分别在真实联调、真实凭据接入或相关环境实施前阻断；长期生产运维负责人须在生产部署前指定。用户负责首版测试验收，不自动承担环境或运维责任。
- 第五项周期只存文字、质量阈值和预算保持未填写；调度规则、指标字段与单位、审批流程确认前不得接入 Beat 或首次 Prepare。连接类型/归属在草稿写入时核对；连接后续变化及真实 PostgreSQL 并发尚未验证，任何未来执行入口须重新核对引用。
- 前端、LangGraph、Celery/Beat、Redis、Vault、SeaTunnel、MySQL/Doris 增量、双审批、发布、回滚及端到端运行均未实现或联调；页面验收与运行验收均未进行。前五项功能的用户验收见上表。
