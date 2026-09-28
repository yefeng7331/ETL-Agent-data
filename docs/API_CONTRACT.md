# 首版接口契约：Web 控制台 ↔ FastAPI

- 状态：v0.2 文档基线及前五项后端功能已获用户验收；D-59 非执行 Pipeline 草稿已有代码与自动化验证。真实联调另见 [实施状态](IMPLEMENTATION_STATUS.md)。接口实现与 OpenAPI 覆盖情况以实施状态为准。
- 权威：[MVP_SPEC](MVP_SPEC.md) 是首版业务、技术约束与验收的唯一执行依据；本文固定其 Web API 交接，不新增审批豁免、质量阈值或生产范围。完整产品目标见 [PRD](../PRD.md)，服务端顺序见 [后端全链路流程](BACKEND_END_TO_END_FLOW.md)。
- 范围：首版 Vue 浏览器控制台调用 FastAPI。Celery、Beat、Tool Broker、Vault、SeaTunnel 和 Doris 之间的命令与数据交接属于内部受管流程，不作为第三方开放 API。后续实现按本文生成或核对 OpenAPI 3.1；路径、字段和错误语义变更须同步本文、SPEC 与受影响流程。

## 通用契约

| 项目 | 首版约定 |
| --- | --- |
| 基础路径与格式 | `/api/v1`，HTTPS，JSON；路径中的 ID 为不透明字符串，字段名使用 `snake_case`，时间使用带时区的 ISO 8601。具体 ID 生成方式不向客户端承诺。 |
| 登录态 | 本地具名账户由管理员命令行初始化，无自助注册；密码至少 15 字符、允许至少 64 字符，并经过离线版本化弱密码表及账户/项目上下文校验，只存安全哈希。登录后使用服务端会话；Cookie 为 `HttpOnly`、`Secure`、`SameSite=Lax`。登录发新会话标识，登出使会话失效；空闲 15 分钟或总计 8 小时即失效。单账户 15 分钟内连续失败 5 次后限制登录 15 分钟。修改类请求携带会话绑定的 CSRF 值；浏览器不保存可读的长期访问令牌。 |
| 项目与权限 | 除会话和可访问项目列表外，业务资源统一处于 `/projects/{project_id}` 下。服务端逐次校验账户、项目成员关系、角色、资源归属与操作权限；工作台返回 `allowed_actions` 供页面展示，不能代替服务端鉴权。跨项目资源不返回其内容。 |
| 成功响应 | 会话与项目发现接口按下表返回，不附业务资源状态时间；其他可变业务资源读取返回当前服务端事实及 `updated_at`，不可变审计事件返回 `created_at`；创建或提交返回新记录 ID、状态与查询链接。耗时操作返回 `202 Accepted`、`task_id` 与查询链接；最终业务对象以查询接口为准。列表返回 `items` 和服务端分页游标，过滤条件仅在授权项目内生效。 |
| 冲突与重试 | 会话续答使用 `If-Match` 绑定所见修订版；不符返回 `412` 与最新记录引用。Commit 以 Preparation ID 为唯一执行边界；同一单重复提交返回原 `ExecutionRun` 或原拒绝事实。回滚提交绑定预览操作 ID 与预览的正式版本。超时或断线先查服务端记录，不据此判断操作失败。 |
| 错误响应 | 统一形如 `{"error":{"code":"...","message":"...","request_id":"...","resource_ref":"...","retryable":false}}`；`message` 可展示，`code` 稳定供页面分支，`request_id` 用于受控诊断。不得返回 Secret、原始敏感数据、内部栈或未经授权的资源事实。 |

常用 HTTP 状态：`200` 已有或查询结果，`201` 新资源，`202` 已受理异步动作，`204` 登出，`400` 格式不合法，`401` 未登录，`403` 无权操作，`404` 项目内资源不存在或不可见，`409` 业务状态/冻结事实冲突，`412` 会话修订版过期，`422` 已确认的业务门禁阻断，`503` 依赖暂不可用。错误码至少区分 `PROJECT_FORBIDDEN`、`SECRET_ALIAS_UNAVAILABLE`、`PROFILE_UNCLASSIFIED`、`SCHEMA_CHANGED`、`VALIDATION_BLOCKED`、`RISK_POLICY_UNRESOLVED`、`PREPARATION_STALE`、`APPROVAL_INCOMPLETE`、`APPROVAL_CONFLICT`、`CYCLE_OUT_OF_ORDER`、`RUN_BUDGET_EXCEEDED`、`QUALITY_BLOCKED`、`PUBLICATION_CONFLICT`、`ROLLBACK_PREVIEW_STALE`、`DEPENDENCY_UNAVAILABLE`；具体数值阈值不在错误码中写死。

所有 Web 项目业务写入记录具名操作者、项目、请求追踪标识与审计事件；登录会话和管理员命令行初始化测试数据不属于 Web 项目业务写入。项目业务资源返回 `state`、`updated_at` 与有关记录 ID；不可变审计事件只返回 `created_at`，无状态或更新时间。前端不能仅据 HTTP 已受理推断探查完成、作业已运行、质量通过或正式版已发布。字段中出现 `credential_alias_id` 只表示管理员预置的授权别名，不得返回 Vault 原始路径、Secret 明文、Capability 或可重放的内部命令。

通用字段约定：创建/变更请求仅包含本节各资源列出的业务字段；除会话、项目发现和不可变审计事件外，业务资源成功响应至少包含对应资源 ID、`state`、`updated_at`，异步响应再包含 `task_id` 与同项目内的查询链接。`GET /projects/{project_id}/tasks/{task_id}` 返回任务类型、状态、关联业务资源 ID、可展示的失败码及完成时间；查询失败或断线后以服务端业务资源与任务记录交叉核对。`GET` 列表响应统一含 `items` 和游标；页面不得从游标、工作台操作清单或请求成功状态推断审批已通过。各表中的复合方法/路径分别表示独立 REST 操作，后续 OpenAPI 3.1 须逐一列明请求体与响应 Schema。

错误码与恢复动作：`400`/`HTTPS_REQUIRED` 改用受信 HTTPS 入口；`401` 会话失效后重登并重查原记录；`404`/`PROJECT_FORBIDDEN` 停止该项目操作且不泄露项目存在性；其他已授权业务操作的 `403` 表示无权执行；`409`/`SCHEMA_CHANGED`、`PREPARATION_STALE`、`PUBLICATION_CONFLICT`、`ROLLBACK_PREVIEW_STALE` 重读相应事实后重新探查、准备或预览；`409`/`CYCLE_OUT_OF_ORDER` 等待或受管关闭前轮；`412` 重读澄清会话修订版；`422`/`PROFILE_UNCLASSIFIED`、`VALIDATION_BLOCKED`、`RISK_POLICY_UNRESOLVED`、`APPROVAL_INCOMPLETE`、`QUALITY_BLOCKED` 保留阻断并按对应治理流程处理；`503`/`DEPENDENCY_UNAVAILABLE` 查询服务端事实后再决定是否重试。`SECRET_ALIAS_UNAVAILABLE`、`RUN_BUDGET_EXCEEDED` 和 `APPROVAL_CONFLICT` 按同一错误封装返回。不得以自动重试越过门禁。

## 1. 登录、项目与工作台

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `POST /session` | 匿名用户提交 `username`、`password` → 服务端会话 Cookie、`account`（`id`、`username`）和 `csrf_token`；响应不回显密码。 | 失败及账户限制均返回通用认证错误，不透露账户是否存在；登录成功轮换本次会话标识。 |
| `GET /session`、`DELETE /session` | 已登录用户读取 `account` 和 `csrf_token`；登出请求携带 `X-CSRF-Token`，使服务端会话失效。 | 会话过期返回 `401`，页面重新登录后从业务记录恢复。 |
| `GET /projects` | 已登录用户 → `items`（可访问项目的 `id`、`name`、`roles`）与 `next_cursor`；不返回其他项目。 | 空列表不能自动选择项目。 |
| `GET /projects/{project_id}/access` | 项目成员 → `project`（当前项目的 `id`、`name`、`roles`）；首个后端功能用于逐请求校验项目成员关系。 | 非成员或项目不存在统一返回 `404`/`PROJECT_FORBIDDEN`，不泄露项目内容；后续项目业务接口继续各自逐次鉴权。 |
| `GET /projects/{project_id}/workbench` | 项目成员 → `project`（`id`、`name`、`roles`）和已实现操作的 `allowed_actions`。当前所有成员有 `project.read`、`workbench.read`；Maker 另有 `connections.read`、`connections.create`、`connections.update`，并收到 `connections: {draft_unready_count, href}`，其中 `href` 指向本项目连接列表；Auditor 另有 `audit_events.read`。非 Maker 的 `connections` 为 `null`，不返回草稿数量。`unavailable_sections` 当前为 `pipelines`、`preparations`、`runs`、`inbox`，表示尚未接入，不以 0 代替。 | 未登录 `401`，非成员项目 `404` 且不泄露项目内容。切换项目后重新查询；`allowed_actions` 仅供界面展示，所有业务请求仍逐次鉴权。完整概况待对应记录实现后接入。 |

## 2. 凭据别名、连接与只读探查

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `GET /projects/{project_id}/credential-aliases` | Maker → 此项目获授权的 MySQL/Doris 别名 ID、用途与可用状态；不含 Vault 路径或凭据。 | 别名撤销后既有草稿可读，探查与后续受控操作被阻断。 |
| `GET/POST /projects/{project_id}/connections`、`GET/PATCH /projects/{project_id}/connections/{connection_id}` | Maker 在项目内登记源/目标类型、非密连接元数据及 `credential_alias_id`，或保存缺别名的 `draft_unready`；读取列表/详情和缺项。草稿输入仅含 `name`、`kind`（`mysql_source`/`doris_target`）、`host`、`port`、`database_name`，均必填；PATCH 可部分更新。响应含上述字段、ID、项目 ID、`state`、创建/更新时间、空 `credential_alias_id` 和 `missing_fields`。 | 严格拒绝用户名、密码、Vault 路径及任意额外字段；当前只实现无别名草稿，服务端逐次校验 Maker 和项目归属，写入与审计同事务。别名登记/校验和就绪转换待真实 Vault 接入；草稿无别名时不得探查。修改影响已冻结事实时旧版本/准备单失效。 |
| `POST /projects/{project_id}/connections/{connection_id}/probes` | Maker 发起授权的连通性、Schema、安全统计探查 → 未来就绪连接返回 `202`、`task_id`。 | 当前仅针对有权访问的未就绪草稿返回 `422`/`SECRET_ALIAS_UNAVAILABLE`，无外部调用；别名缺失、越权或依赖失败不标记 Profile 可用；探查不得写目标库。 |
| `GET /projects/{project_id}/tasks/{task_id}`、`GET /projects/{project_id}/profiles/{profile_id}` | 有权角色读取任务 `queued/running/succeeded/failed/blocked`、关联 Profile；Profile 返回 Schema、统计、字段分类状态及版本指纹。 | 未分类字段的样本值一律缺省；任务失败保留原因与关联记录。 |
| `POST /projects/{project_id}/profiles/{profile_id}/classification-proposals`、`POST /projects/{project_id}/classification-proposals/{proposal_id}/decision` | Maker 对字段提出分类/脱敏建议；安全审批人对同一 Profile/Schema 版本批准或驳回并填写理由 → 决定与待办状态。 | 决定绑定字段与 Schema 版本；新增或变化字段恢复待审并暂停其样本，未变化字段沿用有效确认。未确认阻断 Prepare。 |
| `GET /projects/{project_id}/profiles/{profile_id}/samples` | 获授权角色读取经服务端脱敏的有界样本及分类状态。 | 未分类、越权或规则失效时无样本值；不得以空字段伪装已确认。 |

## 3. Pipeline、澄清、候选与冻结

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `POST /projects/{project_id}/pipelines`、`GET/PATCH /projects/{project_id}/pipelines/{pipeline_id}` | 当前仅 Maker 创建、读取、修改本项目 `draft_unready` 草稿。创建必填 `source_connection_id`、`target_connection_id`（UUID）、`order_table`、`user_table`、`cycle_description`；修改仅接收上述字段的非空子集。源须为本项目 `mysql_source`，目标须为本项目 `doris_target`，允许连接仍未就绪。响应返回上述字段、`id`、`project_id`、`state`、递增 `revision`、时间戳，以及固定为 `null` 的 `proposed_quality_thresholds`、`proposed_runtime_budget`。创建 `201` 并返回 `Location`；成功写入返回 `X-Request-ID` 并记录同事务审计。周期只作文字说明，不触发排程。 | 未登录 `401`，非项目 `404`，本项目非 Maker `403`；CSRF/Origin 失败 `403`；空修改、任意扩展字段（含 Secret）、空值或格式错误 `400`；不存在、跨项目或类型不符的连接 `404`，不写入草稿/审计。当前无生成、冻结、Prepare 或执行入口。拟议阈值与预算字段/口径、周期触发时区及漏跑规则须在后续相关能力实施前确认；首次 Prepare 前须批准该 Pipeline 实际数值。 |
| `POST /projects/{project_id}/pipelines/{pipeline_id}/design-sessions`、`GET /projects/{project_id}/design-sessions/{session_id}` | Maker 提交自然语言需求与关键项表单 → `202`、会话 ID 和生成 `task_id`；查询会话取得修订版、当前问题及候选链接。 | 生成与澄清状态由异步任务和会话查询恢复；缺关键语义返回待澄清事实，不推断模型已确认。 |
| `POST /projects/{project_id}/design-sessions/{session_id}/turns`、`POST /projects/{project_id}/design-sessions/{session_id}/revisions` | Maker 续答或对候选提出修改要求，携带 `If-Match` → 新会话修订版及异步 `task_id`；修改要求生成新候选。 | 并发旧修订版返回 `412`；语义变化必须由 Maker 再确认，失败候选不能冻结。 |
| `GET /projects/{project_id}/candidates/{candidate_id}`、`POST /projects/{project_id}/candidates/{candidate_id}/validate` | Maker 读取 EtlPlan/HOCON/DAG、映射、差异与候选历史；独立静态校验返回阻断项和证据。 | 校验不写目标端；缺主键、可靠变更标记或软删标记等阻断冻结。 |
| `POST /projects/{project_id}/candidates/{candidate_id}/freeze`、`GET /projects/{project_id}/pipeline-versions/{version_id}` | Maker 显式确认候选 ID、所见差异与指纹；后端再次校验 → 不可变 `PipelineVersion`、SHA256 摘要。 | 候选或 Profile 事实变化、门禁失败返回冲突/阻断；不复用旧审批。 |

## 4. 准备单、独立审批与 Commit

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `GET /projects/{project_id}/preparations`、`GET /projects/{project_id}/preparations/{preparation_id}` | 项目内获授权角色按 Pipeline、轮次、状态查询统一队列；详情返回来源、冻结版本/输入指纹、水位上下界、分类规则、质量阈值、预算、风险结论、影响和回滚计划、两项具名决定。 | 只显示当前角色有权查看的证据；读取页面不授予审批权。 |
| `POST /projects/{project_id}/pipelines/{pipeline_id}/preparations` | Maker 发起首轮 Prepare，提交冻结版本 ID → 不可变 Preparation。之后每轮由 Beat 在内部发起并出现在同一队列，无浏览器自动 Commit。 | 分类未确认、风险规则不足、关键事实缺失时保留阻断状态；Prepare 不写目标端。Maker 拟议阈值和预算在此冻结。 |
| `POST /projects/{project_id}/preparations/{preparation_id}/revisions` | Maker 从驳回/失效原单与新的有效配置、版本事实生成新准备单 → 新 ID；原单及审批保留只读。 | 不原地覆盖决定；新单重新取得两项批准。 |
| `POST /projects/{project_id}/preparations/{preparation_id}/decisions` | 数据或安全审批人提交 `approve/reject` 与理由；服务端从具名账户和项目角色确定审批职责 → 绑定同一准备单指纹的决定。 | Maker 自批、同人占两槽、事实失效、重复相反决定均被拒绝；审批人并行但互不代签。 |
| `POST /projects/{project_id}/preparations/{preparation_id}/commit` | Operator 显式提交所见准备单指纹 → 首次受理返回 `ExecutionRun` ID 与 `202`；重复请求返回同一运行或原拒绝结果。 | 后端重核项目、轮次顺序、风险、双审批、指纹与时效；同一 Preparation 最多一次实际运行，`ExecutionRun` 与 Outbox 原子落库。前轮未执行或未受管关闭时后轮不得 Commit。 |

## 5. 运行、质量、发布与回滚

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `GET /projects/{project_id}/runs`、`GET /projects/{project_id}/runs/{run_id}` | 有权角色按 Pipeline/轮次查询 `ExecutionRun`、作业和阶段状态、`updated_at`、吞吐、预算、硬中断、诊断与关联报告。 | 页面自动定期刷新并可手动刷新；已提交、运行中、质量通过、发布中、已发布为不同服务端事实。 |
| `POST /projects/{project_id}/runs/{run_id}/interrupt` | Operator 提交原因 → 受管中断记录及查询链接。 | 后端停作业、禁止继续发布、清理本轮未发布暂存/影子结果并留痕；已发布版本只能走独立回滚。重复请求返回原操作事实。 |
| `GET /projects/{project_id}/runs/{run_id}/quality`、`GET /projects/{project_id}/runs/{run_id}/quality/samples`、`GET /projects/{project_id}/runs/{run_id}/quality/samples/export` | 有权角色读取质量结论、有效/拒绝行数、错误码、冻结阈值与原因；额外授权者方可分页查看或下载有界脱敏行级样例。 | 安全、Schema、主键、映射和完整性错误直接阻断；导出与查看同权且留审计，不能导出全量原始错误行。样例上限数值 `UNVERIFIED`。 |
| `GET /projects/{project_id}/pipelines/{pipeline_id}/publication` | 有权角色读取正式版、上一版、待发布/发布阶段及真实目标端核实结果。 | 质量通过后由后端自动发布；水位仅在成功发布后推进，发布失败不得显示成功。 |
| `POST /projects/{project_id}/pipelines/{pipeline_id}/rollback-previews` | Operator 提交原因 → 当前正式版、可回滚目标、发布前清理或发布后恢复的阶段、影响摘要、受限 `preview_id` 与预期正式版。 | 预览不产生清理或换表副作用；目标不在可回滚范围时拒绝。 |
| `POST /projects/{project_id}/rollback-previews/{preview_id}/commit`、`GET /projects/{project_id}/rollbacks/{rollback_id}` | Operator 显式确认预览 → 回滚记录/异步状态与最终核实的正式版。 | 同一预览重试返回同一记录；发布或正式版变化时拒绝旧预览，要求重新预览。发布与回滚按 Pipeline 串行，不按过期目标自动排队执行；发布前清理不改变既有正式版。 |

SeaTunnel 仅搬运订单/用户增量至 Doris 暂存区；Doris 构建完整待发布宽表。Prepare 冻结增量上界，后续新变化进入下一轮；成功发布后才推进已发布水位。软删订单从当前宽表移除；软删用户的历史订单保留订单事实，用户维度字段置空并标记用户已删除。订单/用户更新须有按提交顺序可靠单调的变更标记，并在同一可核实一致快照内读取；无法证明迟到、乱序或源端并发变化完整性时阻断发布。发布后回滚恢复上一正式版的已发布水位并使旧准备单失效，重放须新 Prepare 与双审批。真实连接器能否满足此规则尚待联调验证。

## 6. 审计与 Benchmark

| 方法与路径 | 调用者；关键输入 → 输出 | 失败与交接 |
| --- | --- | --- |
| `GET /projects/{project_id}/audit-events` | 当前仅本项目 Auditor 可分页读取 `connection.created` / `connection.updated`。可选 `cursor`（上一页返回的事件 UUID）、`action`（上述两值之一）、`actor_id`（账户 UUID）；按 `created_at`、事件 ID 倒序，每页最多 50 条。响应 `items`、`next_cursor`；每项只含 `id`、`project_id`、`actor_id`、`action`、`resource_id`、`request_id`、`created_at`。完整 Pipeline、轮次、审批、Commit、发布、回滚与评测证据查询待相应记录实现。 | 未登录 `401`；非本项目 `404`，本项目非 Auditor `403`；无效游标或过滤值 `400`。服务端查询时重新核对账户与项目 Auditor 成员关系，游标不得跨项目；不返回连接主机、数据库名、Secret、内部 Capability 或样本。 |
| `GET /projects/{project_id}/benchmarks`、`GET /projects/{project_id}/benchmarks/{benchmark_id}` | 获授权角色查询版本化 L0/L1/L2 评测状态、生成准确率、P0/P1 拦截率及报告引用。 | 达标阈值 `UNVERIFIED`；报告展示不等于达标或用户验收。 |
| `POST /projects/{project_id}/benchmarks` | 获授权角色申请指定级别及评测版本 → 评测请求 ID。 | L2 若会产生实际写入，只能使用隔离的非敏感测试资源，并进入普通 Prepare、双审批、Operator Commit 链；该接口本身不得直接触发写入。 |

## 契约核对与未确认项

实现时须将本契约映射为 OpenAPI 3.1，并以项目隔离、越权、事实失效、重复提交、断线恢复和敏感信息不回传作为逐接口核对项。已确认的风险、增量、回滚水位和受管关闭规则见 [MVP_SPEC](MVP_SPEC.md)；各 Pipeline 实际阈值、Benchmark 达标值、容量门槛、样例上限及旧版清理策略的推迟与阻断见 [待确认与变更控制](MVP_SPEC.md#待确认与变更控制)。文档不证明接口可用、真实联调或用户功能验收。
