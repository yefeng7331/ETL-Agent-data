# ETL-Agent

面向企业异构数据集成场景的 ETL-Agent 项目。目标是让数据工程师以自然语言提出 ETL 需求，经受管生成、确定性校验和独立审批后，由 SeaTunnel 执行数据搬运，并对运行质量与审计证据形成闭环。

> **当前状态：文档基线及前五项后端功能（账户与项目权限、未就绪连接草稿、工作台现有数据、连接审计只读查询、非执行 Pipeline 草稿）已获用户验收。** PostgreSQL 真实联调、HTTPS 入口及浏览器验证仍待完成，前端和 ETL 全链路尚未实现。证据与阻断见 [实施状态](docs/IMPLEMENTATION_STATUS.md)。

## 首版目标

- 完成 MySQL → Doris 订单/用户宽表的周期增量批处理；在真实组件测试环境以非敏感数据验收。其他来源与生产部署仍属完整产品目标。
- 完成受管连接、只读元数据探查和脱敏采样。
- 使用 LangGraph 处理需求澄清与状态恢复，生成 EtlPlan 和 SeaTunnel HOCON，并通过确定性门禁冻结不可变版本。
- 通过 `prepare → approve → commit`、两名不同且非申请人的具名数据与安全审批、单次 Capability 和审计证据账本管理执行权限。
- 通过 Celery 与 SeaTunnel 搬运增量至 Doris 暂存区，由 Doris 构建完整影子宽表，完成质量分流、受管自动发布与回滚。
- 提供 Vue 控制台、Benchmark 评测集及至少一个端到端业务演示场景。

## 计划架构

FastAPI、LangGraph、Celery、PostgreSQL 和 Redis 构成控制面；Apache SeaTunnel 承担数据面搬运。测试环境的凭据规划由 Vault KV v2 管理，控制面只保存引用，控制面不直接搬运海量业务数据。

## 从哪里开始

1. 阅读已验收的 [首版 SPEC](docs/MVP_SPEC.md)，了解首版范围、规则和验收条件。
2. 阅读 [完整 PRD](PRD.md)，了解后续产品目标；查看 [已确认决策](docs/DECISIONS.md) 与 [实施状态](docs/IMPLEMENTATION_STATUS.md)。
3. 首版 Web API 的预期请求、响应和权限边界见[接口契约](docs/API_CONTRACT.md)；前端从登录到回滚的角色操作与状态见[前端全链路流程](docs/FRONTEND_END_TO_END_FLOW.md)；后端从连接登记到回滚的连续交接见[后端全链路流程](docs/BACKEND_END_TO_END_FLOW.md)。页面与服务端分段行为见[需求生成与版本冻结](docs/FLOW_01_DESIGN_FREEZE.md)、[准备单与审批执行](docs/FLOW_02_APPROVAL_COMMIT.md)、[运行质量与回滚](docs/FLOW_03_RUNTIME_ROLLBACK.md)。协作规则见 [AGENTS.md](AGENTS.md)。

## 首个后端功能：测试准备

当前后端有本地具名账户、服务端会话、可访问项目列表、逐请求项目校验、未就绪连接草稿、工作台现有数据、连接审计查询和非执行 Pipeline 草稿接口。管理员命令行负责初始化测试数据；没有注册页面。测试只使用非敏感 PostgreSQL 数据库。用户承担功能测试，但测试环境搭建、授权和故障排查的具名负责人尚未指定；真实数据库联调前须落实。以下步骤供环境就绪后使用，目前未在真实 PostgreSQL 上验证。

1. 准备 Python 3.11+、独立虚拟环境和可用的非敏感 PostgreSQL 测试库。安装依赖：`python -m pip install -e ".[test]"`。本步骤尚未在该测试环境验证。
2. 在当前 PowerShell 进程中交互输入测试库 DSN，避免把密码写入命令历史、仓库或截图：

   ```powershell
   $secureDsn = Read-Host 'Test DATABASE_URL' -AsSecureString
   $env:DATABASE_URL = [pscredential]::new('local', $secureDsn).GetNetworkCredential().Password
   Remove-Variable secureDsn
   ```

3. 在**已获准写入的专用测试库**执行 `python -m etl_agent.bootstrap init-db`。随后执行 `python -m etl_agent.bootstrap project alpha Alpha`、`python -m etl_agent.bootstrap project beta Beta`、`python -m etl_agent.bootstrap account alice`、`python -m etl_agent.bootstrap member alice alpha Maker`。账户命令通过终端交互输入并复核密码；至少 15 字符，支持 64 字符以上，拒绝离线弱密码表及账户/现有项目名称。不要把密码写进命令参数。`beta` 不给 `alice` 成员关系，用于验证隔离。需要测试审批角色时由管理员另建具名账户和成员关系，不能把 Maker 视为审批人。
4. 运行 `python -m unittest discover -s tests -v` 检查本地接口与规则测试。这些测试使用内存替身，不连接 PostgreSQL。

## 首个后端功能：用户自测

API 仅接受 HTTPS。可在现有受信 TLS 入口后运行 `python -m uvicorn etl_agent.app:app --host 127.0.0.1 --port 8000`；入口须正确传递 HTTPS scheme。直连 `http://127.0.0.1:8000/api/v1/...` 会收到 `HTTPS_REQUIRED`。如果没有已获准的 HTTPS 入口，先记录真实 HTTP 验收阻断，不通过关闭安全 Cookie 或 HTTPS 限制绕过。FastAPI 的 `/docs` 和 `/openapi.json` 可用于查看接口说明，实际请求须通过 HTTPS。

在 HTTPS 地址中按顺序检查，记录时间、测试账号、项目 ID、请求路径、状态码和脱敏后的响应摘要；不要保存密码、Cookie、CSRF 值或 DSN：

1. 未登录请求 `GET /api/v1/projects` → `401`。`POST /api/v1/session` 提交 `alice` 和交互设置的密码 → `200`，响应只含账户及 CSRF 值，浏览器收到 `HttpOnly; Secure; SameSite=Lax` 会话 Cookie；不回显密码或会话标识。CSRF 值用于下一步修改类请求，记录证据时请遮蔽。
2. `GET /api/v1/session` → 当前账户；`GET /api/v1/projects` → 仅 `alpha`；`GET /api/v1/projects/alpha/access` → `200`；`GET /api/v1/projects/beta/access` → `404` 且不含 `beta` 内容。成员关系变动后的实时生效目前只有接口替身测试，真实数据库场景待后续受管成员管理流程验证。
3. `DELETE /api/v1/session` 不带或带错 `X-CSRF-Token` → `403`；带会话响应的 CSRF 值 → `204`；再请求项目列表 → `401`。跨站 `Origin` 的修改请求应被拒绝。
4. 连续 5 次错误密码后，正确密码仍应得到通用 `401`；15 分钟限制期后可登录。空闲 15 分钟或会话总长 8 小时后请求会话应得到 `401`。这些时间边界可使用受控测试时钟或真实等待检查，不要以本地替身测试代替 PostgreSQL 结果。
5. 检查 `/openapi.json` 为 OpenAPI 3.1，包含会话、项目列表、项目访问、工作台现有数据、未就绪连接草稿及连接审计查询接口；其他业务接口仍是文档契约，尚未实现。

本地弱密码文件为版本化公开样例集，来源与范围见 [密码表说明](etl_agent/weak_passwords_v1.md)。不得将这份有限离线表理解为覆盖全部已泄露密码。自测结果、缺陷及真实数据库联调证据应写入 [实施状态](docs/IMPLEMENTATION_STATUS.md)，功能验收须由用户明确确认。

## 第二项后端功能：未就绪连接草稿自测

沿用上面的非敏感测试库、`alpha` 项目、`alice` 的 Maker 成员关系及受信 HTTPS 入口。在 `/docs` 或同源 HTTPS API 工具中登录，使用返回的 `csrf_token` 作为修改请求的 `X-CSRF-Token`；记录证据时遮蔽 Cookie、CSRF 和内部主机信息。当前没有 Vault 别名登记或真实探查，草稿始终为 `draft_unready`。

1. 向 `POST /api/v1/projects/alpha/connections` 提交 `{"name":"Order source","kind":"mysql_source","host":"mysql.internal","port":3306,"database_name":"orders"}`，预期 `201`、新连接 ID、`state=draft_unready`、`credential_alias_id=null`、`missing_fields=["credential_alias_id"]`，响应头含 `X-Request-ID`；不带 CSRF 预期 `403`。
2. `GET /api/v1/projects/alpha/connections` 及 `GET /api/v1/projects/alpha/connections/{connection_id}` 只返回本项目 Maker 有权读取的草稿；`PATCH` 可只提交 `{"host":"new.internal"}`，预期 `200` 且更新时间变化。提交 `password`、`username`、`vault_path` 等额外字段或把账号密码拼成 URL 主机，预期 `400`，错误响应不回显输入。
3. 用 `beta` 项目路径读写 `alpha` 的连接，预期 `404` 且无草稿内容。用只有 `Auditor` 角色的独立具名测试账户访问 `alpha` 草稿，预期 `403`；可通过管理员命令行新增该账户并执行 `python -m etl_agent.bootstrap member <username> alpha Auditor`。两种情况均不得改变草稿。
4. 对草稿调用 `POST /api/v1/projects/alpha/connections/{connection_id}/probes` 并携带 CSRF，预期 `422`/`SECRET_ALIAS_UNAVAILABLE`，无任务 ID、无外部连通性测试或 Profile。用数据库只读查询核对 `audit_events`：每次成功创建或修改各有一条同项目、具名账户、资源 ID 与响应 `X-Request-ID` 一致的事件；失败请求无连接变更。真实事务和审计持久化目前未验证，须在已授权测试库检查。

本项只保存你确认的五类非密字段；内部主机信息会保存在项目范围的 PostgreSQL 记录中。别名就绪、Vault Secret 读取、异步探查、字段分类与前端页面仍待后续独立实现和验证。

## 第三项后端功能：工作台现有数据自测

沿用前述非敏感测试库、受信 HTTPS 入口、`alpha` 的 Maker `alice` 和单独的 `Auditor` 测试账户。使用各自的服务端会话请求 `GET /api/v1/projects/alpha/workbench`；记录测试时间、账号、项目、状态码和脱敏响应，遮蔽 Cookie、CSRF 及内部地址。

1. 未登录请求预期 `401`；`alice` 请求 `beta` 工作台预期 `404`，不含 `beta` 项目事实。`alice` 请求 `alpha` 预期 `200`，`project` 为 `alpha` 与 Maker 角色，`allowed_actions` 含 `project.read`、`workbench.read`、`connections.read`、`connections.create`、`connections.update`。
2. 在 `alpha` 尚无草稿时，Maker 的 `connections.draft_unready_count` 应为 `0`，`href` 为 `/api/v1/projects/alpha/connections`；按上一节成功创建一条草稿后再次请求，数量应增加到 `1`。若测试库已有草稿，先记录基数并核对增加一条后的差值，勿为获得零值删除数据。两次响应的 `unavailable_sections` 都应包含 `pipelines`、`preparations`、`runs`、`inbox`，不出现这些业务的虚假数量。
3. `Auditor` 请求 `alpha` 预期得到 `project.read`、`workbench.read`、`audit_events.read`，`connections` 为 `null`，响应不含 Maker 草稿数量、主机或数据库名；其直接访问连接列表仍应被拒绝。撤销成员关系后再次请求工作台应为 `404`，该检查应在专用测试账户上进行，不影响其他测试。

本地接口测试只使用内存替身。真实 PostgreSQL 查询、成员并发变更和 HTTPS 请求须由用户在环境就绪后记录独立证据；工作台没有前端页面，待办、Pipeline、准备单和运行概况尚未接入。

## 第四项后端功能：连接审计只读查询自测

沿用非敏感测试库与受信 HTTPS 入口，准备本项目 Maker `alice` 和独立的具名 `Auditor` 账户。按第二项步骤由 Maker 创建、修改一条连接草稿，保存两个响应中的 `X-Request-ID`，记录证据时遮蔽 Cookie、CSRF 和内部地址。

1. 未登录请求 `GET /api/v1/projects/alpha/audit-events` 预期 `401`；Maker 但非 Auditor 请求预期 `403`；无 `beta` 成员关系的 Auditor 请求 `beta` 预期 `404`。
2. Auditor 请求 `GET /api/v1/projects/alpha/audit-events` 预期 `200`，`items` 出现本项目 `connection.created` 和 `connection.updated`，各项只含事件 ID、项目 ID、操作者 ID、动作、连接 ID、请求 ID 和创建时间。与两次写入的 `X-Request-ID` 核对；响应不含主机、数据库名或任何凭据。可用 `action=connection.created` 和具名账户 UUID `actor_id` 验证过滤；非法动作或跨项目游标预期 `400`。
3. 若有超过 50 条本项目连接事件，首页最多 50 条，并用 `next_cursor` 读取下一页，不重复事件。只在专用测试账户上验证撤销 Auditor 成员关系后再次查询变成 `404`；不为凑页数向测试库批量写入。

当前尚无前端审计页面，也没有审批、Commit、发布、回滚和评测事件。接口替身测试通过不代表 PostgreSQL 的分页 SQL、事务隔离或 HTTPS 真实联调已通过；测试环境就绪后将实际状态码、脱敏响应和数据库只读核对结果记入 [实施状态](docs/IMPLEMENTATION_STATUS.md)。

## 第五项后端功能：非执行 Pipeline 草稿自测

沿用上述非敏感测试库、Maker `alice` 和受信 HTTPS 入口。先按第二项步骤在 `alpha` 创建一条 `mysql_source` 与一条 `doris_target` 未就绪连接，记下两条响应的 ID；接口路径均以 `/api/v1` 开头。只记录脱敏后的请求/响应、状态码、时间和 `X-Request-ID`，遮蔽 Cookie、CSRF 与内部地址。

1. Maker 携带会话 Cookie 与 `X-CSRF-Token`，请求 `POST /api/v1/projects/alpha/pipelines`，正文填写 `source_connection_id`、`target_connection_id`、`order_table`、`user_table` 和 `cycle_description`。预期 `201`、`Location`、`X-Request-ID`；响应 `state=draft_unready`、`revision=1`，`proposed_quality_thresholds` 与 `proposed_runtime_budget` 均为 `null`。周期文字只保存说明，不触发排程。`GET Location` 预期返回同一草稿；携带 CSRF 的 `PATCH Location` 修改周期说明后预期修订版递增，并产生独立请求标识。
2. 不带 CSRF 的写入预期 `403`；传入密码、Vault 路径、质量阈值、预算或任意额外字段预期 `400` 且不回显敏感值。源/目标类型互换、使用不存在或 `beta` 项目连接 ID 预期 `404` 且没有新草稿；非 Maker 对 `alpha` 的访问预期 `403`，无成员关系访问 `beta` 预期 `404`。不要尝试真实探查或执行。
3. 用有权限的数据库只读查询核对 Pipeline 行的项目、连接引用、修订版与两条 `pipeline.created` / `pipeline.updated` 审计事件的操作者和请求 ID；当前 Auditor API 只展示连接事件，不能据此推断 Pipeline 审计缺失。工作台的 Pipeline 概况仍标“未接入”。生成、冻结、Prepare、排程和运行接口尚未实现，不能把草稿当作可执行配置。

当前自动化测试只用内存替身；PostgreSQL 外键/事务、并发变更、真实 HTTPS 调用及页面验证仍 `UNVERIFIED`。环境就绪后将实际证据补入 [实施状态](docs/IMPLEMENTATION_STATUS.md)；本项已获用户功能验收。

## 需求与协作

产品需求变更写入 [PRD](PRD.md)；涉及首版时同步维护 [SPEC](docs/MVP_SPEC.md)，并明确首版或后续范围。功能落地时同步核对相关流程、[全局协作规范](AGENTS.md)、[实施状态](docs/IMPLEMENTATION_STATUS.md) 和本 README；仅据实际验证更新功能与使用说明。维护人与支持渠道尚未指定，远程仓库地址尚未配置。
