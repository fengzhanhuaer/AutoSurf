# 任务：AutoSurf 自动签到窗口复用

- 任务标识：`2026-10-13-single-task-window`
- 状态：`已完成`
- 日期：`2026-10-13 +08:00`
- 用户最新指令：至少维持一个可见 Chrome 窗口；当前一个窗口都没有。
- 启用方式：明确长任务条件，跨诊断、实现、验证及既有部署授权。

## 一、需求定义

| 需求 | 验收标准 | 状态 |
|---|---|---|
| REQ-001 | 跨站跳转和 CDP 重连后复用同一自动任务标签页 | 已完成 |
| REQ-002 | 雷池预热失败、取消后清理此次创建的页面；成功接管时关闭旧任务页 | 已完成 |
| REQ-003 | 保留手动页面、持久登录目录及雷池分离预热能力 | 已完成 |
| REQ-004 | 常驻浏览器退出或无页面时自动恢复一个窗口；状态不得误报 active；失败清理保留最后一页 | 已完成 |

范围为浏览器任务页生命周期；不更改 CloudHelper、登录凭据及站点签到动作。
基线：工作区干净，已发布 `e0c4686`；本机只有一个 AutoSurf Chrome 主实例，多个页面被遗留。

## 二、总体架构

现状：任务页依赖 `window.name`，跨站导航可能清空；预热超时只返回 None，没有关闭新页。
目标：用 CDP target ID 跟踪任务所有权；window.name 仅用于兼容发现；预热用新旧 target 差集限定清理范围。

补充现场事实：Chrome 已退出，9222 不可达，但 browser-control 返回 active=true。接管已有 Chrome 时 browser_process=None，原生监督仅等待 stop_event，未监测退出。增加 HTTP DevTools 页面巡检，空页面恢复窗口，连续不可达交由既有 supervisor 重启，避免 WAF 预热时建立 WebSocket；清理前重新核查最后一页。

| 接口 | 调用方/提供方 | 契约 | 关联 |
|---|---|---|---|
| IF-001 | 两类浏览器 provider / browser_session | 传入已拥有 target ID，返回该页或新任务页；不存在则回退 | REQ-001 |
| IF-002 | detached_safeline_warmup / HTTP DevTools | 无 WebSocket 连接地关闭本次新开的预热 target；成功页不关闭 | REQ-002 |
| IF-003 | 原生 browser supervisor / HTTP DevTools | 无页面补建一个可见页面；连续失联重启；状态以实际页面可达为准 | REQ-004 |

## 三、单元设计

| 单元 | 文件 | 设计与异常处理 |
|---|---|---|
| UNIT-001 | browser_session.py | 页面 target 查询和按 ID 查找；重连不依赖页面标题及 name；手动页不关闭 |
| UNIT-002 | browser_control.py | 两类 provider 保存任务 target；预热失败 finally 清理本次新增同站页面 |
| UNIT-003 | tests/test_browser_control.py | 跨域清空 name、重连、成功接管、失败取消清理、手动页面保护 |
| UNIT-004 | browser_control.py、tests/test_browser_control.py | 接管与自启动 Chrome 均巡检，关闭全部页面自动恢复；失败清理保留最后一页；失联状态验证 |

## 四、执行任务

| 任务 | 状态 | 需求 | 完成条件 |
|---|---|---|---|
| TASK-001 实现 target 所有权与预热清理 | 已完成 | REQ-001/002/003 | 两类 provider 按 target ID 复用、预热 finally 清理 |
| TASK-002 回归与全量验证 | 已完成 | 全部 | 39 项聚焦、236 项全量及实际 Chrome 回归通过 |
| TASK-003 发布部署及运行验证 | 已完成 | 全部 | `6df0676` 在线升级完成、health=ok、HDCity 单次实机验证成功 |
| TASK-004 保持至少一个窗口 | 已完成 | REQ-004 | 巡检、恢复、状态与最后一页保护通过 46 项聚焦及 243 项全量回归 |
| TASK-005 发布与可见窗口验证 | 已完成 | REQ-004 | 在线升级完成；实机保留一个可见窗口；隔离 Chrome 验证最后页关闭与进程退出恢复、不累积页面 |

当前交接：`b8aacf39b92a1d623c6f12dcbe2c9e52940ed2f2` 已推送并在线部署，升级 complete、health=ok；现场一个可见 Chrome 窗口，恢复验证及回归通过。下一步唯一动作：无。

部署检查点：初始在线升级因 GitHub 连接超时失败，沿同一在线升级入口重试完成，complete 时间 `2026-10-13T09:27:05Z`；管理 API revision 等于上述提交、running=false。未改动网络配置或 CloudHelper。

## 五、测试与验证

| 测试 | 命令/方法 | 需求 | 状态 |
|---|---|---|---|
| TEST-001 | `.venv\Scripts\python.exe -m pytest tests/test_browser_control.py -q` | 全部 | 最终代码 39 项通过 |
| TEST-002 | `.venv\Scripts\python.exe -m pytest -q`、`git diff --check` | 全部 | 最终代码 236 项通过、diff 检查通过；仅已有 SQLite 日期弃用提示 |
| TEST-003 | 本机 health、升级 revision 和任务页 target/window ID 验证 | REQ-001/003 | 已通过，详见下述证据 |
| TEST-005 | 原生监督接管后失联、空页恢复、最后一页清理保护及 active 状态回归 | REQ-004 | 46 项聚焦通过；243 项全量通过，仅已有 SQLite 日期弃用提示 |
| TEST-006 | Win32 窗口句柄及 CDP 页数稳定观察；隔离 Chrome 最后页关闭及进程退出恢复 | REQ-004 | 已通过，具体证据及现场测试限制见下文 |

TEST-004：`tmp/single-window-regression.py` 使用临时 profile 的无头 Chrome、两个本机域名和三次独立 CDP 重连；三次任务 target/window ID 完全相同，页面数始终 `[2, 2, 2]`，保留初始空白页；HTTP DevTools 关闭失败预热页后，同站手动消息页和所有已有页面仍保留。已通过；未访问 PT 站点或使用登录 Cookie。

TEST-003 实机证据：在线版本 `6df0676`、升级状态 complete、health=ok。HDCity 执行 `4a74e5b5-b73f-47fa-aa12-4d3111e69891` 首次尝试 succeeded/already_done，个人信息刷新 success、HTTP 200、clicked=false。任务 target `A122EAC36F50B1C68F4FC62E07A50703` 从 Kufei 跳转到 HDCity，前后五个 target ID 集合相同，没有新窗。

TEST-006：`tmp/verify-browser-recovery.py` 使用独立临时 profile、随机 CDP 端口的无头普通 Chrome，在 Windows 上运行实际原生 supervisor；接管现有进程后关闭最后页，HTTP 自动恢复一个页面并保持不累积，再结束被接管进程，supervisor 成功重新启动，结果 empty_page_recovery=true、adopted_process_recovery=true、page_count=1、launches=2、restart_count=1。结束后隔离进程和 profile 均为 0。

现场验证：`tmp/verify-native-window.ps1 -Samples 5` 使用 Win32 EnumWindows/IsWindowVisible 与 Chrome 窗口类核查。仅关闭身份明确的额外空白页，保留自动任务结果页；连续五次采样均为 PID 7808、可见窗口 1、窗口句柄 6227918、CDP page 1、target `5BAE0E89AD6BEFF58166DC8B5BA2FE4E`。未关闭现场最后窗口：自动队列再次运行，busy 守卫阻止了两次尝试；最后窗口关闭及退出恢复采用隔离 Chrome 验证，避免中断任务。

现场清理：在无 running 执行时，仅关闭用户截图中既有 target 的空白页、重复 HDCity 结果页和旧 Kufei 错误页，逐项核对 ID 与原 URL。保留当前任务页和 HDDolby 消息页；最终两个页面。原 profile `C:\Tools\AutoSurf\browser\profiles\shared` 不变。

## 六、端到端追踪

| 需求 | 单元 | 任务 | 测试 |
|---|---|---|---|
| REQ-001 | UNIT-001/002 | TASK-001/002/003 | TEST-001/002/003/004，全部通过 |
| REQ-002 | UNIT-002/003 | TASK-001/002 | TEST-001/002/004，全部通过 |
| REQ-003 | UNIT-001/002/003 | TASK-001/002/003 | TEST-001/002/003/004，全部通过 |
| REQ-004 | UNIT-004、IF-003 | TASK-004/005 | TEST-005/006、全量回归，全部通过；现场关闭最后窗口未执行，替代验证见 TEST-006 |

## 七、决策与冲突

DEC-001：target ID 不受跨域 name 重置影响，在 provider 中跨 CDP 重连保存；不依标题判断页面所有权。
DEC-002：不关闭身份不明的既有标签页；只清理有所有权证明的目标。冲突：无。
DEC-003：针对本次用户截图进行一次性遗留页整理，以原始 target ID、精确 URL 和无活动执行为条件；不把历史页面清理策略加入通用运行逻辑，保留消息页及当前任务页。
DEC-004：原生常驻 Chrome 必须维持至少一个窗口，以 HTTP 页面巡检监测接管的无进程句柄实例；连续失联触发恢复，不持续连接 WebSocket。
CON-001：旧完成门禁未覆盖最后窗口退出；以用户最新要求重新打开任务，保留旧复用验证证据。
DEC-005：现场自动队列持续执行，保持 busy 守卫；以隔离普通 Chrome 的真实原生 supervisor 恢复验证，加现场 Win32 单窗口稳定采样完成验收，不强制中断自动签到。

## 八、缺陷与回滚

DEF-001：跨域 name 清空使任务窗重复创建；DEF-002：失败预热页遗留。代码已修复，单元和隔离 Chrome 验证通过。
DEF-003：接管 Chrome 后退出无法恢复，active 误报正常。已修复并部署，回归及隔离真实 Chrome 恢复验证通过。
回滚：恢复前一正式提交，按在线升级流程发布；无需数据库迁移，保留原 profile。

## 九、门禁与检查点

准备门禁：通过。REQ-004、接口及验证已补齐；工作区已有修改仅为本任务完成证据。
完成门禁：通过。REQ-004 的原生监督、状态及最后一页保护已部署；恢复通过单元与隔离 Chrome 验证，现场单窗口通过 Win32 与 CDP 核查；现场关闭最后窗口未执行原因及替代证据已明确。工作区后续修改仅为本账本完成证据。
