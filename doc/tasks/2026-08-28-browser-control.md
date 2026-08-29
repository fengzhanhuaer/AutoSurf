# 任务：同端口 Chrome 浏览器控制界面

- 任务标识：`2026-08-28-browser-control`
- 状态：`已完成`
- 创建时间：`2026-08-28 16:46 +08:00`
- 更新时间：`2026-08-29 22:22 +08:00`
- 用户原始需求：在现有功能中添加一个专门显示并操作 Docker 内 Chrome 的界面。
- 用户最新指令：只发布已完成改动，不需要监控 Actions、在线升级或发布后验证；发布后修改 `autosurf-push-deploy` 技能，去除在线升级和发布后验证。
- 启用方式：明确长任务条件（跨浏览器生命周期、后端接口、前端交互与渲染验证）。

## 一、需求定义

### 1.1 背景与问题

AutoSurf 原先以 `persistent_headful` 模式在任务期间启动 Xvfb 与 Chromium，但只保存执行截图，没有用户可访问的实时操作界面。Docker Compose 仅暴露 `18980:8080`，用户要求通过既有 Web 管理入口查看并操作共享 Chrome，且明确禁止增加端口。

### 1.2 目标

在 `/app#browser-control` 提供受现有登录和局域网策略保护的浏览器远程桌面。页面显示 Xvfb 中完整 Google Chrome 窗口（含标签栏、地址栏及网页），并直接转发鼠标、滚轮和键盘输入。Chrome 随 AutoSurf 启动并常驻；自动签到短时取得同一浏览器的独占操作权，完成后只释放操作权，不关闭浏览器。

### 1.3 范围、非范围与约束

- 范围内：应用启动时拉起常驻 Xvfb/Chrome、异常退出自恢复、完整虚拟显示器画面、原生浏览器界面、鼠标键盘输入、共享浏览器操作互斥、普通 Chrome 人工登录、Playwright 按任务短时连接、一个持久化 User Data 根目录下的多个 Chrome Profile 与独立 Google Sync、管理界面与接口测试。
- 范围外：新增 Docker 暴露端口、额外 VNC/RFB 服务端口、绕过 CAPTCHA 或安全验证、多个独立 Chrome 容器、跨 Profile 自动迁移账号数据、多人同时输入、部署发布。
- 约束：仅支持 Docker/Linux 运行时，不实现 Windows 远程桌面运行时；所有客户端流量继续使用 `18980` 并继承 `require_login` 与 LAN 中间件；常驻进程不能永久阻塞自动签到；已有签到适配修改不得覆盖或回退；不记录 Cookie、密码或页面敏感 DOM；本地运行验证使用 WSL 或 Windows Docker Desktop，禁止使用 HomePc NAS 进行测试。

### 1.4 需求与验收标准

| 需求编号 | 需求描述 | 验收标准 | 优先级 | 状态 | 来源或最新变更 |
|---|---|---|---|---|---|
| REQ-001 | 同端口、安全访问浏览器控制 | 浏览器控制页和全部接口均通过现有 `18980`、现有登录与 LAN 中间件访问，Compose 无新增端口 | P0 | `已完成` | 用户最新指令“不使用新端口” |
| REQ-002 | 管理共享 Chrome 维护会话 | 可启动/停止会话；使用共享 profile；会话期间自动任务无法并发占用 profile；应用退出会清理会话 | P0 | `已完成` | 用户原始需求 |
| REQ-003 | 显示可刷新的网页内容截图 | 活跃会话可返回页面 PNG 帧 | P0 | `已取消` | 被 2026-08-29 的完整浏览器显示要求替代 |
| REQ-004 | 通过 Playwright 页面对象操作网页 | 支持页面坐标点击、滚轮和文字输入 | P0 | `已取消` | 被 2026-08-29 的显示器级原生输入替代 |
| REQ-005 | 现有风格下的可用界面 | 左侧保留“浏览器控制”；去掉伪地址栏和启停冷启动流程；桌面与移动端无重叠；繁忙和错误状态明确 | P1 | `已完成` | 用户最新纠正 |
| REQ-006 | 显示完整 Chrome 窗口 | 返回 Xvfb 根窗口画面，能看到 Chrome 标签栏、地址栏、网页内容和浏览器弹层；画面不落盘 | P0 | `已完成` | 用户最新纠正 |
| REQ-007 | 像远程桌面一样直接操作浏览器 | 鼠标移动、单/双击、滚轮、常用组合键及 ASCII 文字作用于 X11 Chrome 原生窗口，坐标按实际帧映射 | P0 | `已完成` | 用户最新纠正 |
| REQ-008 | Chrome 始终打开且无冷启动 | AutoSurf 启动后自动准备浏览器；控制页无需启动按钮；异常退出自动恢复；签到结束不关闭进程 | P0 | `已完成` | 用户最新指令 |
| REQ-009 | 远程浏览器窗口支持全屏 | 控制页可用明确按钮进入全屏；按钮状态随全屏进入、退出和 `Esc` 同步；不支持 Fullscreen API 时提示错误 | P1 | `已完成` | 用户最新指令“窗口应该支持全屏” |
| REQ-010 | 容器首次启动时一次性初始化浏览器环境 | 共享 profile 尚未初始化时，容器启动先批量写入 Cookie 和 WebStorage 并落持久化标记；后续容器重启及签到任务只读取 Chrome 当前环境，API 适配器也不再回退旧凭据 | P0 | `已完成` | 用户明确首次容器启动自动注入，后续 Cookie/WebStorage/API 均按实际浏览器环境操作 |
| REQ-011 | 使用官方 Google Chrome 并持久化完整登录数据 | Docker amd64 镜像安装官方 Chrome stable；Playwright 使用 `chrome` channel；`user-data-dir` 固定在 `/app/browser/profiles/shared`，容器重建后 Google 登录态与站点存储保持；不发布 arm64 | P0 | `已完成` | 用户明确“使用chrome替换chromium”、保证谷歌登录数据持久化并且“不需要arm” |
| REQ-012 | 可选择并持久化远程桌面分辨率 | 浏览器控制页提供常用分辨率；选择 1920x1080 后安全重启 Xvfb、Chrome 和远程桌面，状态回报新尺寸；刷新页面及容器重启后保持选择；全屏画面比例与选择一致 | P0 | `已完成` | 用户最新指令 |
| REQ-013 | 普通 Chrome 人工登录、多个 Sync Profile 与 Playwright 生命周期分离 | Chrome 由宿主直接启动且不含 Playwright 自动化启动参数；人工访问 Google 登录页时 `navigator.webdriver=false`；Playwright 仅在初始化或签到时通过容器回环 CDP 连接，操作结束后断开且 Chrome/noVNC/人工页面继续运行；完整 User Data 根目录持久化 `Default`、`Profile 1` 等多个资料，每个资料可独立登录与 Sync；启动参数不固定单一 `--profile-directory` | P0 | `已完成` | 用户明确“解决无法登陆”“Playwright 可以单独一个操作，与nvc独立”“跟windows下一样，支持多个chrome sync” |
| REQ-014 | 发布 AutoSurf 源码 | 范围内功能代码提交并推送到 `origin/main`；不监控 Actions、不调用在线升级、不执行发布后验证 | P0 | `已完成` | 功能提交 `b473580` 已推送 |
| REQ-015 | 收窄 AutoSurf 发布技能 | `autosurf-push-deploy` 只保留发布前测试、Git 提交和推送；删除在线升级、部署、CI 监控、发布后检查和实时签到回归；技能元数据同步且校验通过 | P0 | `已完成` | 用户明确“发布后，修改技能，去除发布后验证”“去除在线升级” |

## 二、总体架构

### 2.1 当前现状

- `persistent_chromium_session()` 为每次任务启动临时 Xvfb 和持久化 Chromium context，并通过 `_PROFILE_LOCKS` 串行共享 profile。
- `APIRouter(prefix="/api/v1", dependencies=[Depends(require_login)])` 已保护管理 API；`LanAccessMiddleware` 统一限制来源地址。
- 管理界面是静态 `admin.html`、`admin.js`、`admin.css`，用 hash 切换左侧视图。
- Compose 只映射 `0.0.0.0:18980:8080`，本任务保持不变。

### 2.2 目标架构

`BrowserControlService` 随应用启动常驻 Xvfb、由普通子进程直接启动的 Google Chrome、x11vnc 和 noVNC/websockify。Chrome 使用 `/app/browser/profiles/shared` 作为完整 User Data 根目录，内含多个 Chrome Profile；不固定 `--profile-directory`，由 Chrome 原生资料选择器创建、切换和管理各自 Sync。浏览器与 noVNC 生命周期不依赖 Playwright；自动任务只在执行期间持有独占操作锁，通过容器回环 CDP 临时附加，退出后仅断开 Playwright，不关闭 Chrome。x11vnc 仅监听容器回环地址，websockify 仅监听 Unix socket；FastAPI 在 `/browser-control/remote/` 代理其 HTTP 与 WebSocket，客户端仍只连接现有 `18980`，Docker 无新增暴露端口。

### 2.3 关键模块与职责

| 模块 | 当前职责 | 目标职责 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|---|
| 浏览器宿主 | 单次自动化浏览器生命周期 | 常驻 Xvfb/普通 Chrome，共享 User Data 根目录，并向自动任务提供短时 CDP 操作租约 | RunContext、URL | Chrome 进程、临时 BrowserContext、busy 状态 | Chrome、Playwright CDP、`persistent_chromium_session` |
| 远程桌面 | 无 | x11vnc 捕获同一 Xvfb，noVNC/websockify 传输画面并注入输入 | X11 显示器、WebSocket | 视频帧、鼠标键盘 | Debian 稳定包 x11vnc/noVNC/websockify |
| 管理 API | 登录后的业务接口 | 代理 websockify Unix socket 的 HTTP/WebSocket，并暴露宿主状态 | 同源 HTTP/WS | HTML/静态资源/WS/JSON | FastAPI、aiohttp、服务实例 |
| 管理前端 | hash 视图与业务设置 | 通过同源 iframe 嵌入 noVNC 客户端，显示启动、恢复、自动任务占用和错误状态 | 用户鼠标/键盘 | 完整 Chromium 远程操作 | noVNC Web 客户端 |
| 应用生命周期 | 调度器与 worker | 启动浏览器宿主并在退出时按逆序清理 | startup/shutdown | 常驻进程、自恢复 | FastAPI lifespan |

### 2.4 关键流程

| 流程 | 发起方 | 处理方 | 数据或状态变化 | 失败处理 | 关联需求 |
|---|---|---|---|---|---|
| 应用启动 | FastAPI lifespan | BrowserControlService | 启动 Xvfb、普通 Chrome、x11vnc 和 websockify Unix socket，并注册共享浏览器提供者；无待初始化凭据时不启动 Playwright | 失败记录状态并退避自恢复，不阻断管理端启动 | REQ-002/008/013 |
| 远程显示与输入 | Web UI iframe | FastAPI proxy → noVNC/websockify → x11vnc → X11 | 同源 WebSocket 持续传输完整画面和原生输入 | 未登录拒绝；Unix socket 未就绪返回 503；前端显示恢复状态 | REQ-001/005/006/007 |
| 自动签到 | worker | persistent_chromium_session → 常驻宿主 | 获取独占操作租约、新建任务标签页、执行后关闭任务标签页并释放租约 | UI 标记自动任务占用；异常仍释放租约 | REQ-002/008 |
| 异常退出与关闭 | supervisor / lifespan | BrowserControlService | Chrome、x11vnc 或 websockify 退出后清理并退避重启；应用退出时停止重启并清理 | 状态保留最近错误 | REQ-008/013 |

### 2.5 接口记录

| 接口编号 | 接口名称 | 调用方 | 提供方 | 输入、输出与错误契约 | 实现位置 | 兼容要求 | 关联需求、任务与测试 | 状态与证据 |
|---|---|---|---|---|---|---|---|---|
| IF-001 | 浏览器会话状态 | 管理前端 | `GET /api/v1/browser-control` | JSON：active/starting/url/title/viewport/error；登录必需 | `api.py` / `browser_control.py` | 不影响现有 API | REQ-001/003；TASK-002；TEST-002 | `已实现，focused test 通过` |
| IF-002 | 浏览器会话启停 | 管理前端 | `POST/DELETE /api/v1/browser-control/session` | 旧版冷启动接口 | 已移除 | 常驻宿主不再需要启停 | REQ-002/008 | `已取消并移除` |
| IF-003 | 旧页面截图帧 | 管理前端 | `GET /api/v1/browser-control/frame` | 页面 PNG | 旧实现 | 被完整桌面要求替代 | REQ-003 | `待移除兼容入口` |
| IF-004 | 旧 Playwright 页面输入 | 管理前端 | `POST /navigate`、`POST /input` | 页面级动作 JSON | 旧实现 | 被 X11 原生输入替代 | REQ-004 | `待移除兼容入口` |
| IF-005 | noVNC 同源 HTTP 代理 | iframe | `GET /browser-control/remote/{path}` | 去除外部前缀后转发到 websockify Unix socket；继承登录和 LAN 限制；未就绪 503 | `main.py` / `browser_control.py` | 不新增端口 | REQ-001/005/006/008；TASK-006；TEST-007 | `已实现，focused test 通过` |
| IF-006 | noVNC 同源 WebSocket 代理 | iframe | `WS /browser-control/remote/websockify` | 校验会话 Cookie 和同源 Origin 后双向转发 text/binary/close 到 Unix socket | 同上 | 同源、同端口、无 VNC 端口暴露 | REQ-001/006/007；TASK-006；TEST-007 | `已实现，focused test 通过` |
| IF-007 | 远程桌面分辨率切换 | 管理前端 | `PATCH /api/v1/browser-control/resolution` | 输入受支持的 width/height；正执行自动任务时返回 409；成功后返回重启后的状态和分辨率列表 | `api.py` / `browser_control.py` | 不新增端口；共享 profile 不变 | REQ-012；TASK-013；TEST-012/013 | `已实现并通过认证、校验和重启测试` |
| IF-008 | 容器回环 Chrome DevTools 接口 | BrowserControlService 的短时 Playwright 操作 | 普通 Chrome 子进程 | 仅监听 `127.0.0.1`；使用固定自定义 User Data 根目录；返回已有普通 Profile 页面上下文；断开 Playwright 不关闭 Chrome | `browser_session.py` / `browser_control.py` | 不新增宿主端口；现有 handler 仍接收 Playwright `BrowserContext` | REQ-013；TASK-016；TEST-014/015 | `已实现；本机 Docker 与单元测试通过` |

### 2.6 架构决策引用

| 决策编号 | 对架构的影响 | 相关模块或接口 |
|---|---|---|
| DEC-001 | 已被 DEC-004 替代；页面截图无法显示 Chromium 原生界面 | IF-003/IF-004 |
| DEC-002 | 维护会话复用现有 `persistent_chromium_session`，以共享锁阻止自动任务并发 | BrowserControlService |
| DEC-003 | 已被 DEC-004 替代；PNG 短轮询不是远程桌面 | IF-003、旧 admin.js |
| DEC-004 | 采用 noVNC/x11vnc 远程桌面，经 websockify Unix socket 和 FastAPI 同源代理接入 | IF-005/IF-006、BrowserControlService |
| DEC-005 | Chromium 进程常驻，自动任务只租用操作权并使用临时标签页 | browser_session、签到 handler |
| DEC-007 | 分辨率使用受支持选项并持久化；切换时重启共享显示栈 | BrowserControlService、IF-007、管理前端 |
| DEC-008 | 普通 Chrome 独立常驻，Playwright 仅通过回环 CDP 短时附加；完整 User Data 根目录持久化多个 Chrome Profile | browser_session、BrowserControlService、IF-008 |

## 三、单元设计

### 3.1 受影响单元

| 单元编号 | 文件或位置 | 职责 | 输入 | 输出 | 依赖 | 关联需求 |
|---|---|---|---|---|---|---|
| UNIT-001 | `src/autosurf/browser_control.py`、`src/autosurf/automations/browser_session.py` | 普通 Chrome 子进程、短时 CDP 租约、多个 Profile 的 User Data 根目录、会话状态机、显示尺寸设置、远程桌面进程和清理 | 分辨率/生命周期/RunContext | 状态/远程桌面/临时 BrowserContext | Chrome、Playwright CDP、数据库 | REQ-002/006/008/012/013 |
| UNIT-002 | `src/autosurf/api.py`、`main.py` | Pydantic 契约、受保护路由、服务注入与 shutdown | HTTP | JSON/错误 | FastAPI、UNIT-001 | REQ-001/002/012 |
| UNIT-003 | `src/autosurf/web/admin.*` | 左侧视图、分辨率选择、远程桌面和全屏交互 | DOM 事件 | API 请求与渲染 | IF-001/005/006/007 | REQ-005/006/007/009/012 |
| UNIT-004 | `tests/test_browser_control.py`、现有 Web 静态测试 | 服务/API/前端契约回归 | fake Page / ASGI | 断言 | pytest/httpx | 全部 |

### 3.2 处理与异常规则

| 单元编号 | 正常处理规则 | 异常处理规则 | 兼容要求 | 验证方式 |
|---|---|---|---|---|
| UNIT-001 | 单会话；所有 Page 操作经异步锁串行；共享 profile 锁覆盖整个会话 | 重复启动返回现状；浏览器退出记录短错误；stop 幂等；输入严格限长/限坐标 | 不改变自动任务 context manager 行为 | fake session 单测 |
| UNIT-002 | 全部路由挂 `/api/v1` 登录依赖；帧 `no-store` | 未激活 409；无效 URL/动作 422 | 不新增端口/Compose 项 | ASGI 认证与契约测试 |
| UNIT-003 | 仅进入视图时轮询；图片保持 1365:768 比例；容器可聚焦收键盘 | 请求失败停止帧更新并显示状态；离开视图清理定时器 | 延续现有样式，移动端可滚动 | Playwright 桌面/移动截图与交互 |
| UNIT-004 | 覆盖状态、认证、生命周期和动作分发 | 不依赖真实外站或真实 Chromium的单元测试 | 保持完整测试通过 | focused + full pytest |

## 四、执行任务

### 4.1 当前交接

- 当前阶段：已完成
- 当前计划步骤：无
- 当前门禁：完成门禁通过
- 最近完成检查点：功能提交 `b473580` 已推送；24 项定向和 188 项全量测试通过；发布技能已去除在线升级与发布后验证并通过 `quick_validate.py`。
- 工作区状态：基于 `01c2a41` 的未提交修改；未发布、未部署；未使用 HomePc NAS 测试。
- 下一步唯一动作：无。
- 恢复时先读取：本账本、`git status`、`browser_session.py`、`main.py`、`api.py`、`admin.html/js/css`。

### 4.2 任务计划

| 任务编号 | 工作内容 | 状态 | 关联需求 | 文件或接口范围 | 完成条件 |
|---|---|---|---|---|---|
| TASK-001 | 基线调查、架构与准备门禁 | `已完成` | 全部 | 账本、现有代码 | 门禁通过 |
| TASK-002 | 实现浏览器控制服务、API 与生命周期 | `已完成` | REQ-001 至 004 | UNIT-001/002、IF-001 至 004 | focused tests 通过 |
| TASK-003 | 实现左侧浏览器控制界面和交互 | `已完成` | REQ-003 至 005 | UNIT-003 | UI 流程可操作 |
| TASK-004 | 完整测试、渲染 QA、差异审查与完成门禁 | `已完成` | 全部 | UNIT-004、全仓 | 追踪闭合、门禁通过 |
| TASK-005 | 重新调查完整桌面和常驻生命周期方案 | `已完成` | REQ-001/005/006/007/008 | 上游 Selkies、现有 browser session | 修正版准备门禁通过 |
| TASK-006 | 实现常驻共享 Chromium、noVNC Unix socket 与同源代理 | `已完成` | REQ-001/002/006/007/008 | browser_session、browser_control、main/api、依赖 | focused 后端测试通过 |
| TASK-007 | 将管理页改为完整远程桌面 iframe | `已完成` | REQ-005/006/007/008 | admin.html/js/css | 无旧伪地址栏和启停流程；响应式预览通过 |
| TASK-008 | Docker、完整回归与真实远程桌面 QA | `已完成` | 全部有效需求 | Dockerfile、tests、账本 | Docker 中完整 Chrome 可见可操作 |
| TASK-009 | 增加远程桌面全屏切换并验证退出同步 | `已完成` | REQ-009 | admin.html/js/css、静态契约测试 | 桌面和移动端可进入/退出全屏，布局无溢出 |
| TASK-010 | 在容器首次启动时一次性初始化 Cookie 与 WebStorage | `已完成` | REQ-010 | CredentialService、BrowserControlService、browser_session、pt_signin、tests | 启动时初始化并持久化完成标记；任务期从浏览器读取 Cookie 与 localStorage |
| TASK-011 | 将 Docker 浏览器替换为官方 Google Chrome 并验证 profile 持久化 | `已完成` | REQ-011 | Dockerfile、entrypoint、upgrade、browser_session、upgrade UI、README、tests | CI amd64 镜像成功；本机正式镜像显示 Chrome，重建前后 profile 标记保持 |
| TASK-012 | 调查全屏不随显示器变化的真实约束并补齐设计 | `已完成` | REQ-012 | browser_session、browser_control、admin.*、账本 | 确认 Xvfb 与 Chrome 均固定为 1365x768；准备门禁通过 |
| TASK-013 | 实现分辨率持久化、受保护切换接口和前端选择器 | `已完成` | REQ-012 | UNIT-001/002/003、IF-007 | 1920x1080 可选；重启后保持；忙时不打断任务 |
| TASK-014 | 定向回归、渲染与真实本机容器验证 | `已完成` | REQ-012 | UNIT-004、本机 Docker Desktop | API/单测/全量测试通过；桌面选择和全屏比例实测通过 |
| TASK-015 | 验证普通 Chrome、短时 CDP 与多个 Chrome Profile 的真实行为 | `已完成` | REQ-013 | 本机 Docker 临时 User Data、IF-008、账本 | `webdriver=false`；Playwright 断开不关闭 Chrome；明确多个 Profile 的可见性和选择边界 |
| TASK-016 | 实现普通 Chrome 常驻、短时 CDP 租约与多 Profile 持久化 | `已完成` | REQ-013 | UNIT-001、IF-008、相关测试 | noVNC 独立常驻；任务接口兼容；不固定单一 Profile；Chrome 退出可恢复 |
| TASK-017 | 定向回归、全量测试和本机 Docker 登录/Profile 验证 | `已完成` | REQ-013 | UNIT-004、本机 Docker Desktop | 单测和全量测试通过；多个 Profile 跨重启保持；禁止使用 HomePc |
| TASK-018 | 提交并推送源码 | `已完成` | REQ-014 | Git、`origin/main` | 功能提交 `b473580` 推送成功 |
| TASK-019 | 修改并校验 AutoSurf 发布技能 | `已完成` | REQ-015 | `C:\Users\fengz\.codex\skills\autosurf-push-deploy` | SKILL 与 UI 元数据无在线升级和发布后验证流程；官方校验器通过 |

### 4.3 变更记录

| 文件、配置或接口 | 变更内容 | 原因 | 关联需求与任务 | 验证方式 | 回滚引用 |
|---|---|---|---|---|---|
| 本账本 | 建立需求、架构、接口、任务和测试追踪 | 长任务管理 | 全部 / TASK-001 | 人工核对 | RB-001 |
| `src/autosurf/browser_control.py` | 新增共享 Chrome 维护会话、截图、导航与输入服务 | 提供同端口控制能力 | REQ-002/003/004 / TASK-002 | `tests/test_browser_control.py` | RB-001 |
| `src/autosurf/api.py`、`main.py` | 新增受保护接口并接入应用生命周期 | 复用现有认证、LAN 与 18980 | REQ-001/002/003/004 / TASK-002 | focused API test | RB-001 |
| `src/autosurf/web/admin.html/js/css` | 新增左侧控制页、帧轮询和响应式交互 | 用户可直接查看并操作 Docker Chrome | REQ-003/004/005 / TASK-003 | 桌面/移动真实渲染通过 | RB-001 |
| `tests/test_browser_control.py` | 覆盖服务、API、认证、UI 契约和单端口约束 | 防止生命周期与端口回归 | 全部 / TASK-002/004 | 5 passed | RB-001 |
| `src/autosurf/automations/browser_session.py`、`src/autosurf/browser_control.py` | 普通 Chrome 子进程、回环 CDP、短时 Playwright、多 Profile 根目录和 Chrome 退出自恢复 | 修复 Google 登录拒绝并保持 Windows 式多 Sync Profile | REQ-013 / TASK-016 | TEST-014/015/016 | RB-001 |
| `tests/test_browser_control.py`、`tests/test_browser_signin.py` | 覆盖独立生命周期、任务 Playwright 复用、启动参数和 Profile 数据保留 | 防止登录环境和多 Profile 回归 | REQ-013 / TASK-016/017 | 24 项定向 + 188 项全量 | RB-001 |

## 五、测试与验证

### 5.1 测试计划与结果

| 测试编号 | 测试目标 | 关联需求与任务 | 方法或准确命令 | 预期结果 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|
| TEST-001 | 服务状态机与动作分发 | REQ-002/003/004 / TASK-002 | `.venv\Scripts\python.exe -m pytest tests/test_browser_control.py -q` | fake browser 下全部通过 | 5 passed | `通过` | 2026-08-28 运行 |
| TEST-002 | API 认证、同端口契约、帧与错误 | REQ-001 至 004 / TASK-002 | 合并至 `tests/test_browser_control.py` | 未认证 401，活跃流程正确 | 5 passed 中覆盖 | `通过` | 2026-08-28 运行 |
| TEST-003 | 管理页静态资源与 hash 视图 | REQ-005 / TASK-003 | 现有静态资源测试 + 定向 pytest | 元素/脚本契约存在 | 7 passed | `通过` | 2026-08-28 运行 |
| TEST-004 | 浏览器渲染与操作 | REQ-003/004/005 / TASK-004 | 常规 Playwright；桌面 1365×900、移动 390×844 | 非空、无控制台错误、启动/帧/点击状态可见 | 桌面点击并发送 `qa-user` 成功；移动图片 356px、无横向溢出、控制台零错误 | `通过` | Browser plugin not available，按 Skill 使用 regular Playwright |
| TEST-005 | 完整回归 | 全部 / TASK-004 | `.venv\Scripts\python.exe -m pytest -q` | 全部通过 | 185 passed，1 个现有 SQLAlchemy/SQLite 弃用警告 | `通过` | 2026-08-29 13:18 +08:00 |
| TEST-009 | 远程桌面全屏切换 | REQ-009 / TASK-009 | regular Playwright；1365×900、390×844 | 点击进入全屏，面板铺满视口；再次点击退出；状态同步；无溢出和控制台错误 | 两种视口均进入完整视口并可退出，零溢出、零控制台错误 | `通过` | 2026-08-29 运行 |
| TEST-010 | Cookie/WebStorage 仅在首次容器启动初始化 | REQ-010 / TASK-010 | `.venv\Scripts\python.exe -m pytest -q` | 两类凭据均进入初始化源；首次启动注入并落标记；第二次启动不回填；任务/API 使用浏览器当前 Cookie 与 localStorage | 184 passed，1 个现有 SQLite 弃用警告 | `通过` | 2026-08-29 |
| TEST-011 | Google Chrome 镜像与持久 profile | REQ-011 / TASK-011 | CI amd64 build；本机 Docker 拉取、`google-chrome-stable --version`、远程桌面、容器重建前后 profile 文件校验 | 正式 Chrome 启动；`/app/browser/profiles/shared` 挂载持久；无 Chromium 下载路径或 arm64 发布 | CI `33235957823` 成功；Chrome 152.0.7977.64；容器健康；完整窗口可见；键盘导航改变 URL 并恢复；标记 SHA256 保持 `185136E2...84CA` | `通过` | 2026-08-29，本机 Docker Desktop |
| TEST-012 | 分辨率设置、校验、持久化和共享显示重启 | REQ-012 / TASK-013 | focused pytest | 默认值兼容；只接受支持尺寸；忙时 409；切换后 launcher 和状态使用新尺寸 | 22 项定向测试通过；覆盖 401、422、409、数据库持久化、重启和 1920x1080 启动参数 | `通过` | 2026-08-29 |
| TEST-013 | 1920x1080 管理页与全屏渲染 | REQ-012 / TASK-014 | regular Playwright + 本机 Docker Desktop（禁止 HomePc） | 选择器可操作；iframe 比例更新；容器实际 Xvfb/Chrome/状态均为 1920x1080；全屏无重叠 | 桌面选择值和比例为 1920x1080；全屏面板 1920x1080；移动端无横向溢出；两者控制台零错误；Docker Xvfb dimensions 为 1920x1080 | `通过` | Browser plugin 未暴露，使用 regular Playwright |
| TEST-014 | 普通 Chrome 与短时 CDP 生命周期 | REQ-013 / TASK-015/016 | 单元测试 + 本机 Docker 临时 Profile | Chrome 命令无 Playwright 自动化参数；`webdriver=false`；CDP 仅回环；Playwright 断开后 Chrome/noVNC 存活 | 24 项定向测试通过；隔离应用进入 Google `signin/identifier` 且非 rejected；`webdriver=false`；Playwright 退出后 Chrome PID 仍存活；Chrome 被结束后服务自动拉起新 PID | `通过` | 2026-08-29，本机 Docker Desktop |
| TEST-015 | 多 Chrome Profile/Sync 数据持久化 | REQ-013 / TASK-015/017 | 本机 Docker 临时和应用 Profile | `Default`/`Profile 1` 等目录及 Local State 元数据保留；启动不锁定一个资料；重启后资料仍存在 | 隔离应用创建两份资料；`Local State` 保存两份元数据；启动命令无 `--profile-directory`；Chrome 自恢复后两份目录和元数据仍在 | `通过` | 2026-08-29，本机 Docker Desktop；未使用 HomePc |
| TEST-016 | REQ-013 完整回归 | REQ-013 / TASK-017 | `.venv\Scripts\python.exe -m pytest -q` | 全部测试通过 | 188 passed，1 个现有 SQLAlchemy/SQLite 弃用警告 | `通过` | 2026-08-29 |
| TEST-017 | 发布后 Actions、在线升级与运行验证 | REQ-014 / TASK-018 | GitHub Actions、升级 API、容器与浏览器控制 API | 用户明确不需要验证 | 未执行 | `已取消` | 2026-08-29，按用户最新指令取消 |
| TEST-018 | 发布技能结构校验 | REQ-015 / TASK-019 | `quick_validate.py C:\Users\fengz\.codex\skills\autosurf-push-deploy` | 技能 frontmatter、名称和内容结构有效 | `Skill is valid!` | `通过` | 2026-08-29 |

### 5.2 未执行测试

`ruff` 未执行：当前虚拟环境未安装该模块；以 `compileall`、`git diff --check`、24 项定向测试、188 项全量测试和本机 Docker 验证替代。该缺口不影响运行时行为结论。

## 六、端到端追踪

| 需求编号 | 验收标准 | 架构或单元 | 任务编号 | 文件、配置或接口 | 测试编号 | 结果与证据 | 状态 |
|---|---|---|---|---|---|---|---|
| REQ-001 | 同端口、现有认证/LAN、无 Compose 端口 | UNIT-002 | TASK-002/004 | IF-001 至 004、`compose.yaml` | TEST-002/005 | API、认证、Compose 和 full test 通过 | `已完成` |
| REQ-002 | 会话启停、共享 profile 互斥、shutdown 清理 | UNIT-001/002 | TASK-002/004 | `browser_control.py`、`main.py` | TEST-001/002/005 | 生命周期、启停竞态和 full test 通过 | `已完成` |
| REQ-003 | 旧页面 PNG 帧 | UNIT-001/003 | TASK-002/003/004 | IF-003 | TEST-001/002/004/005 | 被完整桌面需求替代 | `已取消` |
| REQ-004 | 旧 Playwright 页面输入 | UNIT-001/003 | TASK-002/003/004 | IF-004 | TEST-001/002/004/005 | 被显示器级输入替代 | `已取消` |
| REQ-005 | 左侧入口、状态完整、响应式可用 | UNIT-003 | TASK-007/008 | iframe、`admin.html/js/css` | TEST-007/008/011 | 本机管理页显示运行中，完整窗口无重叠 | `已完成` |
| REQ-006 | 完整 Chrome 窗口可见 | UNIT-001/003 | TASK-006/007/008 | IF-005/006、noVNC | TEST-006/007/008/011 | noVNC connected，1066×600 可见画布含标签栏和地址栏 | `已完成` |
| REQ-007 | 原生鼠标键盘远程控制 | UNIT-001/003 | TASK-006/007/008 | IF-006、noVNC | TEST-006/007/008/011 | 地址栏输入改变浏览器 URL 并恢复到 about:blank | `已完成` |
| REQ-008 | 应用启动即常驻且自恢复 | UNIT-001/002 | TASK-006/008 | BrowserControlService、lifespan | TEST-006/008/011 | 两次容器重建后均自动 active，starting=false，error=null | `已完成` |
| REQ-009 | 全屏进入、退出和状态同步 | UNIT-003 | TASK-009 | `admin.html/js/css`、Fullscreen API | TEST-009 | 桌面与移动视口均通过 | `已完成` |
| REQ-010 | 首次容器启动初始化 Cookie/WebStorage，后续任务和 API 只用浏览器环境 | UNIT-001/002 | TASK-010 | `services.py`、`browser_control.py`、`browser_session.py`、`pt_signin.py`、`main.py` | TEST-010 | 完整回归通过 | `已完成` |
| REQ-011 | 官方 Chrome 运行时和完整 Google 登录数据跨容器持久化 | UNIT-001/002/003 | TASK-011 | Docker shell、Chrome channel、共享 profile、升级状态 UI | TEST-011 | Chrome 152；仅 amd64；profile 标记重建前后哈希一致 | `已完成` |
| REQ-012 | 可选并持久化 1920x1080 等远程桌面尺寸 | UNIT-001/002/003 | TASK-012/013/014 | IF-007、Xvfb、Chrome、管理页选择器 | TEST-012/013 | API、服务重启、数据库、桌面/移动 UI 和本机 Docker Xvfb 均通过 | `已完成` |
| REQ-013 | 普通 Chrome、Playwright 短时 CDP、多个持久化 Sync Profile | UNIT-001/004 | TASK-015/016/017 | IF-008、User Data 根目录、BrowserControlService | TEST-014/015/016 | Google identifier 正常、`webdriver=false`、短时连接后 Chrome 常驻、自恢复后两个 Profile 保留、188 项全量测试通过 | `已完成` |
| REQ-014 | 提交并推送到 main | UNIT-001/002/003/004 | TASK-018 | Git、`origin/main` | TEST-016；TEST-017 按用户指令取消 | 功能提交 `b473580` 推送成功 | `已完成` |
| REQ-015 | 发布技能不再升级或验证部署 | 不适用，用户级技能 | TASK-019 | `autosurf-push-deploy/SKILL.md`、`agents/openai.yaml` | TEST-018 | 技能校验通过 | `已完成` |

## 七、决策与冲突记录

### 7.1 决策记录

| 决策编号 | 触发原因 | 采用方案 | 理由与证据 | 替代方案 | 影响范围 | 替代关系 | 状态 |
|---|---|---|---|---|---|---|---|
| DEC-001 | 用户禁止新端口 | FastAPI 同源截图与输入代理 | 第一版复用 18980，但无法显示原生浏览器界面 | noVNC 6080/VNC 5900 | 旧接口与 UI | 被 DEC-004 替代 | `已替代` |
| DEC-002 | 自动任务与人工操作共享 profile | 维护会话持有现有 profile asyncio lock | 第一版无需修改调度数据即可串行 | 单独 profile 或暂停所有任务 | 浏览器生命周期 | 被 DEC-008 的常驻 Chrome + 短时 operation lock 替代 | `已替代` |
| DEC-003 | 同端口下需要简单可靠画面 | PNG 轮询而非 WebSocket/noVNC | 第一版依赖少，但不是远程桌面 | WebSocket 视频流 | IF-003/前端 | 被 DEC-004 替代 | `已替代` |
| DEC-004 | 用户要求完整浏览器远程桌面且不新增端口 | x11vnc 仅监听容器回环地址；noVNC/websockify 监听 Unix socket；FastAPI 在 `18980` 同源代理 | Debian 稳定包可重复构建，完整支持 X11 画面和输入，外部无新增端口 | Selkies、Guacamole、自研 X11 轮询 | 浏览器宿主、IF-005/006、Docker | 替代 DEC-001/003，并由 DEC-006 修订实现 | `有效` |
| DEC-005 | 用户要求始终打开、无冷启动 | Chromium 与 Xvfb 随应用常驻；任务租用同一 context 并使用临时标签页 | 第一版实现了进程常驻，但 Playwright 仍拥有浏览器进程 | 控制专用 profile、任务前停控制浏览器 | browser_session、handlers、lifespan | 常驻进程目标保留；常驻 Playwright context 部分被 DEC-008 替代 | `已替代` |
| DEC-006 | GitHub Linux CI 无法安装 Selkies 开发版依赖 | 从 Selkies 开发提交切换到 Debian 稳定 noVNC/x11vnc/websockify 包 | Selkies 开发版依赖未发布的 `pixelflux~=2.1.0`，新 Docker 与 CI 均无法解析；noVNC 路径满足同端口和完整桌面要求 | 固定临时 Actions 产物、嵌入上游容器 | Docker、远程桌面进程、代理路径 | 修订 DEC-004 的实现 | `有效` |
| DEC-007 | 客户端全屏只能放大画布，服务端无法据此自动改变 Xvfb | 提供 1280x720、1365x768、1600x900、1920x1080 固定选项；选择持久化，切换时在操作锁内重启共享显示栈 | 分辨率改变必须重建 Xvfb 与 Chrome；固定选项可控制资源消耗并避免任意超大画布；profile 目录不变 | 每次进入全屏按客户端 screen 自动重启、任意宽高输入 | browser_session、BrowserControlService、IF-007、管理前端 | 补充 DEC-004/005 | `有效` |
| DEC-008 | Google 拒绝 Playwright 启动的浏览器，且用户要求 noVNC 与 Playwright 独立、支持多个 Sync | 由 BrowserControlService 直接启动普通 Chrome；Playwright 仅在初始化和任务期间通过回环 CDP 附加；持久化完整 User Data 根目录且不固定 `--profile-directory` | 本机 Docker 验证普通 Chrome `webdriver=false`、Google 登录页可进入 identifier、Playwright stop 后 Chrome 仍存活；Chrome 原生 Profile 模型与 Windows 一致 | 继续由 Playwright `launch_persistent_context` 启动；每个账号单独容器 | browser_session、BrowserControlService、IF-008、测试 | 替代 DEC-005 中“常驻 Playwright context”部分 | `有效` |

### 7.2 冲突记录

无。

## 八、缺陷记录

| 缺陷编号 | 现象 | 根因 | 修复方案 | 关联需求 | 状态 |
|---|---|---|---|---|---|
| DEF-001 | 上一版只显示网页内容，无法看到标签栏和地址栏；进入页面还要冷启动 | 使用 `Page.screenshot()` 和 Playwright 页面输入，且维护会话由 UI 临时创建 | 改用 noVNC/x11vnc 捕获 Xvfb 根显示器；Chrome 随应用常驻 | REQ-005/006/007/008 | `已修复` |
| DEF-002 | GitHub CI 和全新 Docker 在安装 Selkies 时失败 | 固定的 Selkies 开发提交依赖尚未发布的 `pixelflux~=2.1.0` | 移除不可解析的开发依赖，使用 Debian 稳定 noVNC/x11vnc/websockify 包 | REQ-006/007/008 | `已修复，待 CI 验证` |
| DEF-003 | 远程桌面已 active 后状态仍返回 `starting=true` | supervisor 在 `_run_once()` 整个常驻生命周期结束前才清除 starting | Unix socket 就绪后立即清除 starting，并增加回归断言 | REQ-005/008 | `已修复` |
| DEF-004 | noVNC 页面同源代理返回 500 | Unix socket HTTP 客户端使用 `aiohttp`，但从 Selkies 切换后未将它声明为直接项目依赖 | 在 `pyproject.toml` 显式加入 `aiohttp>=3.11,<4` 并增加依赖契约断言 | REQ-001/006/007 | `已修复并通过 Docker 复验` |
| DEF-005 | noVNC WebSocket 请求路径重复前缀并返回 403 | noVNC 将 `path` 查询参数相对当前 `vnc.html` 目录解析，却传入了完整 `browser-control/remote/websockify` | 将 noVNC 参数改为相对 `path=websockify`，由浏览器解析到受保护的同源路由 | REQ-001/006/007 | `已修复并通过 Docker 复验` |
| DEF-006 | 容器重建后 Chrome 长时间停在启动中 | 持久 profile 的 `SingletonLock/SingletonCookie/SingletonSocket` 仍指向上一容器进程 | 启动共享 Chrome 前只清理三个进程级残留锁，并用测试保护 Local State | REQ-008/011 | `已修复并通过二次重建复验` |
| DEF-007 | Google 登录页显示“此浏览器或应用可能不安全”并进入 `signin/rejected` | 官方 Chrome 仍由 Playwright 以自动化控制参数启动，Google 将登录环境判定为不受支持；顶部 `--no-sandbox` 横幅不是直接拒绝原因 | 改为普通 Chrome 子进程常驻，Playwright 通过容器回环 CDP 短时连接；不伪造 User-Agent 或绕过验证 | REQ-013 | `已修复并通过本机 Docker 复验` |

## 九、回滚方案

| 变更或风险 | 触发条件 | 回滚步骤 | 数据与兼容影响 | 回滚后验证 | 状态 |
|---|---|---|---|---|---|
| RB-001 浏览器控制模块 | 新接口导致服务启动/会话清理异常或完整测试回归 | 移除新 service、路由、UI 和测试；恢复 `main.py` 生命周期增量；保留原签到修改 | 不涉及数据库迁移和 profile 格式，回滚无数据损失 | `/health`、现有管理页与 full pytest | `可用` |

## 十、已验证事实

| 事实编号 | 已验证事实 | 证据 | 对任务的影响 |
|---|---|---|---|
| FACT-001 | Compose 仅映射 `0.0.0.0:18980:8080` | `compose.yaml` | 不改端口即可满足 REQ-001 |
| FACT-002 | `persistent_headful` 使用每会话 Xvfb，结束时关闭 browser 与 display | `browser_session.py` | 服务必须在维护会话期间保持 context manager 活跃 |
| FACT-003 | 共享 profile 已由 `_PROFILE_LOCKS` 串行保护 | `persistent_chromium_session()` | 可复用该锁阻止自动签到并发 |
| FACT-004 | `/api/v1` 路由统一依赖 `require_login`，应用统一使用 LAN middleware | `api.py:255`、`main.py:101` | 新接口放入现有 router 即继承安全边界 |
| FACT-005 | Browser plugin 未在本会话暴露 | Skills 列表 | UI QA 使用 regular Playwright 并记录原因 |

## 十一、风险与阻塞

| 编号 | 类型 | 描述与证据 | 影响 | 缓解或所需动作 | 状态 |
|---|---|---|---|---|---|
| RISK-001 | 性能 | PNG 短轮询会占 CPU/带宽 | 页面打开期间有额外负载 | 仅前台活跃视图以 700ms 轮询，隐藏或离开立即取消请求，不持久化 | `已缓解` |
| RISK-002 | 并发 | 长时间维护会话会让自动签到等待共享锁 | 调度执行可能延后 | 提供显式停止和 15 分钟空闲超时；共享锁防止 profile 损坏 | `已缓解` |
| RISK-003 | 输入 | 页面截图不包含原生 Chrome 地址栏/下载 UI | 不满足用户目标 | 已升级为 DEF-001，替换实现 | `处理中` |
| RISK-004 | 依赖 | Selkies 主线依赖未发布的原生扩展，无法在普通 pip/Docker 构建中解析 | GitHub CI 和全新 Docker 安装失败 | 已改用 Debian trixie 中稳定的 noVNC 1.6、websockify 0.12、x11vnc 0.9.17 | `已解决` |
| RISK-005 | 生命周期 | 多次短时 CDP 操作可能把任务新建标签页留在常驻 Chrome | 签到结果串扰或人工页面累积 | 每次任务记录连接前页面集合，只关闭任务新建页面；Playwright 断开不关闭原有人工页面 | `已验证` |
| RISK-006 | 性能 | 1920x1080 比 1365x768 增加约 98% 像素和远程桌面编码带宽 | 弱设备或网络下操作延迟增加 | 保留较低分辨率选项；只在用户切换时重启；限制为四个已验证尺寸 | `已缓解` |
| RISK-007 | 兼容 | 两个 Chrome Profile 的 CDP 目标具有不同 `browserContextId`，但 Playwright 高层将页面合并到一个 context，且无法按非默认 ID 创建新目标 | 自动任务无法可靠地用 Playwright context 直接绑定 Profile 目录 | 本轮保证人工多 Sync 与完整数据持久化；自动任务沿用当前活动资料，后续若要账号绑定需设计显式 Profile 契约 | `已确认边界` |
| RISK-008 | 容器安全 | 当前 Docker `no-new-privileges` 下官方 Chrome 沙箱无法建立 namespace，普通 Chrome 仍需 `--no-sandbox` | Chrome 顶部显示安全提示，容器内浏览器沙箱弱化 | 保持容器非 root、LAN/登录边界和最小端口；不把 CDP 暴露到容器外；后续可单独评估容器 capability/seccomp | `已知并限制暴露` |

## 十二、质量门禁

### 12.1 准备门禁

| 检查项 | 结论 | 证据或条件 |
|---|---|---|
| 最新目标、范围、非范围和约束已记录 | 通过 | REQ-001/002/005 至 013，包含普通 Chrome、短时 CDP 和多个 Sync Profile |
| 验收标准可观察、可测试 | 通过 | REQ-013 有启动参数、Google identifier、webdriver、进程和 Profile 目录验收 |
| 必要架构和单元设计达到可实现程度 | 通过 | 普通 Chrome 子进程、任务租约、noVNC Unix socket、IF-005/006/008 |
| 每项需求已有任务、范围和测试思路 | 通过 | 追踪矩阵 |
| 工作区基线和用户已有改动已识别 | 通过 | 三个签到适配文件已记录并保留 |
| 高风险变更已有回滚思路 | 通过 | RB-001，无迁移无新端口 |
| 无改变实现方向的未解决冲突 | 通过 | 冲突记录为无 |

- 门禁结论：修正版通过
- 条件及关闭要求：无

### 12.2 完成门禁

| 检查项 | 结论 | 证据或条件 |
|---|---|---|
| 用户最新目标和有效需求逐项验收 | 通过 | REQ-001/002/005 至 015 均完成 |
| 端到端追踪闭合 | 通过 | TASK-001 至 019 全部完成或按用户指令取消验证 |
| 测试已执行或缺口影响已准确记录 | 通过 | 24 项定向、188 项全量与本机 Docker 登录/Profile 验证通过；ruff 缺口已记录 |
| 缺陷已关闭或成为用户接受的遗留风险 | 通过 | DEF-007 已修复；RISK-007 的自动任务 Profile 绑定边界已准确记录 |
| 决策、冲突、回滚、风险和阻塞状态已更新 | 通过 | 决策有效，风险已缓解，无阻塞 |
| 最终差异无范围漂移、无关回退和调试残留 | 通过 | `git diff --check` 通过，Compose 未改；保留既有签到修改 |
| 账本与工作区一致，下一步唯一动作明确 | 通过 | 功能提交已推送；账本待作为独立文档提交推送；下一步无 |

- 门禁结论：通过
- 条件及关闭要求：无；Actions、在线升级和发布后验证按用户指令不执行。

## 十三、检查点

| 时间 | 已完成 | 新发现或变化 | 影响 | 下一步唯一动作 |
|---|---|---|---|---|
| 2026-08-28 16:46 +08:00 | 完成基线调查、目标架构、接口、测试计划和准备门禁 | 用户明确禁止新增端口；现有 profile lock 可直接复用 | 采用同源 PNG + HTTP 输入代理 | 实现 BrowserControlService 及单元测试 |
| 2026-08-28 17:12 +08:00 | 完成 BrowserControlService、同源 API、应用清理、管理页主流程；focused tests 4 项与语法检查通过 | 画面只在控制页可见时轮询，隐藏页不续活；Compose 未修改 | 后端任务完成，前端进入验证 | 补静态契约测试并执行桌面、移动渲染与交互验证 |
| 2026-08-28 17:32 +08:00 | 完成真实 Chromium 操作、桌面/移动视觉 QA、停止竞态修复、移动图片缩放修复和完整回归 | 首次移动截图发现 img 缺 class，修复后实际缩放为 356px 并可见 | 全部需求闭合，完成门禁通过 | 无 |
| 2026-08-29 13:34 +08:00 | 完成官方 Chrome、首次环境初始化、amd64 发布、本机 Docker 二次重建和 noVNC 输入验收 | 跨容器 Singleton 残留锁会阻塞持久 profile，已定向清理并保护 Local State | 运行版与远端均为 `8cf8ca9`，Chrome 152 常驻，profile 哈希保持 | 无 |
| 2026-08-29 18:18 +08:00 | 重新打开任务并完成分辨率问题调查、接口和测试设计 | 全屏仅改变前端容器，Xvfb 与 Chrome 启动参数仍固定 1365x768 | 增加持久化分辨率选择和安全重启，不自动猜测客户端显示器 | 实现 TASK-013 |
| 2026-08-29 18:52 +08:00 | 完成四档分辨率、持久化、安全重启、前端切换和全量验证 | 渲染 QA 发现恢复中禁用选择器及漏引 browser shell，均已修复；Google 登录拒绝是独立自动化启动问题 | REQ-012 闭合；未发布、未部署 | 等待用户决定提交发布或独立改造 Google 登录 |
| 2026-08-29 20:46 +08:00 | 将目标修正为多个 Chrome Sync Profile；验证普通 Chrome + 短时 CDP 核心生命周期 | 普通 Chrome 可进入 Google identifier 页且 `webdriver=false`；Playwright stop 不关闭 Chrome；容器现有安全配置仍要求 `--no-sandbox` | 采用完整 User Data 根目录多 Profile，不固定单一资料；完成门禁重新打开 | 验证两个 Chrome Profile 的 CDP 可见性与持久化元数据 |
| 2026-08-29 21:02 +08:00 | 完成两个 Chrome Profile 的真实行为验证并清理临时进程/目录 | `Default`/`Profile 1` 跨重启保留；CDP 底层可区分，高层 Playwright 合并且非默认 Profile 不能直接创建 target | 人工多 Sync 可实现；本轮不承诺不可靠的自动任务 Profile 绑定 | 实现普通 Chrome 常驻与 Playwright 短时 CDP 租约 |
| 2026-08-29 21:22 +08:00 | 完成普通 Chrome 子进程、回环 CDP 短时租约和相关单元测试 | 服务启动不再启动 Playwright；已有任务 Playwright 直接附加并在任务结束断开；Chrome 命令不含 `--enable-automation`、`--remote-debugging-pipe` 或固定 Profile | TASK-016 完成；进入全量与本机 Docker 验证 | 运行全量测试和本机 Docker 隔离实例复验 |
| 2026-08-29 21:45 +08:00 | 完成全量回归、本机 Docker Google 登录、短时 Playwright、Chrome 自恢复和多 Profile 持久化验证；删除隔离测试容器 | 实际 Sync 登录进入 identifier 而非 rejected；Chrome PID 18 被结束后由服务拉起 PID 705；`Default`/`Profile 1` 仍在 | REQ-013、TASK-017、DEF-007 闭合；完成门禁通过 | 无 |
| 2026-08-29 22:08 +08:00 | 接管“发布”指令并完成发布前容器、入口进程和差异基线检查 | 不需要镜像重建；必须通过 Web 在线升级更新部署 checkout | 新增 REQ-014/TASK-018/TEST-017，发布门禁重新打开 | 复跑测试后提交推送 |
| 2026-08-29 22:14 +08:00 | 24 项定向和 188 项全量测试再次通过；用户将范围缩小为只发布 | 不再监控 Actions、不调用在线升级、不做发布后验证 | TEST-017 取消；TASK-018 只保留提交推送 | 提交并推送 `main` |
| 2026-08-29 22:22 +08:00 | 功能提交 `b473580` 推送成功；发布技能删除在线升级、部署与发布后验证并通过校验 | 技能自动触发仍保留，但“发布”现在只执行测试、提交和推送 | REQ-014/015 与 TASK-018/019 闭合 | 无 |

## 十四、完成摘要

- 交付结果：普通 Google Chrome 由服务直接常驻，noVNC 不依赖 Playwright；初始化和签到仅短时通过容器回环 CDP 附加；完整 User Data 根目录保留多个 Chrome Profile 与各自 Sync 数据。
- 需求验收：REQ-001/002/005 至 015 全部完成；镜像仍仅支持 linux/amd64，未增加端口。
- 测试结论：24 项定向、188 项全量、本机 Docker Google identifier、`webdriver=false`、Chrome 自恢复与两个 Profile 跨重启保持均通过；发布后验证按用户要求取消。
- 缺陷与风险：DEF-007 已修复；Playwright 高层无法可靠按 Chrome Profile 目录绑定自动任务，当前自动任务使用 CDP 默认活动资料，边界记录为 RISK-007。
- 回滚说明：RB-001。
- 发布结果：功能提交 `b473580` 已推送到 `origin/main`；未执行在线升级与发布后验证。
- 技能结果：`autosurf-push-deploy` 已改为仅测试、提交、推送，并通过官方快速校验。
- 完成门禁：通过。
- 下一步唯一动作：无。
