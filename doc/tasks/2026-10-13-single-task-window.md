# 任务：AutoSurf 自动签到窗口复用

- 任务标识：`2026-10-13-single-task-window`
- 状态：`进行中`
- 日期：`2026-10-13 +08:00`
- 用户最新指令：修复多个 Chrome 任务窗口累积。
- 启用方式：明确长任务条件，跨诊断、实现、验证及既有部署授权。

## 一、需求定义

| 需求 | 验收标准 | 状态 |
|---|---|---|
| REQ-001 | 跨站跳转和 CDP 重连后复用同一自动任务标签页 | 进行中 |
| REQ-002 | 雷池预热失败、取消后清理此次创建的页面；成功接管时关闭旧任务页 | 待开始 |
| REQ-003 | 保留手动页面、持久登录目录及雷池分离预热能力 | 待开始 |

范围为浏览器任务页生命周期；不更改 CloudHelper、登录凭据及站点签到动作。
基线：工作区干净，已发布 `e0c4686`；本机只有一个 AutoSurf Chrome 主实例，多个页面被遗留。

## 二、总体架构

现状：任务页依赖 `window.name`，跨站导航可能清空；预热超时只返回 None，没有关闭新页。
目标：用 CDP target ID 跟踪任务所有权；window.name 仅用于兼容发现；预热用新旧 target 差集限定清理范围。

| 接口 | 调用方/提供方 | 契约 | 关联 |
|---|---|---|---|
| IF-001 | 两类浏览器 provider / browser_session | 传入已拥有 target ID，返回该页或新任务页；不存在则回退 | REQ-001 |
| IF-002 | detached_safeline_warmup / HTTP DevTools | 无 WebSocket 连接地关闭本次新开的预热 target；成功页不关闭 | REQ-002 |

## 三、单元设计

| 单元 | 文件 | 设计与异常处理 |
|---|---|---|
| UNIT-001 | browser_session.py | 页面 target 查询和按 ID 查找；重连不依赖页面标题及 name；手动页不关闭 |
| UNIT-002 | browser_control.py | 两类 provider 保存任务 target；预热失败 finally 清理本次新增同站页面 |
| UNIT-003 | tests/test_browser_control.py | 跨域清空 name、重连、成功接管、失败取消清理、手动页面保护 |

## 四、执行任务

| 任务 | 状态 | 需求 | 完成条件 |
|---|---|---|---|
| TASK-001 实现 target 所有权与预热清理 | 已完成 | REQ-001/002/003 | 两类 provider 按 target ID 复用、预热 finally 清理 |
| TASK-002 回归与全量验证 | 已完成 | 全部 | 39 项聚焦、236 项全量及实际 Chrome 回归通过 |
| TASK-003 发布部署及运行验证 | 进行中 | 全部 | 在线版本匹配、复用实机页面 |

当前交接：代码验证完成；下一步唯一动作是提交推送并核对在线升级版本；恢复先读本账本和工作区 diff。

## 五、测试与验证

| 测试 | 命令/方法 | 需求 | 状态 |
|---|---|---|---|
| TEST-001 | `.venv\Scripts\python.exe -m pytest tests/test_browser_control.py -q` | 全部 | 最终代码 39 项通过 |
| TEST-002 | `.venv\Scripts\python.exe -m pytest -q`、`git diff --check` | 全部 | 最终代码 236 项通过、diff 检查通过；仅已有 SQLite 日期弃用提示 |
| TEST-003 | 本机 health、升级 revision 和任务页 target/window ID 验证 | REQ-001/003 | 待开始 |

TEST-004：`tmp/single-window-regression.py` 使用临时 profile 的无头 Chrome、两个本机域名和三次独立 CDP 重连；三次任务 target/window ID 完全相同，页面数始终 `[2, 2, 2]`，保留初始空白页；HTTP DevTools 关闭失败预热页后，同站手动消息页和所有已有页面仍保留。已通过；未访问 PT 站点或使用登录 Cookie。

## 六、端到端追踪

| 需求 | 单元 | 任务 | 测试 |
|---|---|---|---|
| REQ-001 | UNIT-001/002 | TASK-001/002/003 | TEST-001/002/003 |
| REQ-002 | UNIT-002/003 | TASK-001/002 | TEST-001/002 |
| REQ-003 | UNIT-001/002/003 | TASK-001/002/003 | TEST-001/002/003 |

## 七、决策与冲突

DEC-001：target ID 不受跨域 name 重置影响，在 provider 中跨 CDP 重连保存；不依标题判断页面所有权。
DEC-002：不关闭身份不明的既有标签页；只清理有所有权证明的目标。冲突：无。

## 八、缺陷与回滚

DEF-001：跨域 name 清空使任务窗重复创建；DEF-002：失败预热页遗留。代码已修复，单元和隔离 Chrome 验证通过。
回滚：恢复前一正式提交，按在线升级流程发布；无需数据库迁移，保留原 profile。

## 九、门禁与检查点

准备门禁：通过。需求、接口、验证计划齐全；无既有工作区改动。
完成门禁：有条件通过。代码、单元及隔离 Chrome 检查完成，部署结果待核对。
