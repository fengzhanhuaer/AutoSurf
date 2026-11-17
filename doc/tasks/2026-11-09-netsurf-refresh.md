# CARPT 等站点资料刷新修复

- 任务标识：2026-11-09-netsurf-refresh
- 状态：已阻塞
- 用户最新指令：2026-11-13 提供“页面已锁定/空闲过久”截图并要求自主完成；在已授权使用 Chrome 保存密码的前提下检查并接入站内空闲解锁，不再停留于可行性答复。
- 启用方式：明确长任务条件；跨运行诊断、规则实现和浏览器验证。

## 一、需求定义
REQ-001：修复 CARPT 的账号刷新，验收为读取当前账号指标且刷新状态成功。REQ-002：识别其他失败站点并对有证据的相同问题修复。范围仅只读资料刷新，不提交签到、不绕过验证、不修改其他设置。
REQ-003：用户已确认 Chrome 自动填充 PigGo 凭据。资料刷新/既有签到任务遇到登录失效时，用原浏览器完成一次普通登录并继续原任务；缺失填充、未知表单、验证码或登录未确认均停止。账号密码不新增存储、消息传输或日志输出。REQ-001/002 的资料刷新仍不提交签到；REQ-003 普通登录为用户最新授权的增量范围。
REQ-004：适配截图中的 PigGo 空闲锁定。验收：精确识别 /locked 的 #idle-lock-title 和 form.step-up；使用 Chrome 填充的当前密码调用官方控件一次，验证真实解除锁定并刷新本人资料。没有自动填充时明确提示选择 Chrome 密码候选；本次允许通过正常浏览器界面选择已保存密码。系统身份验证和验证码交给用户，不提取密码库。

## 二、总体架构
background inspectSite -> 内容脚本 freshSnapshot -> 同源首页/本人详情 -> piggo.profile -> saveResult 独立 refreshState。已安装目录是本仓库扩展；正式 Chrome 无 CDP。使用临时扩展诊断页读取脱敏失败原因与页面结构，通过 UI Automation 读取结果，结束删除诊断页。
REQ-001/002 接口：兼容原有 inspect 消息及 profile/refreshState 数据结构；REQ-003 新增 IF-003 独立登录许可。
REQ-003 目标流程：freshPage -> 恢复登录 -> Chrome 填充后的可见同源登录表单 -> 持久化单次提交许可 -> 点击官方登录按钮 -> 当前页面出现本人资料才确认登录 -> 原 freshPage。登录许可与签到 operation 分开；失败提交记录跨任务/重载保留，直到真实已登录页面清除。默认仅 PigGo 启用，不扩大其他站点范围。

## 三、单元设计
UNIT-001：site-rules.js/piggo.js 的 CARPT 页面解析；基于实际 DOM 收窄本人资料区域。UNIT-002：如现场证实请求失败，调整 content.js 刷新读取策略，不放宽登录或安全校验。UNIT-003：对应 Node 和 Playwright 回归，模拟网络和页面结构，不访问真实签到。
UNIT-004：piggo.js 校验登录控件、路径、表单目标和人工验证；content.js 等待填充及许可后点击一次；background.js 管理独立 browserLoginAttempt 许可、截止时间、设置重查及登录核验。未知结构安全停止，不猜测凭据或发起额外认证接口请求。
UNIT-005：锁定页精确路径与 DOM 适配，复用 IF-003 许可；保留当前锁定页，不跳转登录页。官方 StepUp 是 Vue submit.prevent 处理的默认 GET 表单，提交时仅通知网站 input/change 与官方 submit 处理器，始终阻止原生 GET 回退，避免凭据进入 URL。未确认解锁继续保留单次保护。

## 四、执行任务
TASK-001/002 已完成；TASK-003 原七站整体成功验收仍有外部遗留，未在本次重复执行。TASK-004/005/006 已完成（正式锁定恢复成功；普通重新登录以本地浏览器测试为证据）。TASK-007 站内锁定结构调查：已完成；TASK-008 适配及验证：已完成。
最新 REQ-004 已完成；整体已阻塞仅保留 REQ-002 原外部站点遗留，不表示本次 PigGo 解锁未完成。当前请求下一步唯一动作：无。
基线：保留上一轮未提交的刷新修复；扩展 manifest 0.4.105。

## 五、测试与验证
TEST-001/002：已完成，详见 2026-11-09 最终检查点。TEST-003：三站成功、两站维护、两站超时，全部成功的实站验收仍受外部条件阻塞。
TEST-004：浏览器模拟延迟填充、普通登录导航/SPA、缺失凭据、验证码、错误密码、重复消息、刷新/重载和许可绑定；验证最多一次登录，刷新不签到，独立 signinState 保留。TEST-005：正式 Chrome 重载版本与 PigGo 可达性及登录结构核验，现场不可达时明确记为未通过实站验收。
TEST-006：按实站锁定结构测试隐藏只读账号、延迟填充与 Vue input 同步、官方解锁、无事件处理器禁止 GET、错误密码不重发、额外验证停止；TEST-007 正式 Chrome 原锁定标签页使用浏览器密码候选与正式 inspect 验收。

## 六、端到端追踪
REQ-001 -> UNIT-001/002 -> TASK-001/002/003 -> TEST-001/002/003。REQ-002 -> TASK-001/002/003 -> TEST-001/002/003；未确认站点不宣称修复。
REQ-003 -> UNIT-004 -> TASK-004/005/006 -> TEST-004/005 -> piggo.js/content.js/background.js/site-rules.js；源码与本地测试已完成，正式版本已确认 0.4.106，实站登录成功待验收。
REQ-004 -> UNIT-005 -> TASK-007/008 -> IF-003 增补 /locked -> TEST-006/007 -> piggo.js/content.js/background.js；已完成，0.4.107 正式 Chrome 解锁后资料刷新成功，时间 2026-11-13T02:01:02.401Z。

## 七、决策与冲突
DEC-001：只读诊断和刷新，保留当前登录和签到结果。无冲突。
DEC-002：REQ-003 用户新授权普通浏览器登录，补充 DEC-001 的只读范围，不授权处理验证码或重发签到。登录已提交但未确认时不自动重试，真实读取本人账号资料后解除保护。
IF-003：netsurf-browser-login 请求和 browser-login-permit 许可，只传 attemptId/截止时间/状态；sites.key('browserLoginAttempt',siteId) 保存 tabId、attemptId、phase、deadline、automatic 等非凭据元数据，不加入备份。异步许可必须在 content 点击之前持久化 submitted。默认其他站点禁用。接口已实现，许可绑定与并发回归通过。
DEC-003：实站已确认 /locked 为官方密码二次确认，不是新登录。使用官方 StepUp 控件及网站 SRP 实现，不调用认证接口、修改锁定状态或删除锁定记录。Chrome 密码候选不代表已填入，只有非空有效密码才申请单次许可。

## 八、缺陷
DEF-001/002/003/004/005：上一轮源码及回归完成，详见最终检查点。DEF-006：恢复登录时重复导航到已打开的登录页导致消息端口关闭；已按实际标签页 URL 判断并等待新页面完成，浏览器普通跳转及 query 场景通过。

## 九、回滚
恢复本轮相关源代码并重载扩展；不删除 storage 和 Cookie。诊断临时文件最终删除。

## 十、已验证事实
Chrome PID 9788 无远程调试；NetSurf 扩展 ID oglmadajmcmfcijokadkdboafkgfmanl，安装路径本仓库；已有 CarPT 本人详情标签和 NetSurf 标签。

## 十一、风险与阻塞
已明确七站。当前 PigGo 首页及 /login 均只出现“站点”空壳，15至30秒内没有输入框或账号栏；shell 无凭据请求另有5秒连接超时。这些是页面未加载证据，不等同于已确认账号掉线。本轮不能据此声称已用真实 Chrome 密码完成 PigGo 登录。

## 十二、质量门禁
准备门禁：有条件通过；仅诊断可执行，具体代码修改前需取得页面或报错证据。完成门禁：不通过，待验证。
REQ-003 准备门禁：通过；基于明确的自动填充前提实现严格表单检测，真实站点结构暂未知时停止并如实标注实站验收限制。准备门禁不要求提交未知表单。
REQ-004 准备门禁：通过；2026-11-13 当前正式 Chrome PID13068、PigGo /locked，真实 #idle-lock-title、form.step-up、只读用户名、当前密码及“解锁”按钮已确认；公开站点脚本确认官方 Vue submit.prevent/SRP 处理。源码和浏览器双重检查同源，不记录字段值。

## 十三、检查点
2026-11-09 Asia/Singapore：开始只读现场诊断，未提交签到，未改变配置。

## 十四、完成摘要
REQ-001/002 详见 2026-11-09 最终检查点；REQ-003 自动填充表单的单次登录恢复已实现。REQ-004 /locked 正式解锁及资料刷新已完成，详细证据见 2026-11-13 检查点。

2026-11-09 用户补充截图明确七站：CarPT、Free Farm、HXPT、PigGo、PTSBao、SunnyPT、XingYunGePT；REQ-002 范围更新为全部七站逐项验收。CARPT 现场首页请求 HTTP200 耗时6.6秒，本人详情资料可解析；旧刷新错误首页超时。Free Farm refreshState=error/ambiguous，已增加只读资料允许解析；CARPT 新鲜导航避免重复 fetch，修正魔力值 [使用] 解析。准备门禁通过。浏览器 CARPT 回归通过，Free Farm 测试捕获到初次注入的 observed 更新签到状态，需按真实前置状态验证资料刷新保持状态。

2026-11-09 16:33 Asia/Singapore 检查点：
- 正式 Chrome 0.4.105 已重载；CarPT refreshState=success（08:18:33Z），请求新首页后资料可读，原用户页保留。
- Free Farm 实际换为 N8 主题，n8-hero/n8-deck-grid 账号卡替代 info_block；个人中心仍为本人 userdetails.php?id。已实现限定账号卡的等级/指标与本人链接识别；不把 137.0万 截成 137.0。legacy/n8/CarPT 浏览器 3项通过。
- HXPT 当前首页 SSR 有 mhome-hero 账号统计，但旧规则仅识别 usermenu；已确认问题方向，正在取真实结构。
- PigGo 两次新页面导航均停在 pendingUrl=https://piggo.me/，30秒无可注入文档，不把历史 login_required 当成本次已确认原因。
- PTSBao 当前首页短维护提示；XingYunGePT 当前 document.title 和正文均为“停机维护中”，已增加准确维护识别及 pageUnavailable 阻止重复请求。
- SunnyPT 资料读取原串行请求 attendance/status，已增加 read(...,{dataOnly:true}) 只读契约；资料与签到接口分离，保持 signIn 原核验。TEST-002 Node相关129项通过。
- 全Node初次281/282；唯一失败是既有排序测试把2026-11-08当作今天，已给已完成样本补 confirmedDay:sites.day()，相关39项通过。未改产品排序逻辑。
- 自动审批两次拒绝在临时诊断页中显式带凭据的请求；未执行被拒绝请求。后续通过现有正式 inspect 流程和已打开页面 DOM 诊断继续，无扩大访问权限。
- UNIT-001 增加N8/HXPT账号卡解析，UNIT-002 增加 API dataOnly 及不可用页早停。IF-001：NetSurfProfileApi.read 第五可选参数 {dataOnly}，默认保持原读取签到状态；IF-002：netsurf-inspect 可选 pageUnavailable 布尔用于明确维护页面，默认无标志。
- DEF-001 CARPT 重复慢首页请求已修复且实站通过。DEF-002 Free Farm 签到歧义阻断资料及新主题未适配，源码/浏览器通过待最终重载实站。DEF-003 HXPT账号卡未覆盖，进行中。DEF-004 Sunny资料依赖签到状态，源码回归通过待实站。DEF-005 维护页被误报未识别或二次请求超时，源码回归通过待实站。
- TASK-001 调查已完成大部分；TASK-002 实现进行中；TASK-003 最终验证待开始。下一步唯一动作：读取当前 HXPT 任务的账号卡 DOM。


## 最终检查点（2026-11-09 16:39 Asia/Singapore）

### 需求与设计对账
- REQ-001：已完成。CARPT 重复慢首页改为专用新页面，识别魔力值 [使用]；正式 refreshState=success，最后记录 2026-11-09T08:33:48Z。
- REQ-002：源码修复与七站逐项诊断已完成，七站全部恢复成功尚受外部条件阻塞。Free Farm/HXPT 已实站成功；PTSBao/XingYunGePT 当前官方维护，准确显示维护而保留旧资料；PigGo/SunnyPT 仍网络超时，不能称为刷新成功。
- UNIT-001 最终规则：N8 本人账号卡的精确详情、等级和上传下载；缩略余额清空当前解析值以保留上次精确值，不能让通用正则截出137.0。HXPT 的 mhome-hero 定义列表按 dt/dd 读取本人统计，优先于观察期阈值说明；已打开的 desktop 用户菜单有结构化指标时仍优先。
- UNIT-002 最终流程：新页面有本人资料时允许只读复用，签到歧义不阻断资料；维护标志 pageUnavailable 阻止二次首页请求；API dataOnly 不依赖 attendance/status。
- IF-001/IF-002 与既有调用兼容；新规则 profileDefinitionSelector、profileStatValueSelector 都是可选配置，未配置站点保持原逻辑。

### 任务与端到端追踪
| 需求 | 单元/任务 | 实现 | 验证 | 结论 |
|---|---|---|---|---|
| REQ-001 | UNIT-001/002；TASK-001/002/003 | site-rules.js, background.js, content.js | TEST-001 CARPT正式成功；TEST-002慢fetch浏览器用例 | 已完成 |
| REQ-002 | UNIT-001/002/003；TASK-001/002/003 | piggo.js, site-rules.js, profile-api.js, content.js | TEST-001七站诊断；TEST-002 Node与浏览器回归；TEST-003正式逐站只读刷新 | 已阻塞：PigGo/SunnyPT外部连通性及两站维护 |

TASK-001 调查已完成；TASK-002 代码与回归已完成；TASK-003 可用站正式验收已完成，整体状态已阻塞于外部站点。

### 测试与验证
- node --test extensions/netsurf/tests/*.test.cjs：284/284，通过，日志位于本机 TEMP/netsurf-refresh-node-tests.log。
- pytest test_profile_refresh_browser.py + test_hxpt_home_browser.py：38/38，通过。
- 最后的缩略余额与维护页服务器页脚修正后，目标 Node content/piggo/profile-api 90/90，通过；test_profile_refresh_browser.py 4/4，再次通过。
- 新增浏览器测试覆盖慢首页重复fetch、新旧Free Farm主题、N8缩略余额不得截短、签到入口歧义、HXPT未完成交互初始化的SSR资料、无签到请求和旧用户页保留。
- 正式 Chrome 已重载0.4.105，contentRevision=2026-11-09-profile-refresh-v105-3。最后两站专项核验：XingYunGePT 08:37:16Z正确显示站点维护；Free Farm 08:37:27Z成功并读到精确魔力值/做种积分。
- HXPT 08:33:00Z刷新成功，魔力及上传下载/分享率来自本次账号卡；等级/做种积分若当前页不提供则按既有逻辑保留旧值，不声称每个字段都是新读取。
- PTSBao 08:33:56Z返回维护；PigGo 08:34:37Z页面加载超时；SunnyPT 08:33:35Z账号接口超时。额外无凭据 curl HEAD 到 SunnyPT API，连接5秒超时；这是本机shell证据，和Chrome结果分开记录，不据此断言所有网络均不可达。
- 初次新增N8断言误在Playwright主世界访问扩展隔离世界变量，已改为扩展隔离世界中读取；这是测试环境问题，最终4项通过。
- git diff --check 通过；所有 refresh-* 临时诊断文件和诊断标签已清理，正式Dashboard已打开/刷新。

### 缺陷与风险
- DEF-001/002/003/004/005 源码修复及对应回归均通过。
- 外部遗留：两站维护不属于插件可修复行为；PigGo/SunnyPT在本次只读复测仍无法完成网络请求。未清除登录、未更改用户开关、未重新提交签到、未绕过人机验证。
- 现有排序测试日期固定导致跨日失败已单独补 confirmedDay，无产品排序行为变更。
- 回滚：恢复本轮7个扩展源码/说明文件并重载；storage、Cookie与登录不作迁移或删除。

### 门禁与交接
- 准备门禁：通过。
- 源码与本地测试门禁：通过。
- 七站全部恢复成功的完成门禁：有条件通过；条件为外部维护与连接恢复，尚未关闭，整体不标已完成。
- 当前状态：已阻塞（外部条件）。
- 下一步唯一动作：外部站点恢复后，以现有正式只读 inspect 流程复测 PigGo、SunnyPT及两维护站；保留今天已成功刷新与签到记录，不自动补发签到。

## PigGo 自动登录可行性补充（2026-11-09）

- 用户补充：PigGo 会定时登出，询问可否自动利用浏览器登录。
- 已验证：当前 freshPage 遇到 login_required 立即返回；没有自动登录实现。正式 Chrome 主进程仍为 PID 9788；本次 shell 无凭据访问 https://piggo.me/login.php 连接5秒超时，未获取当前登录表单，不能声称已验证实站自动登录。
- 可行方案：仅利用浏览器已填好的登录表单，确认同源、表单目标、无人工验证后提交一次，成功后继续原任务；若需要选账号、解锁或验证码则交还用户处理。不能保证后台页可得到密码自动填充，不提取密码管理器数据库或导出凭据。
- 已向用户询问 Chrome 是否已保存且自动填入 PigGo 账号密码，尚未收到答案。本次仅完成可行性调查，未改自动登录行为、未提交登录。
- 原七站结论仍有效。本补充不是新的已实现需求；后续实现需要取得可验证的表单结构及自动填充行为。下一步唯一动作：根据用户回复确认自动填充条件，并在站点恢复后核对登录表单。

## 最终检查点（2026-11-13，PigGo 空闲解锁）

- 用户最新要求已完成：自主处理截图中的站内锁定。正式 Chrome PID13068、原 PigGo 标签页来源 https://piggo.me/locked；没有重启 Chrome、删除 Cookie、修改网站锁定状态或替换账号。
- UNIT-005 已实现：仅对 PigGo 的 /locked、#idle-lock-title、form.step-up、只读 username-a11y 账号和官方“解锁”按钮启用；等待有效密码后使用 IF-003 单次许可。显式通知官方 input/change 处理器以同步 Vue 状态，点击官方控件，由站点完成自身 SRP 验证；捕获 submit 仅 preventDefault，不阻断网站处理器，禁止默认 GET 泄露密码。
- 浏览器自动填充事实：截图的密码管理器候选不等于已填充。普通自动化鼠标/Invoke 选择后本次仍为空，随后通过正常 Chrome 前台键盘选择同一已保存账号并 Tab 确认，密码框非空；未读取、输出或存储密码值，没有操作系统验证或验证码。
- TEST-006：test_piggo_unlock.py 8/8，通过，包含延迟填充、官方解锁、错误密码不重发、无填充、验证码、跨源/未知结构、无处理器禁止原生GET和并发。test_browser_login.py 14/14，通过；相关 content/piggo Node 80/80，通过；目标 background 6/6，通过（许可、跨任务保护、未决签到不跳转、临时验证后恢复、锁定页不导航及一次许可、完成状态保持）。语法及 git diff --check 通过。
- TEST-007：正式 Chrome 已重载0.4.107。通过 dashboard.html 可信框架的现有 inspect 消息对原标签页核验，refreshState.status=success，时间2026-11-13T02:01:02.401Z（10:01:02 Asia/Singapore），结果status=refreshed、profileFound=true、browserLoginAttempt=null。随后独立检查当前页面 path=/、locked=false、profile=true、contentRevision=2026-11-13-piggo-unlock-v107。
- 没有提交签到；普通资料检查仍保留原签到保护。REQ-003 单次登录恢复代码与本地测试有效，本次实站验证的是 /locked 密码二次确认，不声称已现场验证退出账号后的完整新登录。
- 108项相关测试通过；此前11月10日整套Node286项仅作为历史证据，本次没有重复跑整套，不把历史结果标成当前全量验证。
- 边界：插件可以等待填充后自动解锁；Chrome 要求用户选择保存项、系统身份验证或验证码时，插件无法保证无人值守。本次桌面代理已通过普通浏览器交互完成选择，不代表插件能直接操作浏览器密码管理器。
- 回滚：撤回本次 /locked 专用分支并重载扩展；保留已有账号、Cookie、browserLoginAttempt 单次保护及此前刷新修复。
- 门禁：REQ-004 准备/源码/实站完成门禁均通过；TASK-007/008 已完成，当前请求无下一步。原REQ-002其他站点外部遗留仍保留，未在本轮复测。
- 临时 login-diagnostic 页面、脚本及标签在交付前清理；源码改动未提交或推送。
