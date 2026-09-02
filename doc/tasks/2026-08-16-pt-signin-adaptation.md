# 任务：基于今日结果继续适配 PT 签到

- 任务标识：`2026-08-16-pt-signin-adaptation`
- 状态：`发布中`
- 创建时间：`2026-08-16 14:20 +08:00`
- 更新时间：`2026-09-02 16:51 +08:00`
- 用户原始需求：移除已经死亡的 PTLover，并结合今天签到与统计情况继续适配，尤其处理一次都没成功的站点。
- 用户最新指令：实施、测试并发布雷池无 CDP 预热流程；挑战期间保持 Chrome 与用户数据，暂不连接 Playwright，挑战通过后重新连接并继续签到。
- 启用方式：明确长任务条件。

## 一、需求定义

### 1.1 背景与问题

管理页仍把已经死亡的 `www.ptlover.cc` 作为 PTLover 候选站点。现有 PT 任务中还存在今日失败、从未成功或只有刷新结果的站点，需要依据实际执行记录、统计快照和站点页面区分代码缺陷与外部阻塞，并继续适配可修复项。

2026-08-19 新一轮现场核验显示，正式实例已有 `57` 个 PT 任务、`1` 个普通周期任务和 `54` 条现存脱敏执行记录。需要重新按当前版本、当前凭据和当前站点状态建立异常矩阵，历史结论仅作线索，不能替代本轮证据。

### 1.2 目标

清理死亡站点候选，建立今日 PT 任务的可核查分类，优先修复从未成功且可由 AutoSurf 适配的站点，并发布部署后进行受控回归。

本轮扩展目标是覆盖当前部署实例中的全部 PT 与普通周期签到任务：关闭代码导致的异常，对凭据失效、站点停服、网络/DNS、验证码或 WAF 等外部阻塞给出准确、可复查的分类，并发布后逐个进行有界回归。

### 1.3 范围、非范围与约束

- 范围内：PT 站点目录、识别与签到适配；今日执行和历史成功统计；针对性测试；GitHub 发布；Web 在线升级；受影响站点单次回归。
- 范围内（本轮扩展）：当前部署中的 PT 与普通周期任务、脱敏执行日志、失败截图、代码适配、测试、发布和受影响站点单次回归。
- 范围外：破解图片缺口验证码或 Cloudflare 人机挑战、删除历史执行记录、批量反复点击签到、直接修改 `/app/program` 或 `D:\docker\autosurf\autosurf_program`。
- 约束：只修改 `D:\Code\AutoSurf`；Cookie、Token、密码和授权头不得输出；外部阻塞不得伪报为成功；每轮修复后的受影响站点仅执行一次有界真实回归。

### 1.4 需求与验收标准

| 需求编号 | 需求描述 | 验收标准 | 优先级 | 状态 | 来源或最新变更 |
|---|---|---|---|---|---|
| REQ-001 | 死亡 PT 站点不再作为候选 | CookieCloud 中的 `ptlover.cc`、`raingfh.top` 不出现在候选列表；相关目录测试通过 | 高 | `已完成` | 用户截图与最新指令 |
| REQ-002 | 汇总今日签到、统计和历史成功情况 | 每个已配置任务具备今日结果、历史成功次数、最近错误和统计快照分类 | 高 | `已完成` | 用户最新指令 |
| REQ-003 | 优先适配从未成功且可修复的站点 | 找出从未成功任务；可由代码修复者完成适配与测试，外部阻塞者保留准确分类 | 高 | `已完成` | 用户最新指令 |
| REQ-004 | 发布并验证修复 | 全量测试、CI、Web 升级和受影响站点单次回归均有证据 | 高 | `已完成` | 既有发布约束 |
| REQ-005 | 适配无 Cookie 的 M-Team 认证 | 识别实际浏览器凭据载体；通过中性同步机制导入；候选、签到或准确阻塞分类可验证 | 高 | `已完成` | 用户追加指令 |
| REQ-006 | 完成 M-Team 专用签到执行 | 已同步凭据时调用当前站点每日问候接口并先验证登录；成功、凭据失效、接口或签名失败可区分；无凭据不误报 | 高 | `已取消（被 REQ-007 替代）` | 用户澄清 M-Team 没有签到入口 |
| REQ-007 | M-Team 仅刷新个人信息 | 有 `auth` 时可添加为“仅刷新”；不创建或执行签到；从 `/member/profile` 提取非敏感统计并准确分类失败 | 高 | `已完成` | 用户“馒头没有签到入口”与“继续适配” |
| REQ-008 | PTTime 的 403 已签到正文不得误判登录失效 | HTTP 403 且正文明确为“已签到”时返回 `ALREADY_DONE`；其他 403 仍返回 `AUTH_EXPIRED` | 高 | `已完成` | 用户现场截图 |
| REQ-009 | 识别 0ff 的动态日历签到历史 | 成功页日历渲染完成后提取日期和奖励；不依赖截图中的固定日期 | 高 | `已完成` | 用户现场截图 |
| REQ-010 | 新确认死亡站点不再执行 | `lemonhd.club`、`pt.gtk.pw` 不出现在候选；现有任务停用且历史保留 | 高 | `已完成` | 用户明确确认站点死亡 |
| REQ-011 | SunnyPT 当前签到页可稳定执行 | 在 `/user/attendance` 识别“立即签到”，点击后必须由已签到状态或 API 结果确认；登录失效保持准确分类 | 高 | `已完成` | 用户当前已登录页面截图与“适配” |
| REQ-012 | 图片验证站点形成可执行方案 | 以正式最新执行为准列出图片验证类型；评估本地识别、语义识别与人工确认，禁止把未确认结果提交或伪报成功 | 高 | `已完成（方案评估）` | 用户“看看有没有自动识别验证的方案” |
| REQ-013 | 补全并纠正 PT 统计 | 从正式统计快照定位缺失和明显错位字段；针对站点真实 DOM/API 修正，白名单字段不得混入导航或签到文案 | 高 | `已完成` | 用户“统计信息不完善，错误的，补充修正” |
| REQ-014 | 发布并更新正式实例 | 提交并推送 `main`；CI 通过；在线升级完成；部署 SHA、健康、入口进程和至少一项 PT 行为可验证 | 高 | `已完成` | 用户“发布并更新” |
| REQ-015 | 建立当前全部签到异常矩阵 | 57 个 PT 任务和 1 个周期任务均有当前状态、最新结果、异常族、证据与处置结论；不沿用陈旧结果 | 高 | `已完成` | 用户“连接部署库，修复所有的签到异常” |
| REQ-016 | 修复全部代码可控的签到异常 | 每个确认代码缺陷都有根因、最小修复和回归测试；外部阻塞保持准确分类且不伪报成功 | 高 | `已完成` | 用户最新指令 |
| REQ-017 | 发布并验证本轮全部修复 | 聚焦及全量测试通过；提交推送并在线升级；每个受影响站点只触发一次有界回归 | 高 | `已完成` | 用户最新指令与发布约束 |
| REQ-018 | 修正 U2 虚假“已签到”结果 | U2 只有出现站点明确的今日签到证据或实际提交成功时才能返回 `already_done`/`success`；仅访问首页不得误报 | 高 | `已完成` | 用户“U2 没有签到” |
| REQ-019 | 入口消失时从签到记录确认今日状态 | OpenCD/TJUPT 页面包含今日签到记录时返回 `already_done`，不再因入口消失或重新签到验证码误报失败 | 高 | `进行中` | 用户截图与“为什么显示没找到入口” |
| REQ-020 | 活动任务状态自动刷新 | 管理页在 PT 或周期任务为 `pending/running/retry_wait` 时自动拉取执行状态；NodeSeek 后端成功后无需手动刷新即可退出“执行中” | 高 | `进行中` | 用户“NodeSeek 一直显示执行中” |
| REQ-021 | 签到异常不阻断独立资料刷新 | 除明确登录失效外，签到失败、WAF/CAPTCHA 阻塞或导航异常仍独立尝试已配置的资料页；签到与刷新结果分别保留 | 高 | `进行中` | 用户“没签到的，也要尝试刷新数据” |
| REQ-022 | 保持拦截结果真实 | Cloudflare、WAF、验证码未通过仍保持 `blocked`，不得以资料刷新成功覆盖签到结果或模拟绕过挑战 | 高 | `进行中` | 用户“有几个还是被拦截，处理下”与既有安全约束 |
| REQ-023 | 细分并有界处理 WAF 挑战 | Cloudflare、雷池和普通人机验证在执行详情中明确区分；雷池页只精确点击一次“确认/確認”并最多等待 12 秒验证放行，其他挑战不盲点，未放行不伪报成功；资料页独立执行同一规则 | 高 | `进行中` | 用户“其他几个被cloudflare 或雷池拦截的呢”“为什么不带代替用户点击” |
| REQ-024 | 雷池挑战执行期间不暴露 CDP 调试会话 | PT 任务先以普通 HTTP 识别雷池 `468`；命中后由常驻 Chrome 在无 Playwright/CDP 连接状态下完成有界预热，再复用该页继续执行；普通站点不增加等待；执行详情记录预热事实 | 高 | `进行中` | 用户“实验一下”验证成功后要求“实施、测试、发布” |

## 二、总体架构

### 2.1 当前现状

`pt_discovery.py` 提供站点目录与候选识别，`automations/pt_signin.py` 通过共享持久 Playwright Chromium 执行主页优先签到和资料刷新，执行记录与统计由 `api.py` 暴露。真实结果保存在 SQLite，管理 API 是本轮诊断与部署验证入口。

当前正式版本 `ed6736559fc` 已提供认证的 `/api/v1/debug/executions` 与受控截图接口，本轮以该脱敏接口为执行事实入口，同时读取 PT/周期任务清单和历史/统计接口进行交叉验证。

### 2.2 目标架构

保持现有模块边界。目录层排除死亡站点；执行层仅为实际页面差异增加小范围适配；历史层保持原始记录；发布层继续使用 GitHub CI 和 Web 在线升级。

### 2.3 关键模块与职责

| 模块 | 当前职责 | 目标职责 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|---|
| `pt_discovery.py` | 域名归一与 PT 候选识别 | 排除 PTLover，保留有效主域名能力 | CookieCloud 域名、标记 | 候选与能力 | 站点目录 |
| `pt_signin.py` | 浏览器签到、结果分类、资料刷新 | 修复经现场证据确认的站点差异 | URL、Cookie、配置 | `RunResult` | Playwright、共享 profile |
| `userscripts.py` / Web 凭据 | 浏览器侧无 Cookie Token 同步 | 扩展到 M-Team 的实际认证载体，保持中性命名 | 页面存储或请求认证 | 加密 Web 凭据 | 用户脚本、写入密钥 |
| `api.py` / SQLite | 任务、执行、统计与历史 | 提供诊断事实，不改历史语义 | 任务与执行记录 | 管理 API 数据 | SQLAlchemy |

### 2.4 关键流程

| 流程 | 发起方 | 处理方 | 数据或状态变化 | 失败处理 | 关联需求 |
|---|---|---|---|---|---|
| 候选发现 | 管理页 | `pt_discovery.py` | 过滤死亡站点 | 不创建候选 | REQ-001 |
| 失败归类 | 本任务 | 管理 API / SQLite | 只读汇总 | 标为代码缺陷或外部阻塞 | REQ-002、REQ-003 |
| 单站回归 | 本任务 | PT 执行队列 | 新增一次执行记录 | 到终态即停止，不重复触发 | REQ-004 |
| 无 Cookie 凭据同步 | 浏览器用户脚本 | Web 凭据 API | 加密保存站点认证材料 | 无凭据时不伪造 Cookie | REQ-005 |
| M-Team 资料刷新 | PT 执行器 | M-Team Web API | 仅调用 `/api/member/profile` 并提取白名单统计字段 | 凭据失效与接口失败结构化返回，不产生签到副作用 | REQ-007 |
| PTTime 已签到分类 | PT 执行器 | `classify_pt_page` | 403 响应先识别明确的已签到正文 | 其他 403 保持登录失效分类 | REQ-008 |
| 0ff 日历历史 | PT 执行器 | `extract_site_signin_history` | 等待动态事件渲染并从日期单元格提取记录 | 空日历不伪造历史 | REQ-009 |
| 死亡站点清理 | 候选发现与任务协调 | 站点忽略表 | 排除候选、停用任务、取消待执行记录 | 历史执行记录只读保留 | REQ-010 |
| 专用统计刷新 | PT 执行器 | Rousi、SunnyPT、Zhuque 同源 API | 白名单提取资料、流量、等级、魔力与做种字段 | 401/403 或缺少用户标识按登录失效返回 | REQ-013 |
| 图片验证分流 | PT 执行器/后续识别模块 | OpenCD、TJUPT、Cloudflare | 字符码、语义选择、人机挑战分别分类 | 未达置信度门槛不得自动提交 | REQ-012 |
| 当前异常审计 | 本任务 | 调试日志、PT/周期任务 API | 按任务聚合最新执行、历史成功、失败族和截图可用性 | 旧记录、外部阻塞与代码缺陷分开记录 | REQ-015、REQ-016 |
| 当前状态自愈 | 管理页与 PT 执行器 | 现有任务/历史 API、资料页导航 | 活动任务定时更新；签到和资料刷新相互隔离 | 不重复创建执行，不放宽成功判定 | REQ-019 至 REQ-022 |

### 2.5 接口记录

| 接口编号 | 接口名称 | 调用方 | 提供方 | 输入、输出与错误契约 | 实现位置 | 兼容要求 | 关联需求、任务与测试 | 状态与证据 |
|---|---|---|---|---|---|---|---|---|
| IF-001 | Web 凭据同步接口 | 浏览器用户脚本 | AutoSurf API | 按来源提交白名单 LocalStorage 键；无效或未授权请求拒绝；响应不回显机密 | `userscripts.py`、`api.py`、`infrastructure/web_credentials.py` | 保持现有 Rousi 状态、脚本与 Token 上传接口兼容 | REQ-005 / TASK-006 / TEST-005 | `已完成`，聚焦测试通过 |
| IF-002 | M-Team 浏览器 API 调用 | `MTeamAdapter` | M-Team Web API | 使用已同步的 `auth`、`did`、`visitorId` 和站点当前签名格式只调用 `/member/profile`；仅返回白名单统计字段与非敏感错误摘要 | `automations/pt_signin.py` | 不输出或持久化明文凭据；不得调用每日问候 | REQ-007 / TASK-008 / TEST-008 | `已完成`，聚焦测试通过 |
| IF-003 | PT 站同源资料 API | Rousi、SunnyPT、Zhuque 适配器 | `/api/me`、`/api/v1/user/basic-info`、`/api/user/getInfo` | 使用既有浏览器会话，返回固定白名单统计；不回显 Token、Cookie、邮箱或 IP | `automations/pt_signin.py` | 页面型站点仍走通用 DOM 提取 | REQ-013 / TASK-008 / TEST-008 | `已完成`，现场结构与单测确认 |
| IF-004 | 脱敏执行调试接口 | 管理页与本轮诊断 | AutoSurf API | 按任务、状态和结果筛选最近执行；递归脱敏；截图只允许按执行 ID 读取受控目录文件 | `api.py`、`web/admin.js` | 不回显 Cookie、Token、密码或授权头 | REQ-015 / TASK-010 / TEST-011 | `已部署`，待用于本轮完整矩阵 |
| IF-005 | PT 无 CDP 挑战预热接口 | `PtSignInHandler` | 已注册共享浏览器提供方 | 输入 `RunContext` 和目标 URL；返回是否完成雷池预热；提供方缺少能力、非 `468`、探测或启动失败时返回 `False` 并保持原流程 | `browser_session.py`、`browser_control.py` | 不改变普通浏览器签到处理器和现有 provider 的会话契约 | REQ-024 / TASK-021 / TEST-021 | `已完成` |

### 2.6 架构决策引用

| 决策编号 | 对架构的影响 | 相关模块或接口 |
|---|---|---|
| DEC-001 | 历史成功与失败记录只读保留，死亡站点只从发现目录移除 | `pt_discovery.py`、SQLite 历史 |
| DEC-002 | 以真实执行证据区分代码缺陷和外部阻塞，禁止宽松成功匹配 | `pt_signin.py`、回归流程 |

## 三、单元设计

### 3.1 受影响单元

| 单元编号 | 文件或位置 | 职责 | 输入 | 输出 | 依赖 | 关联需求 |
|---|---|---|---|---|---|---|
| UNIT-001 | `src/autosurf/pt_discovery.py` | 站点目录、域名归一和候选能力 | 域名、Cookie 标记 | `PtSiteDiscovery` 或未知 | 目录规则 | REQ-001 |
| UNIT-002 | `src/autosurf/automations/pt_signin.py` | 页面导航、签到与结果分类 | `RunContext` | `RunResult` | Playwright | REQ-003 |
| UNIT-003 | `tests/test_pt_signin.py` | 目录及页面适配回归 | 固定 HTML/模拟页面 | 稳定断言 | pytest | REQ-001、REQ-003 |
| UNIT-004 | `src/autosurf/userscripts.py` 与 Web 凭据模块 | 同步无 Cookie 浏览器认证材料 | 页面存储、写入密钥 | 加密凭据 | 用户脚本、API | REQ-005 |
| UNIT-005 | `src/autosurf/automations/pt_signin.py` 的 `MTeamAdapter` | M-Team 个人信息刷新、统计提取和错误分类 | 页面、`RunContext` Web 凭据 | `RunResult` | Playwright 页面上下文、M-Team Web API | REQ-007 |
| UNIT-006 | `src/autosurf/api.py` 与正式管理 API | 汇总 PT、周期任务及脱敏执行事实 | 当前任务和执行记录 | 逐站异常矩阵 | SQLAlchemy、认证管理接口 | REQ-015 |
| UNIT-007 | `src/autosurf/automations/pt_signin.py`、`browser_signin.py`、`http_signin.py` | 修复本轮确认的 PT 与普通周期执行缺陷 | `RunContext`、站点页面/API | 准确 `RunResult` | Playwright、HTTPX | REQ-016 |
| UNIT-008 | `src/autosurf/web/admin.js` | 活动 PT/周期执行状态的后台轮询与局部重绘 | 现有任务、历史、统计 API | 最新状态与记录 | 浏览器定时器、现有管理 API | REQ-020 |
| UNIT-009 | `src/autosurf/automations/pt_signin.py` | OpenCD/TJUPT 今日历史兜底与签到/资料刷新隔离 | 页面正文、签到配置、资料页配置 | 独立签到和刷新结果 | Playwright | REQ-019、REQ-021、REQ-022 |

### 3.2 处理与异常规则

| 单元编号 | 正常处理规则 | 异常处理规则 | 兼容要求 | 验证方式 |
|---|---|---|---|---|
| UNIT-001 | 有效 PT 域名返回目录项 | 死亡 PTLover 返回未知，不进入候选 | 不影响已保存历史 | 单元/API 候选测试 |
| UNIT-002 | 只在确认入口和结果后成功 | 登录失效、WAF、CAPTCHA、超时保持失败分类 | 不把刷新成功当签到成功 | 模拟测试与单站实测 |
| UNIT-003 | 覆盖新增站点证据 | 禁止删除或放宽既有断言 | 全量测试保持通过 | pytest |
| UNIT-004 | 只同步明确识别的 M-Team 认证材料 | 未登录或结构未知时不上送空值 | 不破坏 Rousi 用户脚本 | 用户脚本/API 测试与候选读取 |
| UNIT-005 | 只调用 `/member/profile` 刷新非敏感统计，不执行签到 | 缺少凭据、401/403、非零业务码、网络失败和签名漂移分别准确分类 | 不调用或统计 `/system/hello` | 模拟 API 结果测试与现场接口结构核验 |
| UNIT-006 | 每个当前任务只取可核查的最新执行并结合历史 | 无记录、旧记录和活动记录分别标注，不把历史失败当当前失败 | 诊断输出必须脱敏 | 管理 API 聚合与抽样复核 |
| UNIT-007 | 只有明确站点成功证据才返回成功 | 凭据失效、WAF、验证码、DNS、超时和页面漂移分开分类 | 保留既有适配器与调度契约 | 站点模拟测试、全量回归、单站有界实测 |
| UNIT-008 | 仅存在活动执行时定时读取现有接口并局部重绘 | 页面隐藏、已有轮询或没有活动执行时不发请求 | 不改变任务或创建新执行 | 前端源码断言与正式页面状态核验 |
| UNIT-009 | 今日历史可证明已签到；资料刷新与签到动作分别捕获异常 | 只有 `auth_expired` 阻止资料刷新；`blocked/failed` 仍尝试独立资料页 | 签到失败保持主结果，不被刷新成功覆盖 | 适配器与处理器模拟测试 |
| UNIT-010 | `browser_session.py`、`browser_control.py` 的无 CDP 预热协调 | PT 处理器请求预热；浏览器提供方在连接 Playwright 前探测 `468`、普通方式打开 URL、等待正常标题并接管预热页 | 探测或预热失败时回退既有浏览器流程；不影响非 PT 任务 | 提供方单测、PT 调用顺序测试、全量 pytest、两站实机验证 |

## 四、执行任务

### 4.1 当前交接

- 当前阶段：发布
- 当前计划步骤：TASK-023 提交并推送 `origin/main`
- 当前门禁：代码、聚焦测试、全量测试和本机实机验证通过；等待 Git 提交与推送证据
- 最近完成检查点：2026-09-02 本机实机走完整源代码流程，HDKylin 预热成功并接管正确签到页，登录态保留且“当前环境正在被调试”未出现。
- 工作区状态：启用前 `main` 与 `origin/main` 均为 `245e54e`；当前仅本轮实现、测试和账本文件修改。
- 下一步唯一动作：复核 staged diff，提交并非强制推送到 `origin/main`。
- 恢复时先读取：本账本、`git status`、PT 管理 API 汇总、`pt_discovery.py`、`pt_signin.py`。

### 4.2 任务计划

| 任务编号 | 工作内容 | 状态 | 关联需求 | 文件或接口范围 | 完成条件 |
|---|---|---|---|---|---|
| TASK-001 | 汇总今日执行、历史成功次数、最近错误与统计 | `已完成` | REQ-002、REQ-003 | 管理 API、SQLite（只读） | 已形成站点分类和优先队列 |
| TASK-002 | 移除 PTLover 候选并补测试 | `已完成` | REQ-001 | `pt_discovery.py`、测试 | 候选 API 不再出现 |
| TASK-003 | 诊断并适配从未成功的可修复站点 | `已完成` | REQ-003 | `pt_signin.py`、测试 | 每项有根因、修复或外部阻塞结论 |
| TASK-004 | 运行针对性和完整测试 | `已完成` | REQ-001、REQ-003、REQ-004 | pytest、Playwright UI | 全部通过 |
| TASK-005 | 推送、CI、Web 升级与单站回归 | `已完成` | REQ-004 | GitHub、管理 API | SHA 一致、健康、回归终态 |
| TASK-006 | 调查并适配 M-Team 无 Cookie 认证 | `已完成` | REQ-005 | `userscripts.py`、Web 凭据、发现与执行代码、测试 | 实际凭据载体明确且同步链路可验证 |
| TASK-007 | 实现 M-Team 专用签到并验证 | `已取消（被 TASK-008 替代）` | REQ-006 | `pt_signin.py`、`main.py`、测试、README | 用户确认站点无签到入口，旧实现不得保留 |
| TASK-008 | 完成本轮站点能力与分类修正 | `已完成` | REQ-007 至 REQ-013 | PT 发现、执行、统计、管理页、测试、README | 全部新增需求均有调查结论或代码、测试和差异证据 |
| TASK-009 | 发布、在线升级和正式回归 | `已完成` | REQ-014 | Git、GitHub Actions、升级 API、正式 PT API | CI、SHA、健康、入口进程和受影响站点有界回归均通过 |
| TASK-010 | 汇总当前 PT 与周期任务异常矩阵 | `已完成` | REQ-015 | 正式管理 API、调试日志、统计与历史 | 58 个任务逐项有状态、异常族、证据和处置结论 |
| TASK-011 | 调查并修复确认的代码缺陷 | `已完成` | REQ-016 | PT/周期处理器、发现目录、测试 | 每个代码缺陷完成最小修复和聚焦测试 |
| TASK-012 | 执行聚焦、全量和必要 UI 验证 | `已完成` | REQ-016、REQ-017 | pytest、Playwright、差异检查 | 所有门禁测试通过，未执行项有准确影响说明 |
| TASK-013 | 提交、推送、在线升级和逐站有界回归 | `已完成` | REQ-017、REQ-018 | Git、升级 API、正式任务 API | SHA、健康和 OpenCD/U2 的最新结果可验证 |
| TASK-014 | 调查并修复 U2 虚假“已签到”判定 | `已完成` | REQ-018 | `pt_signin.py`、U2 正式页面、聚焦测试 | 仅首页文本不再触发 U2 已签到，真实签到路径与证据有回归覆盖 |
| TASK-015 | 读取正式任务和执行详情，确认本轮根因 | `已完成` | REQ-019 至 REQ-022 | 正式管理 API、用户截图、现有代码 | OpenCD、NodeSeek、拦截与刷新链路均有当前证据 |
| TASK-016 | 实现历史兜底、签到/刷新异常隔离和活动状态轮询 | `已完成` | REQ-019 至 REQ-022 | `pt_signin.py`、`admin.js` | 最小改动完成且不放宽拦截分类 |
| TASK-017 | 增加聚焦测试并运行完整回归 | `已完成` | REQ-019 至 REQ-022 | `tests/`、pytest、差异检查 | 新增正反例和全量测试通过 |
| TASK-018 | 提交、推送、在线升级并进行有界正式回归 | `阻塞` | REQ-019 至 REQ-022 | Git、CI、升级 API、正式任务 API | SHA/健康一致；NodeSeek 状态更新；受影响 PT 结果与刷新动作可核查 |
| TASK-020 | 细分 WAF 类型并有限处理雷池确认 | `代码已完成` | REQ-023 | `pt_signin.py`、测试、正式调试 API | Cloudflare/雷池/通用人机验证结果可区分；雷池确认只点击一次并验证放行，未放行保持 `blocked`；资料刷新结果独立 |
| TASK-019 | 修正 OpenCD 记录页动态加载时机并再次发布 | `发布待部署` | REQ-019 | `pt_signin.py`、测试、正式 OpenCD 任务 | 等待动态记录正文，识别今天记录并在正式执行返回 `already_done` |
| TASK-021 | 实现雷池无 CDP 预热和预热页接管 | `已完成` | REQ-024 | `browser_session.py`、`browser_control.py`、`pt_signin.py` | `468` 命中时连接前预热；非 `468` 直接连接；执行详情可见预热标记 |
| TASK-022 | 增加聚焦测试并运行完整回归 | `已完成` | REQ-024 | `tests/test_browser_control.py`、`tests/test_pt_signin.py` | 调用顺序、回退、页复用和详情标记均覆盖；聚焦 131 项、全量 201 项通过 |
| TASK-023 | 复核差异、提交并推送 `origin/main` | `进行中` | REQ-024 | Git、`origin/main` | 仅任务文件进入提交，非强制推送成功，报告 SHA |

### 4.3 变更记录

| 文件、配置或接口 | 变更内容 | 原因 | 关联需求与任务 | 验证方式 | 回滚引用 |
|---|---|---|---|---|---|
| `doc/tasks/2026-08-16-pt-signin-adaptation.md` | 新增长任务账本 | 保持跨诊断与部署过程可恢复 | 全部 | 账本对账 | 不适用 |
| `src/autosurf/automations/pt_signin.py` | 将 M-Team 改为仅资料刷新；修正 PTTime 分类；增强动态日历历史读取 | 对齐站点真实能力和现场页面语义 | REQ-007 至 REQ-009 / TASK-008 | TEST-008 | 第九章 |
| `src/autosurf/main.py` | 注册 `MTeamAdapter` | 确保生产应用装配适配器 | REQ-006 / TASK-007 | 装配断言 | 第九章 |
| `tests/test_pt_signin.py` | 覆盖 M-Team 仅刷新、PTTime 403、0ff 动态日历与死亡站点 | 防止现场缺陷回归 | REQ-007 至 REQ-010 / TASK-008 | TEST-008 | 不适用 |
| `README.md` | 明确 M-Team 无签到、只刷新个人信息 | 对齐站点真实能力 | REQ-007 / TASK-008 | 文档差异复核 | 不适用 |
| `src/autosurf/automations/pt_signin.py` | 新增 Rousi、SunnyPT、Zhuque API 资料刷新；增强卡片/内联统计解析和字段清洗 | 修正空统计、错位统计和导航文案污染 | REQ-013 / TASK-008 | API 形状测试、统计样本测试、全量回归 | 第九章 |
| `src/autosurf/pt_discovery.py` | Rousi 默认启用资料刷新；SunnyPT 移除失效 `/user/profile` | 对齐当前站点能力与接口 | REQ-013 / TASK-008 | 目录与迁移测试 | 第九章 |
| `src/autosurf/application/services.py` | 启动时同时协调 CookieCloud 与 Web Storage PT 任务能力 | 正式旧任务未迁移 M-Team/Rousi 新能力 | REQ-014 / TASK-009 | 重启协调测试与正式任务配置 | 第九章 |
| `src/autosurf/automations/pt_signin.py` | 0ff 保留首页结论、自动完成固定滑块并过滤空日历事件；Zhuque 消费前端 CSRF 请求响应；SunnyPT 404 归为登录失效；分享率统一格式化 | 解决正式回归暴露的历史、CSRF、分类和统计展示缺陷 | REQ-009、REQ-011、REQ-013、REQ-014 / TASK-009 | 聚焦、全量测试与正式有界回归 | 第九章 |
| `src/autosurf/automations/pt_signin.py` | 容忍同源有正文的部分加载页；补充人机/二步登录分类；OpenCD 接入本地 OCR；失败结果保留受控截图；支持首页 AJAX 验证码控件并在复用执行前清理旧截图 | 修复 SunnyPT、Audiences、HDDolby、OpenCD 当前异常及调试截图陈旧问题 | REQ-016 / TASK-011 | TEST-012、TEST-013、TEST-014 | 第九章 |
| `src/autosurf/automations/http_signin.py` | 连接建立前失败时安全重试一次，最终网络失败返回结构化结果 | 修复 NodeSeek `ConnectTimeout` 只有空结果的问题 | REQ-016 / TASK-011 | TEST-012、TEST-014 | 第九章 |
| `tests/test_pt_signin.py`、`tests/test_http_signin.py` | 增加当前五类异常的正反例 | 防止放宽成功判定或重复 POST | REQ-016 / TASK-011 | TEST-012、TEST-013 | 不适用 |
| `src/autosurf/automations/pt_signin.py`、`src/autosurf/web/admin.js`、相关测试 | 增加今日历史兜底、动作异常隔离和活动状态轮询 | 修复当前正式误报与陈旧状态 | REQ-019 至 REQ-022 / TASK-016、TASK-017 | TEST-016 至 TEST-019 | 第九章 |
| `src/autosurf/automations/pt_signin.py`、`tests/test_pt_signin.py` | 分开识别雷池 WAF、Cloudflare 人机挑战和 Cloudflare 52x 源站错误；浏览器挑战最多等待 12 秒自行放行 | 避免把 OKPT 522 误写成人机验证，同时让可自动放行的挑战复用持久浏览器状态 | REQ-023 / TASK-020 | TEST-020 | 第九章 |

## 五、测试与验证

### 5.1 测试计划与结果

| 测试编号 | 测试目标 | 关联需求与任务 | 方法或准确命令 | 预期结果 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|
| TEST-001 | PTLover 不再进入候选 | REQ-001 / TASK-002 | `pytest -q tests/test_pt_signin.py` | 目录与 API 断言通过 | 48 项通过 | `已通过` | pytest |
| TEST-002 | 新增站点适配不误判成功 | REQ-003 / TASK-003 | 针对性 pytest | 正确区分成功与阻塞 | 71 项聚焦测试通过 | `已通过` | pytest |
| TEST-003 | 完整回归 | REQ-004 / TASK-004 | `pytest -q` | 全量通过 | 98 项通过，1 个既有弃用警告 | `已通过` | pytest |
| TEST-004 | 部署与真实站点验证 | REQ-004 / TASK-005 | CI、升级 API、单站单次执行 | 部署健康且结果准确 | 最终 SHA 健康；TTG 已通过；SunnyPT 会话失效且覆盖缺陷已修复，不重复触发 | `已通过` | CI 31935290683、31936116214、执行记录 |
| TEST-005 | M-Team 无 Cookie 凭据同步 | REQ-005 / TASK-006 | 用户脚本/API/发现单元测试及只读现场验证 | 凭据可导入且不泄漏、不误判 | 多来源脚本、白名单、加密、重绑定与注入测试通过 | `已通过` | `tests/test_web_credentials.py` |
| TEST-006 | 导航异常结构化分类 | REQ-003 / TASK-003 | 模拟 Playwright 网络错误 | 结果有明确消息且不误报成功 | 参数化测试通过 | `已通过` | `tests/test_pt_signin.py` |
| TEST-007 | M-Team 专用签到分类 | REQ-006 / TASK-007 | `.venv\Scripts\python.exe -m pytest -q tests/test_pt_signin.py tests/test_web_credentials.py`，再运行全量 `.venv\Scripts\python.exe -m pytest -q` | 成功、缺凭据、会话失效、业务失败均稳定分类，其他站点无回归 | 聚焦 60 项通过；全量 103 项通过，1 个既有 SQLAlchemy 弃用警告；`compileall` 与 `git diff --check` 通过 | `已取消（需求被替代）` | 历史测试证据保留 |
| TEST-008 | 本轮站点与统计修正 | REQ-007 至 REQ-013 / TASK-008 | 聚焦 pytest、全量 pytest、`compileall`、`git diff --check` | M-Team 仅刷新；PTTime、0ff、SunnyPT 正确；死亡站点排除；统计字段准确 | 最终聚焦 77 项、全量 120 项通过；1 个既有弃用警告；编译与差异检查通过 | `已通过` | pytest 与命令结果 |
| TEST-009 | 图片验证自动识别可行性 | REQ-012 / TASK-008 | 正式最近执行分类；`pip install --dry-run ddddocr`；当前适配器路径复核；0ff 固定滑块只读实测 | 明确固定滑块、字符 OCR、语义视觉和人机挑战边界，不提交未确认答案 | 0ff 固定轨道滑块已自动处理；OpenCD 可采用本地 OCR 试验；TJUPT 需视觉语义模型；Cloudflare 保持人工浏览器处理；当前容器未安装 OCR 运行时 | `已通过` | 正式执行、依赖 dry-run、代码复核与滑块实测 |
| TEST-010 | 发布与正式实例验证 | REQ-014 / TASK-009 | GitHub Actions、`/api/v1/system/upgrade`、容器与 PT 管理 API | 推送 SHA 与正式 HEAD 一致，升级 complete、服务 healthy、行为生效 | 六次 CI 均通过；代码版本 `16f633b` 在线升级完成；正式仓库干净、健康恢复、入口进程正确；0ff、Zhuque、SunnyPT、M-Team、Rousi、Audiences 与 TJUPT 结果核验完成 | `已通过` | CI 31953828485、31954179331、31954516199、31955443019、31956785138、31957354173；正式执行与统计 API |
| TEST-011 | 当前全部任务异常审计 | REQ-015 / TASK-010 | `/api/v1/pt-signin/sites`、`/api/v1/periodic-signin/sites`、`/api/v1/debug/executions?limit=200`、历史与统计接口 | 58 个任务全部入矩阵，异常族可复查 | 44 个启用 PT 当前健康、2 个死亡站已停用、3 个 PT 尚未首跑；其余 8 个 PT 与 NodeSeek 均有执行、截图或错误证据和处置分类 | `已通过` | 正式脱敏管理 API 与受控截图接口 |
| TEST-012 | 本轮代码缺陷聚焦回归 | REQ-016 / TASK-011、TASK-012 | `.venv\Scripts\python.exe -m pytest -q tests/test_pt_signin.py tests/test_captcha_ocr.py tests/test_http_signin.py` | 确认缺陷均有正反例覆盖 | 最终 92 项通过 | `已通过` | pytest |
| TEST-013 | 完整工程回归 | REQ-016、REQ-017 / TASK-012 | `.venv\Scripts\python.exe -m pytest -q`、`compileall`、`git diff --check` | 全量通过且无意外差异 | U2 修复后 154 项通过，1 个既有 SQLAlchemy 弃用警告；编译和差异检查通过 | `已通过` | pytest、Git |
| TEST-014 | 发布和受影响站点实测 | REQ-017 / TASK-013 | 在线升级 API、健康检查、每站单次 `run` 与有界轮询 | 代码版本一致；成功/已签到或准确外部阻塞；不重复触发 | `5fb8bbf` 与 `f7216c1` 均在线升级完成且 SHA/健康一致；OpenCD 单次执行 `9709e365` 点击入口后返回 `already_done`，个人信息刷新成功 | `已通过` | 正式 API、CI 32274400785/32317500780 |
| TEST-015 | U2 签到结果真实性 | REQ-018 / TASK-013、TASK-014 | 正式单次执行、执行详情、必要截图与聚焦测试 | 页面明确显示今日已签到或实际提交成功；仅首页访问不得成功 | 首页误判反例通过；`f7216c1` 正式复用执行 `0723ca19`，尝试 1→2，未误报成功，准确返回 `blocked / PT 站点响应超时 / about:blank` | `已通过` | 正式 API、pytest |
| TEST-016 | OpenCD/TJUPT 今日历史兜底 | REQ-019 / TASK-016、TASK-017 | 适配器模拟页面测试 | 今日记录返回 `already_done`；无今日记录仍准确失败或阻塞 | PT 模块 89 项通过，包含记录表、OpenCD 和 TJUPT 正反例 | `已通过` | pytest |
| TEST-017 | 签到异常后的独立资料刷新 | REQ-021、REQ-022 / TASK-016、TASK-017 | 处理器异常与结果合并测试 | `blocked/failed` 仍尝试刷新，`auth_expired` 跳过；刷新不覆盖签到失败 | Cloudflare 页导航和签到 HTTP 响应错误后的独立刷新用例通过 | `已通过` | pytest |
| TEST-018 | 活动状态自动轮询 | REQ-020 / TASK-016、TASK-017 | 前端源码/页面行为测试 | 仅活动执行触发局部轮询并更新 PT/周期视图 | 管理 API 28 项和 `node --check` 通过，包含活动状态及 15 秒轮询断言 | `已通过` | pytest、Node.js |
| TEST-019 | 完整回归、发布与正式有界验证 | REQ-019 至 REQ-022 / TASK-017、TASK-018 | 全量 pytest、`git diff --check`、CI、升级 API、正式任务 API | 工程回归通过；部署 SHA/健康一致；当前异常结果和刷新动作准确 | 全量 162 项及 CI 通过；`c33a2da` 首轮部署验证部分通过；`fb5c485` 因 HomePc 全端口不可达而待在线升级 | `阻塞` | pytest、GitHub、正式 API |
| TEST-020 | WAF 厂商与 Cloudflare 源站错误细分 | REQ-023 / TASK-020 | `.venv\Scripts\python.exe -m pytest tests/test_pt_signin.py -q`、全量 pytest、`compileall`、`git diff --check`、正式受控截图 | 雷池、Cloudflare 挑战、普通人机验证和 Cloudflare 52x 分开；雷池确认精确点击一次，自动放行后继续，未放行保持阻塞 | PT 模块 94 项、全量 167 项通过；HDKyl 截图为雷池 468，OKPT 截图为 Cloudflare 522 Host Error | `代码已通过` | pytest、正式截图与执行 API |
| TEST-021 | 无 CDP 雷池预热单元回归 | REQ-024 / TASK-021、TASK-022 | `.venv\Scripts\python.exe -m pytest -q tests/test_browser_control.py tests/test_pt_signin.py` | 仅 `468` 启动预热；预热发生在 CDP 连接前；预热页被任务复用；失败回退既有流程；详情标记准确 | 131 项通过；HDKylin 实机预热、接管、登录态和调试警告检查通过 | `已通过` | pytest、Playwright |
| TEST-022 | 完整工程与发布门禁 | REQ-024 / TASK-022、TASK-023 | `.venv\Scripts\python.exe -m pytest -q`、`compileall`、`git diff --check`、完整 staged diff | 全量通过且提交只包含本轮实现、测试和账本 | 201 项通过；1 条第三方弃用警告；编译和差异检查通过 | `已通过` | pytest、Git |

### 5.2 未执行测试

无未执行的工程验证。SunnyPT 正式会话返回 404，已准确归为登录失效；该站统计需用户重新同步 Cookie 后才能生成，不属于代码测试缺口。OpenCD、TJUPT 图片语义验证码和 Cloudflare 未自动提交，符合未达置信度门槛不提交的约束。

## 六、端到端追踪

| 需求编号 | 验收标准 | 架构或单元 | 任务编号 | 文件、配置或接口 | 测试编号 | 结果与证据 | 状态 |
|---|---|---|---|---|---|---|---|
| REQ-001 | PTLover、Raing 不出现在候选 | UNIT-001、UNIT-003 | TASK-002 | `pt_discovery.py`、测试 | TEST-001、TEST-003 | 98 项全量通过 | `已通过` |
| REQ-002 | 完成今日与历史分类 | 当前架构 | TASK-001 | 管理 API、SQLite | 只读数据核对 | 今日执行与历史 200 条汇总完成 | `已完成` |
| REQ-003 | 可修复的从未成功站点完成适配 | UNIT-002、UNIT-003 | TASK-001、TASK-003 | `pt_signin.py`、测试 | TEST-002、TEST-003、TEST-004 | TTG 实测通过；SunnyPT 准确识别会话失效；外部阻塞已分类 | `已通过` |
| REQ-004 | 发布部署并验证 | 当前发布架构 | TASK-004、TASK-005 | GitHub、升级 API | TEST-003、TEST-004 | 最终 SHA、CI、健康与进程一致 | `已通过` |
| REQ-005 | M-Team 无 Cookie 认证可用 | UNIT-004、IF-001 | TASK-006、TASK-005 | 用户脚本、Web 凭据、发现与执行 | TEST-005、TEST-003、TEST-004 | 软件链路与正式凭据配置均已确认 | `已通过` |
| REQ-006 | M-Team 可执行专用签到 | UNIT-005、IF-002 | TASK-007 | 历史实现已移除 | TEST-007 | 用户确认站点无签到入口，由 REQ-007 替代 | `已取消` |
| REQ-007 | M-Team 仅刷新个人信息 | UNIT-005、IF-002 | TASK-008 | `pt_signin.py`、发现与 Web 凭据模块 | TEST-008 | 仅资料刷新能力、白名单统计与错误分类测试通过 | `已通过` |
| REQ-008 | PTTime 403 已签到分类 | UNIT-002、UNIT-003 | TASK-008 | `pt_signin.py`、测试 | TEST-008 | 明确已签到正文优先，普通 403 仍为失效 | `已通过` |
| REQ-009 | 0ff 动态历史 | UNIT-002、UNIT-003 | TASK-008、TASK-009 | 历史提取器、固定滑块、测试 | TEST-008、TEST-010 | 正式执行 `succeeded/already_done`，准确提取 7 条奖励记录，今日奖励 15 | `已通过` |
| REQ-010 | LemonHD、GTK 死亡站点清理 | UNIT-001、UNIT-003 | TASK-008 | 忽略目录、任务协调、测试 | TEST-008 | 不再发现，现有任务可停用且历史保留 | `已通过` |
| REQ-011 | SunnyPT 当前签到页 | UNIT-002、UNIT-003 | TASK-008、TASK-009 | SunnyPT 适配器、目录、测试 | TEST-008、TEST-010 | 点击后必须确认今日状态；正式资料 API 404 准确归为登录失效并跳过刷新 | `已通过` |
| REQ-012 | 图片验证方案 | 当前架构 | TASK-008 | OpenCD/TJUPT 适配器、依赖评估 | TEST-009 | 三类验证已分流，未启用无证据自动提交 | `已完成` |
| REQ-013 | 统计纠错补全 | UNIT-002、IF-003 | TASK-008、TASK-009 | 专用 API 适配器、通用 DOM 提取、清洗器 | TEST-008、TEST-010 | M-Team、Rousi、Zhuque、Audiences 正式快照正确；TJUPT 补回等级；分享率最多 3 位小数 | `已通过` |
| REQ-014 | 正式发布更新 | 发布架构 | TASK-009 | GitHub、在线升级 API、Docker、正式管理 API | TEST-010 | CI、升级、SHA、健康、进程和有界 PT 回归均通过 | `已通过` |
| REQ-015 | 58 个当前任务均有异常结论 | UNIT-006、IF-004 | TASK-010 | 正式脱敏管理 API、任务矩阵 | TEST-011 | 当前矩阵已闭合；3 个未首跑任务保留为待首跑而非故障 | `已通过` |
| REQ-016 | 全部代码可控异常被修复 | UNIT-007 | TASK-011、TASK-012 | 执行器、发现目录、测试 | TEST-012、TEST-013 | SunnyPT、Audiences、HDDolby、OpenCD 与 NodeSeek 结构化网络结果均已修复并通过回归 | `已通过` |
| REQ-017 | 修复发布并逐站有界验证 | 发布架构 | TASK-012、TASK-013 | Git、升级 API、正式任务 API | TEST-013、TEST-014、TEST-015 | `f7216c1`、CI、在线升级、健康与 OpenCD/U2 有界实测完成 | `已通过` |
| REQ-018 | U2 仅凭权威签到页返回成功 | UNIT-003 | TASK-013、TASK-014 | `pt_signin.py` | TEST-013、TEST-015 | 首页误判被单测阻止；正式网络超时时保持 `blocked` 而非成功 | `已通过` |
| REQ-019 | 今日历史可替代已消失的签到入口 | UNIT-009 | TASK-015 至 TASK-018 | `pt_signin.py` | TEST-016、TEST-019 | 代码与聚焦测试通过，待正式验证 | `进行中` |
| REQ-020 | NodeSeek 等活动状态自动更新 | UNIT-008 | TASK-015 至 TASK-018 | `admin.js`、现有管理 API | TEST-018、TEST-019 | 后端当前已成功，待页面自动同步 | `进行中` |
| REQ-021 | 非登录失效时独立刷新资料 | UNIT-009 | TASK-015 至 TASK-018 | `pt_signin.py` | TEST-017、TEST-019 | 代码与聚焦测试通过，待正式验证 | `进行中` |
| REQ-022 | 拦截不伪装成功且仍可刷新资料 | UNIT-009 | TASK-015 至 TASK-018 | `pt_signin.py` | TEST-017、TEST-019 | 代码与聚焦测试通过，待正式验证 | `进行中` |
| REQ-023 | 细分 WAF 并等待浏览器自动放行 | UNIT-009 | TASK-020 | `pt_signin.py`、持久浏览器 profile | TEST-020 | 本地与正式截图证据通过，待发布后读取新结构化结果 | `进行中` |
| REQ-024 | 挑战期间无 CDP，完成后继续签到 | UNIT-010、IF-005 | TASK-021 至 TASK-023 | `browser_session.py`、`browser_control.py`、`pt_signin.py`、测试 | TEST-021、TEST-022 | 实现、回归和本机 HDKylin 实机流程通过；待推送 | `进行中` |

## 七、决策与冲突记录

### 7.1 决策记录

| 决策编号 | 触发原因 | 采用方案 | 理由与证据 | 替代方案 | 影响范围 | 替代关系 | 状态 |
|---|---|---|---|---|---|---|---|
| DEC-001 | 用户说 PTLover 已死亡且不需要 | 从发现目录移除，但不删除历史 | 历史仍用于审计，候选不应继续出现 | 删除所有历史 | 候选与历史 | 无 | `有效` |
| DEC-002 | 既有站点曾发生错误成功识别 | 只有明确页面证据才修复并判成功 | 防止刷新、规则文字或断签状态伪装成功 | 放宽成功文本 | 签到判定 | 无 | `有效` |
| DEC-003 | `/system/hello` 匿名请求也可能返回 `code=0` | 每日问候前先用签名 `/member/profile` 验证当前凭据，再以问候结果判定执行成功 | 当时用于避免匿名成功，但用户随后确认每日问候不是签到 | 只检查页面文字或只调用 `hello` | M-Team 适配器 | 被 DEC-004 替代 | `已替代` |
| DEC-004 | 用户确认 M-Team 没有签到入口 | 站点能力定义为需要 Web 凭据的“仅资料刷新”，只调用 `/member/profile` | 不应把每日问候包装成签到 | 保留伪签到或完全不支持 | M-Team 发现与执行 | 替代 DEC-003 | `有效` |
| DEC-005 | PTTime 已签到页返回拒绝状态 | 明确的已签到正文优先于 HTTP 403，其他 403 不放宽 | 站点以 403 表达“拒绝重复签到”，正文语义更具体 | 所有 403 一律登录失效 | 页面分类器 | 无 | `有效` |
| DEC-006 | 0ff 日历由脚本动态渲染且自动会话先进入固定滑块 | 保留首页“已签到”结论，自动拖动固定轨道滑块，有界等待事件 DOM，只保留带奖励的签到块 | 正式 DOM 证明空圆点和背景事件代表未签到，不能写入历史 | 写死日期、忽略滑块或把全部事件算作签到 | 历史提取器 | 无 | `有效` |
| DEC-007 | 剩余验证机制类型不同 | OpenCD 字符码可做本地 OCR 样本试验；TJUPT 保留视觉语义或人工确认；Cloudflare 不自动破解 | OCR 不能回答影视语义选择，且当前没有字符码准确率样本 | 所有验证统一交给 OCR 或盲目提交 | 后续验证码模块 | 无 | `有效` |
| DEC-008 | 多个站点统计为空或错位 | Rousi、SunnyPT 优先用同源 API；Zhuque 捕获页面前端自带 CSRF 的资料响应；其他站点增强结构化 DOM 提取与清洗 | API 字段稳定且可白名单化；Zhuque 手工 fetch 缺少 `x-csrf-token` 会返回 400；DOM 卡片与导航混排会错配 | 继续只依赖相邻表格单元格或伪造 CSRF | 资料刷新与统计快照 | 无 | `有效` |
| DEC-009 | 接口计算分享率产生十几位小数 | 在统一统计清洗层按常规值 3 位、极小非零值最多 6 位格式化 | 历史快照无需重跑即可修正显示，且不改变原始执行结果 | 每个站点单独格式化或前端硬截断 | 统计 API | 无 | `有效` |
| DEC-013 | 实机证明雷池因 Playwright/CDP 的 `performance` 检查计 100 分 | 在 PT 会话连接前用无凭据 HTTP 仅识别专用状态 `468`，由常驻 Chrome 无 CDP 打开并等待挑战完成，再连接并接管预热页 | HDKylin、PigGo 均在 15 秒无 CDP 后进入正常首页，重新连接仍保持登录；隐藏 `webdriver` 无效且已为 `false` | 修改 UA/自动化标志、连接后再延长等待、对所有站点固定等待 | PT 浏览器会话协调 | 无 | `有效` |
| DEC-010 | 用户要求修复“所有”签到异常 | 以当前部署的 58 个任务为封闭清单；代码缺陷修复，外部阻塞准确分类，陈旧历史不算当前失败 | 范围可观察且不会把凭据、停服或验证码问题伪装成成功 | 只修截图中个别站点或宽松判成功 | 本轮调查、实现与验收 | 无 | `有效` |
| DEC-011 | OpenCD 签到后入口消失但记录页存在今天的权威记录 | 先查今日签到历史；仅命中今天时返回 `already_done` | 比“找不到入口”更准确，且不会重复提交验证码 | 将入口消失一律视为成功或失败 | OpenCD/TJUPT 适配器 | 无 | `有效` |
| DEC-012 | 签到页与资料页可能受不同路由、WAF 或导航错误影响 | 仅明确登录失效跳过资料刷新；其他签到结果与资料刷新分别执行和记录 | 用户要求未签到也刷新，且独立动作不能互相覆盖 | 被拦截时完全跳过刷新或把刷新成功当签到成功 | PT 执行处理器 | 无 | `有效` |

### 7.2 冲突记录

无。

## 八、缺陷记录

| 缺陷编号 | 关联需求与测试 | 严重程度 | 现象与根因 | 修复状态 | 修改位置 | 复测证据 |
|---|---|---|---|---|---|---|
| DEF-001 | REQ-001 / TEST-001 | 中 | 已死亡 PTLover、Raing 仍可能被 Cookie 特征识别为可添加，且 Raing 现存任务会继续重试 | `已完成` | `pt_discovery.py`、`api.py`、`services.py`、`pt_signin.py` | 候选、禁用、取消与运行兜底测试；全量 98 项通过 |
| DEF-002 | REQ-003 / TEST-002 | 高 | TTG 目录猜测 `/attendance.php`，实际签到入口是主页上的 `javascript:void(0)` 控件 | `已完成` | `pt_discovery.py` | TTG 目录测试通过，待部署实测 |
| DEF-003 | REQ-003 / TEST-002 | 高 | SunnyPT 目录猜测 `/attendance.php`，实际路由为 `/user/attendance`，资料路由为 `/user/profile`；当前站点会话同时已失效 | `已完成` | `pt_discovery.py`、`services.py` | 目录协调测试通过，待部署确认失效分类 |
| DEF-004 | REQ-003 / TEST-006 | 中 | DNS、拒绝连接等 `Page.goto` 异常只留下空结果，管理页无法直接理解失败类型 | `已完成` | `pt_signin.py` | 参数化错误分类测试通过 |
| DEF-005 | REQ-005 / TEST-005 | 高 | M-Team 无 Cookie，目录虽存在但只有 `custom_required`；现有同步脚本只支持 Rousi 的 `token` | `已完成` | 用户脚本、Web 凭据存储/API、浏览器 localStorage 注入、管理页 | 聚焦测试 71 项通过；部署后需用户安装新脚本并现场同步 |
| DEF-006 | REQ-003 / TEST-004 | 中 | SunnyPT 已跳转 `/auth/sign-in`，但随后资料刷新访问 `/user/profile` 触发 `ERR_ABORTED`，覆盖了登录失效结果 | `已完成` | `pt_signin.py` | 登录路由与跳过资料刷新单测；全量 98 项通过；按单站一次限制不重复实站触发 |
| DEF-007 | REQ-006 / TEST-007 | 高 | M-Team 凭据同步和注入已完成，但曾误把每日问候当作签到能力 | `已替代` | `pt_signin.py`、`main.py` | 用户确认站点无签到入口 |
| DEF-008 | REQ-007 / TEST-008 | 高 | M-Team 已有 Web 凭据但发现策略只启用签到，且 `/member/profile` 数据被丢弃 | `已完成` | `pt_discovery.py`、`pt_signin.py`、管理页、测试 | 聚焦与全量测试通过 |
| DEF-009 | REQ-008 / TEST-008 | 高 | `classify_pt_page` 在正文匹配前把全部 403 判为登录失效 | `已完成` | `pt_signin.py`、测试 | 403 已签到与普通 403 双向断言通过 |
| DEF-010 | REQ-009 / TEST-008 | 中 | 0ff 动态日历历史未进入执行结果，当前抓取时机和 DOM 兼容不足 | `已完成` | `pt_signin.py`、测试 | 动态等待与日期奖励断言通过 |
| DEF-011 | REQ-010 / TEST-008 | 中 | LemonHD、GTK 已死亡但仍可能被 Cookie 标记识别并继续调度 | `已完成` | `pt_discovery.py`、测试 | 死亡域名参数化测试通过 |
| DEF-012 | REQ-011 / TEST-008 | 高 | SunnyPT 当前已登录页面可见“立即签到”，需补充站点级成功确认，避免继续受旧会话失效结论阻塞 | `已完成` | `pt_signin.py`、`main.py`、测试 | 点击确认、API 刷新和 401 分类测试通过 |
| DEF-013 | REQ-013 / TEST-008 | 高 | Rousi、SunnyPT、Zhuque 统计为空；TJUPT 等级为导航文案；Audiences 卡片值被表格错配覆盖 | `已完成` | `pt_signin.py`、`pt_discovery.py`、`main.py`、测试 | 真实接口形状与固定页面样本断言通过 |
| DEF-014 | REQ-014 / TEST-010 | 高 | 首次部署后候选接口已识别 M-Team/Rousi 新能力，但启动协调器跳过 `web_storage` 任务，正式旧任务仍保留旧能力配置 | `已完成` | `application/services.py`、`tests/test_web_credentials.py` | 重启协调测试通过；正式 M-Team 为仅资料刷新、Rousi 为签到加资料刷新 |
| DEF-015 | REQ-014 / TEST-010 | 中 | 0ff 首页已签到状态会在进入 `/attendance.php` 前短路；正式会话还会遇到固定滑块，且空圆点事件曾污染历史 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 正式执行一次成功，提取 7 条真实奖励记录，今日奖励 15 |
| DEF-016 | REQ-014 / TEST-010 | 中 | Zhuque 手工资料请求缺少前端 `x-csrf-token` 而返回 400；SunnyPT 失效会话的资料 API 返回 404 且被误归为普通失败 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | Zhuque 正式资料刷新成功；SunnyPT 正式结果为 `auth_expired` 且跳过后续刷新 |
| DEF-017 | REQ-013 / TEST-010 | 低 | Rousi、Zhuque 分享率显示接口浮点的十几位小数 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 正式统计显示 Rousi `11.429`、Zhuque `31094.627` |
| DEF-018 | REQ-016 / TEST-012 | 高 | SunnyPT 首页内容和登录态已完整渲染，但 `DOMContentLoaded` 未在 60 秒内完成，外层导航超时使专用 API 适配器完全没有执行 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 同源且正文可用的部分加载页继续执行，`about:blank` 仍抛超时 |
| DEF-019 | REQ-016 / TEST-012 | 中 | Audiences 点击签到后显示“人机验证/验证通过后自动完成签到”，通用挑战词未覆盖而误报普通失败 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 当前正文稳定归类为 `blocked`，不误报成功 |
| DEF-020 | REQ-016 / TEST-012 | 高 | HDDolby Cookie 进入异地登录二步验证码页，仍被当作已登录页面并继续资料刷新，最终误报“没有签到入口；资料刷新成功” | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 二步登录正文归类为 `auth_expired`，处理器会跳过资料刷新 |
| DEF-021 | REQ-016 / TEST-012 | 高 | OpenCD 已确认是六位 NexusPHP 字符验证码；正式页面把不保留字段名和图片属性的验证码以 AJAX 控件注入首页，不形成完整表单或整页导航 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | 完整表单优先；否则逐 frame 查找可见文本输入、之前最近的 `img/canvas` 和之后首个按钮，并校验尺寸/间距；等待插件响应；可靠六位值才提交且必须确认成功 |
| DEF-022 | REQ-016 / TEST-012 | 中 | NodeSeek `ConnectTimeout` 直接逃逸到工作队列，执行记录没有结果；周期重试间隔较长且一次瞬时连接失败即结束本次处理 | `已完成` | `http_signin.py`、`tests/test_http_signin.py` | 只对连接尚未建立的超时/错误安全重试一次；最终返回带类型和次数的 `blocked` 结果 |
| DEF-023 | REQ-016 / TEST-012 | 低 | 等待重试复用原执行 ID，先前失败截图文件会在本次成功后继续被调试 API 当作当前截图展示 | `已完成` | `pt_signin.py` | 每次 PT 执行开始前删除同一执行 ID 的旧截图；仅本次新失败重新生成 |
| DEF-024 | REQ-018 / TEST-015 | 高 | U2 配置为 `/attendance.php`，但执行器先在首页匹配宽泛“已签到”文本后直接成功，未进入权威签到页 | `已完成` | `pt_signin.py`、`tests/test_pt_signin.py` | U2 首页的 `already_done` 不再被采信；登录失效/WAF 仍可在首页提前分类，随后必须进入签到页确认 |
| DEF-025 | REQ-019 / TEST-016 | 高 | OpenCD 当天签到后首页入口消失；首轮补丁已进入 `plugin_sign-in.php?cmd=show-log`，但 DOMContentLoaded 时动态记录表尚未填充，仍误报“没找到签到入口” | `代码已完成` | `pt_signin.py`、测试 | 动态表格延迟填充反例及 162 项全量回归通过，待正式复测 |
| DEF-026 | REQ-019 / TEST-016 | 中 | TJUPT 页面已有今日历史时仍进入重新签到图片验证码分支 | `代码已完成` | `pt_signin.py`、测试 | 今日历史先于重新签到控件的测试通过 |
| DEF-027 | REQ-021、REQ-022 / TEST-017 | 高 | `blocked` 与签到导航异常会提前返回，已启用的资料刷新不再执行 | `代码已完成` | `pt_signin.py`、测试 | Cloudflare 页及 Playwright 导航错误后继续刷新的处理器测试通过 |
| DEF-028 | REQ-020 / TEST-018 | 中 | 管理页只在加载和手动操作后刷新，NodeSeek 后端完成后仍长期显示旧“执行中” | `代码已完成` | `admin.js`、测试 | 管理 API 静态断言与 JS 语法检查通过，待正式页面验证 |
| DEF-029 | REQ-024 / TEST-021 | 高 | 雷池挑战在 Playwright 已连接时命中 `performance` DevTools 检查并直接计 100 分，导致真实有头 Chrome 被报告“当前环境正在被调试” | `已完成` | `browser_session.py`、`browser_control.py`、`pt_signin.py`、测试 | 聚焦 131 项、全量 201 项通过；HDKylin 实机预热后登录正常且无调试警告 |

## 九、回滚方案

| 变更或风险 | 触发条件 | 回滚步骤 | 数据与兼容影响 | 回滚后验证 | 状态 |
|---|---|---|---|---|---|
| 站点目录与适配代码 | 有效站点被误排除或结果误判 | 回退本次提交并通过 Web 升级；不改数据库历史 | 历史数据不受影响，新执行恢复旧行为 | 全量测试、健康检查、相关单站读取 | `已完成`（方案已就绪，未触发） |
| 无 CDP 雷池预热 | 普通站点被增加等待、Chrome 启动异常或预热页接管破坏固定窗口 | 回退本轮提交；不修改数据库、Profile 或浏览器凭据 | 已生成执行历史和 Chrome Profile 不受影响，任务恢复原 CDP 导航 | 聚焦测试、全量测试、Chrome 启动和普通站点路径 | `已就绪，未触发` |

## 十、已验证事实

| 事实编号 | 已验证事实 | 证据 | 对任务的影响 |
|---|---|---|---|
| FACT-001 | 基线仓库 `main` 与 `origin/main` 均为 `6edf932` | `git status`、`git log` | 可安全开始调查 |
| FACT-002 | 正式容器当前健康 | Docker health=`healthy` | 可使用管理 API 读取现场数据 |
| FACT-003 | 历史记录和站点 Cookie 状态必须逐次实测，不沿用旧结论 | AutoSurf 记忆与发布 Skill | 本轮重新核验所有结论 |
| FACT-004 | 从未有签到成功的任务为 OpenCD、TTG、U2、LemonHD、GTK、Raing、SunnyPT、GameGamePT、Oshen | 管理 API 最近 200 条执行 | 形成优先队列 |
| FACT-005 | OpenCD 为图片验证码；Raing、GameGamePT、Oshen 为登录失效 | 结构化执行结果 | 保持外部阻塞，不放宽成功判断 |
| FACT-006 | U2 返回浏览器响应码失败且解析到 `198.18.4.95`；LemonHD 无 DNS；GTK 拒绝或超时 | 执行错误与本机只读网络探测 | 环境/站点阻塞，不属于页面解析 |
| FACT-007 | TTG 认证主页有“签到”控件和 `userdetails.php` 资料链接，`/attendance.php` 是 File not found | 只读 Playwright DOM 与失败截图 | 目录应使用主页 |
| FACT-008 | SunnyPT 当前签到路由为 `/user/attendance`，签到 API 为 `/api/v1/attendance/check-in`；旧 `/user/profile` 返回 404，当前资料接口为 `/api/v1/user/basic-info` | 站点当前 JS 与只读浏览器请求 | 移除旧资料路由并由专用适配器读取同源 API |
| FACT-009 | M-Team 当前前端从 LocalStorage 读取 `auth`、`did`、`visitorId` 并写入认证请求头；`/system/hello` 由前端签名调用 | 当前 M-Team JS 与官方 API 说明 | 同步必须支持多键并由真实浏览器执行 |
| FACT-010 | PTLover 当前仍以 `custom_required` 候选出现，M-Team 因没有任何凭据而未出现 | 管理 API 候选与 Web 凭据状态 | 需阻止前者并创建后者的 Web 凭据 |
| FACT-011 | 2026-08-16 只读现场查询显示 M-Team Web 凭据已配置 `auth`、`did`、`visitorId`，候选已是 `web_storage_browser` 且可添加，但尚无已配置任务 | 正式管理 API（字段已脱敏） | 用户侧首次同步阻塞已关闭，当前缺口转为专用执行器 |
| FACT-012 | 当前公开 M-Team 前端版本 `1.1.7` 使用 Base64 HMAC-SHA1 表单签名，并把 `auth`、`did`、`visitorId` 写入 API 请求头；`/member/profile` 可验证当前用户，`/system/hello` 为既有每日问候入口 | 当前主页与 `main.e17fa37e.js`、官方 API 说明 | 适配器应复用浏览器上下文并严格分类签名或认证失败 |
| FACT-013 | 真实无状态 Chromium 使用当前签名调用 `/member/profile` 时，伪造凭据返回 HTTP 200、`code=1`、`無效的請求`，并未返回 `簽名錯誤` | 无用户凭据的 Playwright 探测 | 当前签名格式有效；资料校验阶段的该响应应归为凭据失效 |
| FACT-014 | M-Team 没有签到入口，`/system/hello` 不应被 AutoSurf 计为签到 | 用户明确澄清 | 取消 REQ-006，改为仅资料刷新 |
| FACT-015 | PTTime `/attendance.php` 显示“拒绝访问：已签到，无需再签”，当前分类器却先按 403 返回登录失效 | 用户截图与代码顺序 | 新增 DEF-009 |
| FACT-016 | 0ff 的签到历史显示在动态月历事件中 | 用户截图与既有 FullCalendar 提取代码 | 新增 DEF-010 |
| FACT-017 | `lemonhd.club`、`pt.gtk.pw` 已死亡 | 用户明确确认与访问现象 | 加入死亡站点忽略表 |
| FACT-018 | SunnyPT 当前凭据已能打开 `/user/attendance` 并显示“立即签到”以及今日未签到状态 | 用户现场截图 | 可继续完成有确认条件的专用适配 |
| FACT-019 | 正式最近 200 条执行中，图片验证仅有 OpenCD 传统图片码与 TJUPT 图片选影视名称；Hdkyl 是雷池 WAF 人机确认 | 正式管理 API 与受控截图 | 两类验证码需采用不同方案，WAF 不进入图片 OCR |
| FACT-020 | 正式统计中 Rousi、SunnyPT、Zhuque 为空，TJUPT 等级抓成导航文案，audiences.me 的上传下载与超高分享率明显矛盾 | 正式 `/api/v1/pt-signin/stats` | 新增 REQ-013 并按站点证据修正 |
| FACT-021 | Audiences 真实值为上传 `10.632 TB`、下载 `212.59 GB`、分享率 `51.213`；TJUPT 页头等级为“威震一方”且活动种子为 0 | 认证页面只读 DOM | 结构化卡片需优先于错位表格，导航等级需丢弃并从页头恢复 |
| FACT-022 | Rousi `/api/me` 返回 `stats` 与 `seeding_leeching_data`；Zhuque `/api/user/getInfo` 返回 class、流量、魔力和做种字段；SunnyPT 当前前端声明 `/api/v1/user/basic-info` | 同源 API 只读结构与当前前端资源 | 三站采用专用 API 白名单统计 |
| FACT-023 | Python 3.13 可解析安装 `ddddocr 1.6.1`，但会引入 ONNX Runtime、OpenCV、NumPy 与 Pillow；正式容器当前未安装这些运行时 | pip dry-run 与容器模块检查 | OpenCD OCR 需先做样本基准再决定是否增加生产依赖 |
| FACT-024 | 0ff 自动会话进入标题“滑动认证”的固定轨道页，`#dragHandler` 从 `#dragContainer` 左端拖到右端后进入 FullCalendar | 正式只读 Playwright DOM、截图与拖动实测 | 该验证不需要图像识别，可由本地鼠标轨迹稳定完成 |
| FACT-025 | 0ff 日历包含 7 个带奖励的块事件、14 个空圆点未签到事件和 7 个背景事件 | 正式 FullCalendar DOM 类别与文本 | 历史只应保留带奖励事件，不能把空事件算作签到 |
| FACT-026 | Zhuque 页面自身 `/api/user/getInfo` 请求带 `x-csrf-token` 并返回 200，手工同源 fetch 不带该头返回 400 | 正式只读请求方法、状态与请求头名称 | 资料适配器应消费前端请求响应，不自行猜测 CSRF |
| FACT-027 | 正式最终回归中 0ff 返回 7 条历史；Zhuque 资料刷新成功；SunnyPT 404 被归为登录失效；TJUPT 资料专用执行补回等级“威震一方” | 正式执行 API | REQ-009、REQ-011、REQ-013 验收闭合 |
| FACT-028 | 代码版本 `16f633b` 的 CI `31957354173` 通过并在线升级完成，正式仓库干净且容器健康在重启窗口后恢复 | GitHub Actions、升级 API、Docker health、进程与 Git SHA | REQ-014 发布门禁闭合 |
| FACT-029 | 2026-08-19 23:00 +08:00 正式服务健康，版本为 `ed6736559fc`，升级空闲；当前有 57 个 PT 任务、1 个周期任务和 54 条脱敏执行记录 | `/health`、升级 API、PT/周期任务 API、调试日志 API | 本轮以这 58 个任务为异常审计边界 |
| FACT-030 | 当前 57 个 PT 中 44 个启用任务最近成功或已签到，LemonHD/GTK 已停用，Discfan/0ff/Ubits 尚未首跑；异常为 Audiences、OpenCD、SunnyPT、TJUPT、U2、HDDolby、HDKyl、OKPT，周期异常仅 NodeSeek | 正式任务、历史和脱敏执行 API | TASK-010 矩阵闭合，避免把未首跑任务和死亡站历史算作当前代码失败 |
| FACT-031 | Audiences 截图明确显示人机验证；HDDolby 截图明确显示异地登录与两步验证码；SunnyPT 截图显示认证主页已完整渲染 | 受控执行截图接口 | 分别新增 DEF-019、DEF-020、DEF-018 |
| FACT-032 | OpenCD 返回同时含 `imagehash` 和 `imagestring` 的六位字符验证码表单，而 Oshen/SoulVoice 已使用同一 NexusPHP OCR 处理器 | 当前执行详情与代码 | OpenCD 可复用已有本地 OCR，不新增外部识别服务 |
| FACT-033 | HomePc SSH `18963072950@198.18.0.13:10816` 本轮再次在 banner exchange 阶段拒绝连接；Web API 与截图下载仍正常 | HomePc SSH 包装器与管理 API | 容器内网络无法直接检查，U2/NodeSeek 以执行日志和发布后有界复测为准 |
| FACT-034 | 外部当前访问可到达 U2 并进入 `/portal.php` 认证页；NodeSeek 对通用抓取入口返回 403 | 两站当前公开入口 | U2 不是全站死亡，正式容器的 `about:blank` 超时保留为部署网络/凭据侧问题；NodeSeek 以正式安全重试结果为准 |
| FACT-035 | `c6eef4a` 正式复测中 SunnyPT `success`、U2 `already_done`；Audiences/HDDolby 分别准确为 `blocked/auth_expired`；HDKyl/OKPT 保持 `blocked`；NodeSeek 返回两次安全连接失败的结构化结果 | 正式调试和任务 API | SunnyPT、U2 与四项分类修复闭合；外部阻断未伪装成成功 |
| FACT-036 | OpenCD 正式截图显示六位字符码、输入框和“签到”按钮直接位于首页顶部，页面 URL 仍为 `/`；插件响应并未形成完整表单导航 | 正式受控截图 | DEF-021 增加 AJAX 控件和响应确认路径 |
| FACT-037 | `19dc9eb` 正式 SunnyPT 新执行为 `already_done` 且 `artifact_url=null`；OpenCD 仍停在页面级控件，离线裁剪同一正式截图可稳定识别为六位 `8C32MN` | 正式调试 API、受控截图与本地 OCR | DEF-023 正式闭合；OpenCD 剩余问题仅为图片 DOM 定位，OCR 能力已由当前样本验证 |
| FACT-038 | HomePc Web 升级恢复后，`remote_revision=5fb8bbf` 且 `can_upgrade=true`；在线升级完成后正式三方 SHA 一致，OpenCD 执行点击签到入口并返回 `already_done` | 升级 API、健康端点、执行详情 `9709e365` | RISK-008 关闭，TEST-014 通过 |
| FACT-039 | U2 旧成功结果停在首页、`clicked=false` 且无签到历史；用户确认实际未签到。本轮单次执行又在打开首页时 60 秒超时，未产生签到 | 正式执行详情 `3d8deb96`、`0723ca19` 与用户反馈 | 新增 DEF-024；网络超时与误判分层处理，不把本次 `retry_wait` 当成功 |
| FACT-040 | 用户级技能已拆为 `homepc`（仅 SSH/主机）和 `autosurf-web-debug`（仅网站/API）；新 Web 包装器使用独立 DPAPI 凭据并可直接读取正式升级状态 | 两个技能 `quick_validate.py`、PowerShell 解析与正式只读 API | 后续网站调试不再以 SSH 可达为前置条件；不影响仓库运行代码 |
| FACT-041 | `f7216c1` CI `32317500780` 成功，独立 Web 技能在远端检查恢复后完成在线升级；正式 revision/local/remote 一致且健康 | GitHub Actions、升级 API、`/health` | U2 修复发布门禁闭合 |
| FACT-042 | `f7216c1` 下 U2 单次运行复用 `0723ca19`，尝试次数从 1 增到 2；仍在首页导航阶段 60 秒超时并进入 `retry_wait`，未返回 `already_done` | 正式调试 API | 代码误判已消除；当前 U2 未签到原因是正式容器到站点的外部连接超时 |
| FACT-043 | OpenCD 最新执行误报“首页没有找到签到入口”，但用户截图的记录页第一行明确为 `2026-08-20 20:19:09`；同一执行资料刷新成功且统计与截图页头一致 | 用户截图、正式执行详情与统计 API | 今日历史应作为权威 `already_done` 证据，不能继续尝试验证码 |
| FACT-044 | NodeSeek 最新周期执行 `9cc17f00` 已在后端 `succeeded`，完成时间为 `2026-08-20 04:17:39`，管理页仍显示执行中 | 正式周期任务/执行 API 与用户反馈 | 根因是前端没有活动状态轮询，不是任务仍在运行 |
| FACT-045 | 当前 55 个支持资料刷新的 PT 任务均已启用刷新；OpenCD 本轮刷新成功，而 TJUPT/HDKyl/OKPT 因签到 `blocked` 被代码直接跳过，U2 在签到导航异常后直接返回 | 正式任务/执行 API 与代码路径 | 无需批量改配置，应修复动作隔离和跳过条件 |
| FACT-046 | 本轮实现后 PT 模块 89 项、管理 API 28 项、全量 162 项通过；`compileall`、`node --check` 和 `git diff --check` 通过 | 本地验证命令 | TASK-017 与代码发布前门禁闭合 |
| FACT-047 | 发布前正式健康、升级状态、Python 依赖和 Chromium 均正常，版本为 `91c43ce`；HomePc SSH 仍在 banner exchange 阶段拒绝连接 | `/health`、升级 API、HomePc SSH 包装器 | 可继续 Web 在线升级，但本轮不能重新读取容器 PID 1，需在最终结果准确说明 |
| FACT-048 | `c33a2da` 正式回归中 OpenCD 已导航到 `https://open.cd/plugin_sign-in.php?cmd=show-log`，失败截图稍后显示今日 `2026-08-20 08:19:09` 记录；适配器在 DOMContentLoaded 后立即读取正文而未等动态表格 | 正式执行 `6e83cdbc`、执行详情与受控截图 | 链接选择正确，剩余根因是动态填充时机或 frame 正文覆盖，DEF-025 重新打开 |
| FACT-049 | OpenCD 动态补丁 `fb5c485` 已推送且 CI `32370900882` 成功；随后 `198.18.0.13` 的 `/health`、Web 登录、SSH 和 ICMP 均持续不可达，本机 `198.18.0.0/15` 路由仍为 Alive | GitHub Actions、Web/SSH/ICMP 探测、本机路由 | 代码发布完成但未部署；禁止绕过 Web 升级或误报正式生效 |
| FACT-050 | HomePc 地址已改为 `192.168.50.91`，Web/SSH 端口仍为 `18980/10816`；两个独立技能及包装器已更新并通过校验，新 Web `/health` 返回 200 | 用户指令、技能校验与健康端点 | 正式调试通道恢复，后续不再访问旧 198.18 地址 |
| FACT-051 | HDKyl 第 4 次尝试返回 HTTP 468，截图明确显示“安全检测能力由雷池 WAF 驱动”且只有一个“确认”按钮；签到后资料刷新已独立执行，但当前拦截页无法发现资料链接 | 正式执行 `391313fe` 与受控截图 | 仅精确点击一次雷池确认并验证页面放行；未放行保持 `blocked` |
| FACT-052 | OKPT 第 4 次尝试为 Cloudflare 522，截图显示 Browser/Cloudflare Working、Host Error；签到后资料刷新已独立执行但仍停在故障首页 | 正式执行 `db8c6930` 与受控截图 | 这是站点源服务器超时，不是可由浏览器通过的人机挑战，应归为结构化外部失败 |
| FACT-053 | WAF 修复提交 `e96baca` 已推送，CI `32376023921` 的测试与镜像构建均成功；新 Web 地址连续 5 次远端版本检查超时，正式 revision 仍为 `c33a2da`，新 SSH 地址仍在 banner exchange 阶段拒绝连接 | Git、GitHub Actions、升级 API、HomePc SSH 包装器 | 代码已发布但未部署；不得绕过在线升级或宣称雷池自动确认已在正式环境生效 |
| FACT-054 | 雷池挑战脚本的 `on-debug` 在评分达到 100 时触发；当前实际页面仅编号 27 命中，内部检查器为 `performance`，`navigator.webdriver=false` | 当前挑战脚本与本机 Chrome 实测 | 根因是挑战期间的调试协议行为，不是无头或 webdriver 指纹 |
| FACT-055 | 不连接 CDP、由同一常驻 Chrome 普通打开 HDKylin 和 PigGo 15 秒后，两站均进入正常登录首页；之后重新连接 Playwright 仍正常 | `127.0.0.1:9222/json/list` 与连接后页面读取 | 无 CDP 预热方案已通过实施前实机可行性门禁 |

## 十一、风险与阻塞

| 编号 | 类型 | 描述与证据 | 影响 | 缓解或所需动作 | 状态 |
|---|---|---|---|---|---|
| RISK-001 | 外部依赖 | 站点下线、Cookie 失效、WAF/CAPTCHA 或 DNS 故障不能靠成功文本适配解决 | 部分从未成功站点只能准确分类 | 已保留失败结果和外部阻塞清单 | `已接受` |
| RISK-002 | 行为风险 | 真实签到或刷新可能产生站点记录、奖励或新执行 | 回归具有外部副作用 | 每轮只触发受影响任务一次；TJUPT 通过官方操作接口临时关闭签到后仅刷新资料，并已恢复原配置 | `已关闭` |
| RISK-003 | 外部操作 | M-Team 使用 LocalStorage 的 `auth`、`did`、`visitorId`，曾缺少正式同步 | 无凭据时不能现场签到 | 正式管理 API 已确认三项键配置完成 | `已关闭` |
| RISK-004 | 外部依赖 | M-Team Web 前端签名版本或公开 API 主机可能变更 | 适配器可能返回签名配置失败 | 将非零码准确标为失败并保留聚焦测试；不回退成匿名成功 | `已缓解` |
| RISK-005 | 识别准确率 | OpenCD 字符码尚无本站样本准确率；TJUPT 是影视语义选择而非文字识别 | 错误提交可能触发失败或风控 | 保持 `BLOCKED`，只有样本基准与置信度门槛通过后才允许自动提交 | `已接受` |
| RISK-006 | 正式凭据状态 | SunnyPT 正式 AutoSurf 会话访问资料 API 返回 404，用户浏览器截图中的有效会话尚未同步 | 统计代码无法立即生成正式快照 | 用户下次同步 Cookie 后再执行一次资料刷新；代码已准确返回登录失效并停止后续动作 | `外部待同步` |
| RISK-007 | 部署诊断通道 | HomePc SSH `198.18.0.13:10816` 在上一发布轮次和本轮均拒绝连接，但 Web 管理 API 与健康端点正常 | 暂时不能读取容器内日志和进程；不影响 API 侧矩阵、发布和有界复测 | 使用脱敏调试 API、受控截图和 Web 升级证据并明确残余验证 | `已缓解` |
| RISK-008 | 发布阻塞 | HomePc 在线升级曾连续返回“远端版本检查超时” | 最终 OpenCD 补丁一度无法部署 | Web API 已恢复并按门禁升级 `5fb8bbf`，SHA、健康和 OpenCD 行为均已验证 | `已关闭` |
| RISK-009 | U2 结果真实性 | 旧执行以首页文本返回 `already_done`，但无点击、无签到历史，且用户确认实际未签到 | 历史统计会把未签到误算为成功 | U2 首页结果不再作为已签到证据；正式网络超时保持 `blocked` | `已关闭` |
| RISK-010 | U2 修复发布 | `f7216c1` 推送后远端版本检查曾连续超时 | 一度不能开始最终 U2 回归 | 恢复后按精确 SHA 门禁完成在线升级 | `已关闭` |
| RISK-011 | U2 外部可达性 | 正式持久浏览器打开 `https://u2.dmhy.org/` 仍在 60 秒内无响应，URL 保持 `about:blank` | 当前无法实际进入签到页，未生成签到记录 | 保留 `retry_wait` 让既有调度自动重试；不重复手动触发，不伪报成功 | `已接受` |
| RISK-012 | 正式实例地址变更 | 旧地址 `198.18.0.13` 全端口不可达；用户确认新地址为 `192.168.50.91` 且端口不变，新 Web 健康与认证 API 已恢复 | `fb5c485` 尚未部署，OpenCD 最终现场验收未完成 | 两个连接技能已更新；继续按远端精确 SHA 门禁在线升级 | `已关闭` |
| RISK-013 | 正式容器无法读取 GitHub 远端版本 | `GET /api/v1/system/upgrade` 连续 5 次执行 15 秒 `git ls-remote` 均超时；SSH 无法进入主机继续定位 DNS/网关 | `e96baca` 及先前 `fb5c485` 无法在线升级，正式仍为 `c33a2da` | 不直接修改部署目录；等待容器出站或 SSH 恢复后重新执行精确 SHA 门禁 | `阻塞` |
| RISK-014 | 预热探测与浏览器启动属于外部网络/进程行为 | 探测可能超时，Chrome 可能尚未运行，挑战可能超过等待上限 | 不能让普通站点或整个执行因预热辅助失败而中断 | 仅 `468` 执行；所有预热错误回退既有流程；有界等待；保留真实 WAF 分类 | `已缓解` |

## 十二、质量门禁

### 12.1 准备门禁

| 检查项 | 结论 | 证据或条件 |
|---|---|---|
| 最新目标、范围、非范围和约束已记录 | 通过 | 第一章 |
| 验收标准可观察、可测试 | 通过 | REQ-024、TEST-021、TEST-022 |
| 必要架构和单元设计达到可实现程度 | 通过 | UNIT-010、IF-005、FACT-054、FACT-055、DEC-013 |
| 每项需求已有任务、范围和测试思路 | 通过 | 第四至六章 |
| 工作区基线和用户已有改动已识别 | 通过 | FACT-001 |
| 高风险变更已有回滚思路 | 通过 | 第九章 |
| 无改变实现方向的未解决冲突 | 通过 | 冲突记录为无 |

- 门禁结论：通过
- 当前工作区基线干净，实机可行性已验证；TASK-021 可进入实现，辅助预热失败必须回退既有路径。

### 12.2 完成门禁

| 检查项 | 结论 | 证据或条件 |
|---|---|---|
| 用户最新目标和有效需求逐项验收 | 未通过 | REQ-019 至 REQ-022、TEST-016 至 TEST-019 待完成 |
| 端到端追踪闭合 | 通过 | 第六章；U2 外部连接超时由 RISK-011 准确保留 |
| 测试已执行或缺口影响已准确记录 | 通过 | 第五章 |
| 缺陷已关闭或成为用户接受的遗留风险 | 通过 | 第八、十一章 |
| 决策、冲突、回滚、风险和阻塞状态已更新 | 通过 | 第七、九、十一章 |
| 最终差异无范围漂移、无关回退和调试残留 | 通过 | `git diff --check`；修改均属于本轮 PT 适配、统计、测试与账本 |
| 账本与工作区一致，下一步唯一动作为“无” | 未通过 | TASK-018 发布和正式回归尚未完成 |

- 门禁结论：未通过
- 条件及关闭要求：HomePc 恢复后完成 TASK-018/TASK-019 正式升级与 OpenCD 单次复测，关闭 DEF-025 和 RISK-012。

## 十三、检查点

| 时间 | 已完成 | 新发现或变化 | 影响 | 下一步唯一动作 |
|---|---|---|---|---|
| 2026-08-16 14:20 +08:00 | 启用长任务账本，确认基线与约束 | PTLover 为明确死亡站点；其余站点需读取今日事实 | 准备门禁有条件通过 | 读取管理 API 和 SQLite 汇总 |
| 2026-08-16 14:23 +08:00 | 接收 M-Team 追加范围 | `kp.m-team.cc` 无 Cookie，需确认浏览器认证载体并复用中性 Web 凭据同步 | 增加 REQ-005、UNIT-004、IF-001、TASK-006、TEST-005 | 读取管理 API 和 SQLite 汇总 |
| 2026-08-16 14:50 +08:00 | 完成现场分类与只读 DOM/JS 调查 | 确认 PTLover、TTG、SunnyPT、M-Team 和导航错误为代码项；其余为外部阻塞 | 准备门禁通过，TASK-002 进行中 | 增加 PTLover 阻止规则和测试 |
| 2026-08-16 15:02 +08:00 | 第一组实现与 48 项 PT 测试通过 | PTLover 已排除；TTG/SunnyPT 使用真实路径；导航异常有结构化结果 | TASK-002 完成，TASK-006 进行中 | 扩展多来源 Web 凭据同步 |
| 2026-08-16 15:27 +08:00 | 完成 M-Team 多键 Web 凭据同步、兼容 API、浏览器注入与双站点管理页；聚焦测试 71 项通过 | M-Team 需要重新安装新版合并脚本后才能取得现场凭据 | TASK-003、TASK-006 完成，TASK-004 进行中 | 运行全量测试与 Playwright 页面验证 |
| 2026-08-16 15:52 +08:00 | 排除并停用 Raing；修复 Web 凭据动态表转义；全量 98 项和桌面/移动 Playwright 通过 | 页面两行、零控制台错误；M-Team 正式凭据仍待新版脚本同步 | TASK-004 完成，TASK-005 进行中 | 复核差异后提交并推送 main |
| 2026-08-16 16:16 +08:00 | 首轮 CI、在线升级、正式页面验证完成；TTG 单次回归通过；SunnyPT 单次回归暴露并修复结果覆盖 | SunnyPT 当前会话实际已失效；不再重复触发实站 | TASK-005 继续 | 提交补修并再次完成 CI 与在线升级 |
| 2026-08-16 16:22 +08:00 | 最终补修 CI 与在线升级完成；SHA、健康、进程、部署仓库均通过 | 工程任务完成；M-Team 现场同步需要用户安装新版脚本 | 完成门禁有条件通过 | 无工程任务 |
| 2026-08-16 21:06 +08:00 | 接收 M-Team “适配”追加指令并恢复账本；只读核验正式凭据已同步 | 旧结论只覆盖凭据链路，代码仍缺专用签到执行器；匿名 `hello` 不足以证明登录 | 新增 REQ-006、UNIT-005、IF-002、TASK-007、TEST-007、DEF-007，完成门禁重开 | 实现并注册 `MTeamAdapter` |
| 2026-08-16 21:09 +08:00 | 完成适配器初版和 59 项聚焦测试；真实无状态 Chromium 验证签名可达认证判断 | M-Team 对无效认证返回 `code=1 / 無效的請求`，需归为凭据失效 | 补充现场分类断言后继续全量测试 | 复跑聚焦测试并运行全量回归 |
| 2026-08-16 21:11 +08:00 | 完成现场分类修正、生产装配断言与最终验证 | 聚焦 60 项、全量 103 项、编译和差异检查通过；没有发布授权 | REQ-006、TASK-007、TEST-007、DEF-007 完成，完成门禁通过 | 无 |
| 2026-08-16 21:22 +08:00 | 接收四项现场修正 | M-Team 无签到；PTTime 403 误判；0ff 日历历史缺失；LemonHD 与 GTK 死亡 | 新增 REQ-007 至 REQ-010，完成门禁重开 | 完成 TASK-008 并测试 |
| 2026-08-16 22:05 +08:00 | 完成 M-Team、PTTime、0ff、死亡站点与 SunnyPT 代码修正；聚焦测试通过 | 正式统计还存在 Rousi、SunnyPT、Zhuque 空值以及 TJUPT、Audiences 错值 | 扩展 REQ-012、REQ-013 | 核验真实 DOM/API 并修正统计 |
| 2026-08-16 22:20 +08:00 | 完成三站专用资料 API、通用统计提取与验证码方案评估 | OpenCD 可做本地字符 OCR 样本试验；TJUPT 需要视觉语义；SunnyPT 正式 Cookie 待同步 | TASK-008 完成，外部风险准确保留 | 最终复跑和差异对账 |
| 2026-08-16 22:25 +08:00 | 聚焦 72 项、全量 115 项、编译与差异检查通过 | 本轮未获得发布授权 | 完成门禁通过 | 无 |
| 2026-08-16 23:10 +08:00 | 首批代码、Web Storage 启动协调与 0ff 首页结论修正完成多轮 CI、在线升级 | 正式旧任务曾跳过能力迁移；修复后 M-Team/Rousi 配置已正确 | DEF-014 关闭，继续正式回归 | 核验 0ff、Zhuque、SunnyPT |
| 2026-08-16 23:35 +08:00 | SunnyPT 404 已准确归为登录失效；只读诊断 0ff 与 Zhuque | 0ff 是固定轨道滑块且空事件污染历史；Zhuque 前端请求依赖 `x-csrf-token` | 新增并修复 DEF-015、DEF-016 | 测试、发布最终行为修正 |
| 2026-08-16 23:56 +08:00 | `17f0bac` CI、在线升级及正式回归完成 | 0ff 准确提取 7 条奖励历史；Zhuque 资料刷新成功；TJUPT 仅资料刷新补回等级 | 行为与统计验收闭合 | 规范分享率显示 |
| 2026-08-17 00:05 +08:00 | `16f633b` CI `31957354173`、在线升级、健康恢复与统计只读核验完成 | Rousi、Zhuque 分享率分别显示 `11.429`、`31094.627`；SunnyPT 仍需外部会话同步 | REQ-014、TASK-009、TEST-010 完成 | 无 |
| 2026-08-19 23:00 +08:00 | 接收“连接部署库，修复所有签到异常”，恢复既有账本并确认正式基线 | 当前 57 个 PT、1 个周期任务、54 条执行记录；正式版本 `ed67365` 健康 | 新增 REQ-015 至 REQ-017，完成门禁重开，TASK-010 进行中 | 形成 58 个任务逐站异常矩阵 |
| 2026-08-19 23:15 +08:00 | 完成 58 个任务矩阵并读取三张受控失败截图；重试 SSH 仍拒绝连接 | 确认四项代码缺陷；U2、TJUPT、HDKyl、OKPT、NodeSeek 为外部或待有界复测项 | REQ-015/TEST-011 通过，准备门禁通过，TASK-011 进行中 | 修复 DEF-018 至 DEF-021 并补聚焦测试 |
| 2026-08-19 23:25 +08:00 | 完成 DEF-018 至 DEF-022 实现和回归 | 聚焦 91 项、全量 152 项、编译和差异检查通过；U2 外部可达但正式容器仍需发布后复测 | REQ-016、TASK-011、TASK-012、TEST-012、TEST-013 完成 | 提交、推送、在线升级并逐站有界回归 |
| 2026-08-19 23:47 +08:00 | `c6eef4a` CI 与在线升级完成，九项有界执行进入终态或等待重试；读取 OpenCD 新截图并完成后续补丁 | SunnyPT/U2 成功；Audiences/HDDolby/CF/NodeSeek 分类准确；OpenCD 暴露 AJAX 控件差异；成功记录存在旧截图残留风险 | 新增并关闭 DEF-023，补强 DEF-021；最终 92 项聚焦、153 项全量通过 | 发布后续提交，仅复测 OpenCD 与成功截图状态 |
| 2026-08-19 23:58 +08:00 | `19dc9eb` CI、在线升级及 SunnyPT/OpenCD 有界复测完成 | SunnyPT 旧截图清理生效；OpenCD 图片缺少既有 CSS 特征，但当前样本 OCR 正确 | DEF-023 正式闭合；DEF-021 改用答案输入框的相邻图片定位并通过 92/153 项测试 | 发布最终 OpenCD 定位补丁并触发一次复测 |
| 2026-08-20 00:08 +08:00 | `9d28875` CI、在线升级及 OpenCD 单站复测完成 | 页面注入后字段名也未保留；仅靠属性选择器仍无法进入 OCR | DEF-021 最终改为逐 frame 几何邻接定位，保留尺寸与距离限制；92/153 项通过 | 发布最终几何定位补丁并只触发一次 OpenCD |
| 2026-08-20 00:15 +08:00 | 最终 `5fb8bbf` 推送且 CI `32274400785` 成功 | HomePc 远端版本检查连续超时；SSH 仍在 banner exchange 阶段拒绝连接；正式健康且停在 `9d28875` | TASK-013、TEST-014、REQ-017 转阻塞；不绕过在线升级门禁 | HomePc 到 GitHub 恢复后升级 `5fb8bbf` 并只触发一次 OpenCD |
| 2026-08-20 | HomePc 管理 API 恢复远端版本检查；接收 U2 实际未签到反馈 | API 返回 `remote_revision=5fb8bbf`、`can_upgrade=true`；U2 旧结果只访问首页且无点击或历史证据 | TASK-013 恢复进行中；新增 REQ-018、TASK-014、TEST-015、RISK-009 | 在线升级后分别单次回归 OpenCD 与 U2 |
| 2026-08-20 | `5fb8bbf` 在线升级和 OpenCD 单次回归完成；U2 误判修复通过聚焦 93 项、全量 154 项与编译检查 | OpenCD `clicked=true` 后返回已签到；U2 本次首页导航超时，旧版首页成功判定确认不可靠 | RISK-008 关闭；DEF-024 代码完成；TEST-015 待正式发布实测 | 提交推送 U2 修复，CI 后在线升级并只触发一次 U2 |
| 2026-08-20 | 按用户纠正拆分 `homepc` 与 `autosurf-web-debug`，迁移加密 Web 凭据并完成双技能验证 | 网站管理 API 与 SSH 无必然依赖，新技能可独立读取 `5fb8bbf` 正式状态 | 后续部署与站点调试改用独立 Web 技能；仓库范围不变 | 提交推送 U2 修复，CI 后在线升级并只触发一次 U2 |
| 2026-08-20 | U2 修复 `f7216c1` 推送、CI `32317500780` 成功；独立 Web 技能连续读取正式升级状态 | 网站 API 正常，GitHub 远端版本检查连续四次超时，正式仍为 `5fb8bbf` | 新增 RISK-010；未绕过升级门禁，未再次触发 U2 | Web 远端检查恢复后升级并只触发一次 U2 |
| 2026-08-20 | 远端检查恢复后在线升级 `f7216c1`；正式 SHA/健康通过；U2 复用执行尝试 1→2 | U2 仍在打开首页时超时，准确返回 `blocked`，没有再误报“已签到” | REQ-015 至 REQ-018 与完成门禁闭合；新增并接受 RISK-011 | 无 |
| 2026-08-20 20:10 +08:00 | 恢复既有账本并完成当前正式只读诊断 | OpenCD 今日历史存在但误报无入口；NodeSeek 后端已成功但 UI 陈旧；`blocked`/签到异常会跳过已启用的资料刷新 | 新增 REQ-019 至 REQ-022、DEF-025 至 DEF-028；完成门禁重开 | 实现历史兜底、动作隔离和活动状态轮询 |
| 2026-08-20 | 完成历史兜底、动作隔离和活动状态轮询实现 | PT 模块 89 项、管理 API 28 项和 JavaScript 语法检查通过 | TASK-016、TEST-016 至 TEST-018 代码门禁闭合 | 运行完整工程回归并复核差异 |
| 2026-08-20 20:30 +08:00 | 完成 162 项全量回归、编译与差异复核；正式发布前健康检查通过 | SSH 仍拒绝 banner，无法重新读取 PID 1；Web 升级通道、依赖和浏览器正常 | TASK-017 完成，TASK-018 进行中；不改变在线升级边界 | 提交推送并通过 Web 在线升级部署 |
| 2026-08-20 20:40 +08:00 | `c33a2da` CI、在线升级和首轮正式回归完成 | TJUPT 已 `already_done` 且刷新成功；U2 失败后已尝试资料页；OpenCD 记录页动态表格读取过早；NodeSeek 正式状态为成功且轮询代码已部署 | DEF-025、TASK-019 重新打开，其他本轮代码路径现场生效 | 修正 OpenCD 动态记录表读取并补正式反例测试 |
| 2026-08-20 | OpenCD 改为最多 5 秒轮询记录页并读取所有 frame 正文 | 动态填充反例、全量 162 项、编译、JS 语法和差异检查通过 | TASK-019 代码完成；TASK-018 继续 | 发布 OpenCD 动态记录补丁并只复用该站当前执行一次 |
| 2026-08-20 21:00 +08:00 | OpenCD 补丁 `fb5c485` 推送且 CI `32370900882` 通过 | HomePc Web、SSH、ICMP 同时持续不可达，本机 198.18 路由正常；无法启动第二次在线升级 | TASK-018、TEST-019、RISK-012 阻塞；代码和 CI 结果不等同于部署 | HomePc 恢复可达后在线升级到最新 `main`，并只复用 OpenCD 当前执行一次 |
| 2026-08-20 21:20 +08:00 | 两个连接技能切换至 `192.168.50.91` 并恢复正式 Web；读取 HDKyl/OKPT 第 4 次执行与截图；完成 WAF/52x 分类、自动放行等待及雷池单次确认实现 | HDKyl 是雷池 468 单按钮确认；OKPT 是 Cloudflare 522 源站超时，不是人机挑战；两站资料刷新均已独立尝试 | 新增 TASK-020；正式发布验证继续 | 完成新增确认测试后提交推送，在线升级并对受影响站点做有界验证 |
| 2026-08-20 21:51 +08:00 | `e96baca` 推送且 CI `32376023921` 成功；连续 5 次读取正式升级状态并重试新 SSH 地址 | 正式容器到 GitHub 的远端版本检查持续超时，SSH 仍拒绝 banner；Web 和健康端点正常 | TASK-020 代码完成；TASK-018、TEST-019/020 正式验证转 RISK-013 阻塞 | 容器出站恢复后在线升级最新 `main`，再各执行一次 HDKyl/OKPT 有界验证 |
| 2026-09-02 09:45 +08:00 | 读取雷池挑战脚本并完成 HDKylin、PigGo 无 CDP 对照实验 | 当前唯一命中为 `performance` DevTools 检查；两站无 CDP 15 秒均通过，重连后登录正常 | 新增 REQ-024、UNIT-010、IF-005、TASK-021 至 TASK-023、TEST-021/022；准备门禁通过 | 实现 `468` 探测、无 CDP 预热和预热页接管 |
| 2026-09-02 16:51 +08:00 | 完成雷池无 CDP 预热、预热页接管、失败回退和执行详情标记 | 聚焦 131 项、全量 201 项、编译和差异检查通过；本机 HDKylin 完整流程预热成功、登录态保留、无调试警告 | TASK-021/022、TEST-021/022、DEF-029 完成 | 提交并推送 `origin/main` |

## 十四、完成摘要

- 交付结果：M-Team 改为只刷新资料；PTTime 403 已签到、0ff 固定滑块与动态历史、SunnyPT 登录失效分类、Zhuque CSRF 资料刷新和死亡站点均已修正；Rousi、Zhuque、TJUPT 与 Audiences 正式统计已纠错。
- 验证方案：0ff 固定轨道滑块已本地自动完成；OpenCD 传统字符码适合本地 `ddddocr` 样本基准；TJUPT 为影视语义选择，需视觉模型或人工确认；Cloudflare 不自动破解。本轮未启用任何无置信度证据的自动提交。
- 需求验收：REQ-007 至 REQ-014 均完成；代码版本 `16f633b` 已发布到正式环境。
- 测试结论：最终聚焦 77 项、全量 120 项通过；`compileall` 与 `git diff --check` 通过；六次发布 CI 均成功。
- 正式结论：0ff 返回 7 条真实历史；Zhuque、M-Team、Rousi、Audiences 与 TJUPT 统计生效；Docker 重启窗口后恢复 `healthy`，部署仓库干净且入口进程正确。
- 遗留外部条件：SunnyPT 正式 AutoSurf 会话仍需重新同步；当前 404 已准确归为登录失效，不再误报普通失败或继续刷新。
- 回滚说明：见第九章。
- 完成门禁：未通过，等待 TASK-018 发布与正式回归。
- 当前扩展周期：`阻塞`；REQ-020 至 REQ-022 已有 `c33a2da` 正式证据，REQ-019 的 `fb5c485` 与 REQ-023 的 `e96baca` 等待部署。
- 下一步唯一动作：正式容器恢复访问 GitHub 后在线升级最新 `main`，再分别完成 OpenCD、HDKyl、OKPT 一次有界验证。
