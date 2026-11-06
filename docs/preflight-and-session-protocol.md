# M1 预检与会话协议

日期：2026-11-06。协议版本1.0，供M2实现；M1仅提供隔离验证工具、结构约束和合成案例，没有文件分享服务。

## 1. 本阶段冻结的工程选择

| 项目 | 首版规则 |
| --- | --- |
| 运行时 | 服务核心目标Python3.9+；优先宿主已有可用环境。当前仅实测本机3.9.6与3.12.14的有限探针，不能据此声称所有版本通过 |
| 二维码 | Segno1.6.6，本地生成标准QR的PNG/SVG，无Pillow运行时依赖；缺失或实际生成失败为needs_action |
| 验证工具 | M1虚拟环境Python3.12，jsonschema4.26.0校验协议，zxing-cpp3.1.1与Pillow13.0.0独立解码；均是开发依赖，不进入Skill运行必需项 |
| 文件 | 1至20个显式授权普通文件，每个最多2GiB，总计最多5GiB；不递归目录、不自动打包 |
| 有效期 | 默认600秒，最少60秒、最多3600秒；默认值由后续CLI补齐并展示，协议中始终写明实际ttl_seconds |
| 端口 | 只绑定确认的本机RFC1918 IPv4地址；自动端口用0交给系统分配，显式端口限1024至65535；不抢占其他程序 |
| 传输 | 可信局域网HTTP，未加密；用户明确要求加密时返回不支持该方式，不悄悄降级 |
| 并发 | 首版每会话最多2个文件传输，超出返回可理解的繁忙反馈；按块传输，不整体载入内存 |
| 期限执行 | 截止由服务端独立执行，到期拒绝新请求并中断未完成传输，不自动续期 |
| 分享范围 | 只发布本次文件快照；会话信息、来源路径、预检报告和控制凭据不对接收端开放 |

这些是本轮工程决定，不代表用户逐一指定了参数。若M2实测需要调整，先记录原因和兼容性，不静默改变协议。

文件大小与总量属于设计上限，不是已经完成大文件吞吐或跨设备传输测试的证明；真实边界和性能由M2/M3单独验收。

## 2. 环境检查不是网络保证

不通过外部IP查询服务、远端二维码接口或DNS探测来判断本地能力。OS名称、文件路径形状、网卡名称、环境变量或容器标记都不能单独证明“这就是用户文件所在电脑”。

host_context必须有可解释的来源：用户已明确确认的本机上下文，或宿主提供的本地执行/文件位置能力说明。仅能看到远端服务器或容器地址且没有本机网络桥接证据时，返回unsupported；无法确认归属时返回needs_action。存在SSH、VPN或容器标记不自动等于不支持，需结合实际执行位置解释。

逐项检查固定为以下8项，均属关键项：

| id | 检查内容 | 不能冒充通过的情况 |
| --- | --- | --- |
| host_context | 文件主机及执行位置关系已有依据 | 只看到Darwin/Linux或一个私有IP |
| runtime | 受支持解释器与执行能力实际可用 | PATH里仅有命令名、未执行 |
| source_files | 显式文件白名单、普通文件、大小、权限及身份可核对 | 随意扫描目录、只做exists检查 |
| workspace | 独立状态与快照目录可写，资源预算足够 | 只知道上级目录存在 |
| qr | 本地标准QR可实际生成，缺依赖有准确反馈 | 仅发现模块名、只有文本链接 |
| interface | 有明确选定并确认归属的本机RFC1918地址 | 回环、链路本地、公网、全部网卡或多候选未选定 |
| bind | 能在选定地址绑定端口；释放预检套接字 | 本机绑定通过就宣称手机可达 |
| lifecycle | 当前宿主允许受控服务存活、观察状态并自行到期/响应停止，且有符合期限要求的连续计时来源 | 只凭可调用Popen就保证长时间运行，或把不含休眠的计时当作完整有效期 |

预检套接字只bind、不listen；正式启动必须重新原子绑定。bind阶段通过不预留端口，不消除检查后被占用的竞态。

防火墙、AP隔离、路由策略和手机局域网权限单列为局限，不伪称已检测全部网络配置。preflight.receiver_status固定为not_tested，正式服务启动及接收端可达属于后续阶段。

## 3. 分享请求

结构见[request.schema.json](../schemas/request.schema.json)。合成案例见[cases.json](../examples/m1/cases.json)。

| 字段 | 含义 |
| --- | --- |
| schema_version | 固定1.0 |
| title | 分享标题，1至120字符，仅作为文本，不解释HTML |
| file_paths | 1至20个明确授权的绝对物理文件路径；不接受URL、目录、通配符或递归范围 |
| ttl_seconds | 60至3600的整数，不能是布尔值 |
| bind_address | 已选地址或null；null由实际发现流程解析，未确定前不创建 |
| port | 0自动分配，或1024至65535整数 |
| host_context | local / remote / unknown及其依据来源；local不能使用none作为证据 |
| transport | 固定http，产品层明确其未加密 |

schema校验通过不表示地址属于本机或路径可读；这两个事实只能在实际主机预检中确认。RFC1918按10/8、172.16/12、192.168/16显式判断，不能直接把IPv4Address.is_private当作唯一规则。

请求是配置数据，不自行产生文件或网络授权；file_paths必须与当次用户明确授权的范围一致，host_context声明必须与实际宿主证据一致。不能因为文件内写了某路径或把kind写成local，就额外分享文件或跳过主机关系核对。

未确定地址时，单个可信物理接口候选可在展示理由后使用；多候选或仅VPN/桥接/容器接口时返回needs_action，让用户选择和确认，不修改系统网络。

## 4. 预检报告

结构见[preflight.schema.json](../schemas/preflight.schema.json)。报告只在本机保存，不进入可下载页面或仓库；仓库中的实例都是合成数据。

字段包括schema_version、preflight_id、request_digest、checked_at、valid_until、result、can_start、can_publish、checks、receiver_status、limitations。

- checked_at与valid_until为UTC时间，预检有效窗口30秒；过时、时钟倒退或请求摘要变化后重新预检。
- request_digest为最终执行请求的SHA256：采用UTF-8编码、ensure_ascii=false、sort_keys=true、separators=(',',':')及allow_nan=false序列化，不能用它替代实际文件重查。路径应先按实际授权规范化，不能在计算摘要后悄悄修改。
- can_publish在预检报告中固定为false；只有正式进程启动、文件快照和健康检查成功后才能发布二维码。
- checks必须恰好包含8个关键id，各出现一次；不能删除失败项以获得supported。
- 每项status为pass/fail/unknown，附reason_code、summary、evidence和remediation。非pass必须提供处理步骤，不能只写“失败”。

预检放行仅用于及时进入preparing。快照准备超过报告时间窗时，正式绑定/发布前重新核对动态关键条件并更新报告；已完成且核验一致的私有快照不必因报告刷新重复复制。若此时原路径身份或内容状态已变化，按source_changed处理，不静默改变本次分享内容。

预检报告不是外部提交的通行证。M2启动入口必须在受控流程中执行实际检查，不能直接读取用户提供的supported JSON就开放文件；结构校验不能证明检查真的发生过。

汇总结论按固定优先级计算，不由调用方任意填入：

1. 有明确不可支持的根因remote_host_only、execution_forbidden或lifecycle_unavailable，且对应检查确实fail：unsupported。
2. 其他任一fail/unknown、缺关键检查或没有可靠依据：needs_action，can_start=false。
3. 全部8项有依据地pass：supported，can_start=true；仍不代表已经启动或手机可连接。

关键项的pass不能使用not_tested依据。fixture只出现在开发合成案例，生产报告不接受此依据。

常用reason_code包括ok、host_unconfirmed、remote_host_only、execution_forbidden、runtime_missing、dependency_missing、qr_generation_failed、source_invalid、source_changed、workspace_unwritable、insufficient_space、interface_ambiguous、address_invalid、bind_denied、port_in_use、lifecycle_unavailable、lifecycle_unverified、clock_backend_unverified。

面向用户的失败反馈必须说明：当前结论、哪项未满足、实际观察、影响、处理步骤和复检方式。不要让用户猜测是否应该禁用防火墙。

反馈示例：

- needs_action：“当前Python可执行，但缺少本地二维码库，暂未创建分享。可以在任务虚拟环境准备Segno，再重新检测；不会修改全局Python。”
- unsupported：“当前只能在远端执行，无法确认或使用文件所在电脑的局域网，所以不能创建本机扫码下载。请改用该电脑的本地执行宿主后复检。”
- supported：“本机关键预检已通过，可以继续准备分享。服务尚未启动，手机连通性未验证；启动自检成功后才会展示下载二维码。”

## 5. 文件白名单与快照

1. 读取前固定物理路径白名单；拒绝目录、设备文件、FIFO和最终文件为符号链接的输入。父路径含符号链接时需明确解析后的物理文件范围，不能静默扩权。同一物理文件通过大小写别名、硬链接或其他路径重复指定时拒绝并提示，不按不同文件计数。
2. 通过打开文件描述符核验普通文件与大小，记录文件身份及纳秒级mtime/ctime；可用时采用O_NOFOLLOW。无法可靠核验的宿主不能伪称已防止替换。
3. 复制为本次会话私有快照，复制前后核对源身份/大小/时间及复制字节数，计算快照SHA256。变化则拒绝或重新登记，不边服务边追踪原路径。
4. POSIX目录权限0700、快照与状态文件0600；Windows需后续验证私有目录及文件身份语义，不把POSIX探针当作Windows证明。
5. 下载只映射随机file_id到已完成快照；浏览器提交的名字或路径不参与本机文件定位。
6. 快照预算为总文件字节数加max(64MiB,总大小的10%)预留；M2仍须处理复制过程中磁盘空间变化。失败不得回退直接共享原目录。

快照可隔离后续原文件变化；对能恶意同时写入并恢复元数据的同权限进程，不承诺得到事务级一致快照。真实生产实现及攻击回归留在M2/M3。

## 6. 会话、链接与控制

会话状态依次为preparing → ready → stopping → expired/stopped；启动错误为failed。旧状态文件无法核实进程时显示unverified_stale，不声称服务仍可用。

- session_id与file_id使用不透明随机标识；访问凭据至少256位随机数，控制凭据另行生成，不能互相复用。
- 公开路由限/s/<access_token>/和/s/<access_token>/files/<file_id>及必要静态资源；未授权内容不能通过猜测路径获得。
- 用常量时间比较校验访问凭据，页面与下载禁止缓存及跨站引用；文件名经HTML转义、Content-Disposition处理，响应为attachment并设置nosniff。
- 控制凭据不进二维码、链接、网页或访问日志。停止优先通过私有会话目录内、带控制凭据的停止请求交给服务自停，不按端口杀进程，不只用PID判断归属。
- M2需验证私有目录权限、控制请求归属、退出回执及监听关闭；M1无网络子进程仅证明一段有限时间的存活，不等于正式控制协议已经实现。
- 页面倒计时只是显示。关闭监听后浏览器可能显示连接失败，不能承诺过期地址仍能打开漂亮的失效页面；已经加载的页面可提示到期。

私有状态文件的固定字段为schema_version、session_id、request_digest、state、created_at、ready_at、expires_at、bind_address、port、owner_instance、files、last_error。files逐项包含file_id、download_name、size_bytes、sha256、snapshot_relative_path；原始路径和源身份另存为内部source_manifest，不随下载清单输出。owner_instance为本次服务随机身份，PID仅作诊断，不能作为停止授权。

访问与控制凭据单独保存在0600的私有secrets文件，不进入预检报告或一般状态输出。停止请求包含schema_version、session_id、owner_instance、control_token、requested_at；服务校验后转入stopping，关闭传输与监听并写最终状态。具体私有文件写入须原子替换，错误不能让状态先写ready而服务尚未启动。

ready_at/expires_at以实际进入ready的时间为准。单调时钟起点只在同一服务进程内使用，不能把保存下来的单调时刻当作重启后的授权依据；服务崩溃后不恢复旧会话，重新分享必须新建会话与凭据。

## 7. 自动过期与时间边界

有效期从快照准备完成、服务即将进入ready时起算；超时或启动失败清理，不把文件复制耗时默默算入用户可用时间。

服务记录wall_started、wall_deadline、mono_started、mono_deadline；mono指经过核对、包含系统休眠的连续单调计时来源，而不是在所有平台上直接假定time.monotonic都满足要求。只要墙钟达到wall_deadline，或该连续时钟达到mono_deadline，就视为到期，取先发生者。不能因时钟回拨、页面刷新或重试延长。

计时后端：macOS评估mach_continuous_time配合mach_timebase_info；Linux评估CLOCK_BOOTTIME；Windows评估原生GetTickCount64，不能直接借用名称相近但语义不同的.NET计时器。M1只在macOS核对原生API存在与正向推进，休眠包含性依据厂商文档，尚未实际休眠；其他后端仅为待验收方案。找不到可信后端或不能核对时，lifecycle返回unknown/clock_backend_unverified，不降级成“保证睡眠后准时过期”。

看门循环目标检查间隔不超过0.25秒；下载分块不超过1MiB，套接字发送/读取等待设超时。截止后拒绝新请求并关闭进行中传输；M2验收目标为正常可调度状态下2秒内完成监听关闭，不能对系统暂停、内核阻塞或机器失去供电作实时保证。

睡眠恢复后，在健康响应、授权及继续发送前检查截止时间；若系统睡眠和时钟同时异常变化、计时来源不足以证明有效期，采取失效关闭，不假装仍在原有时间窗内。连续计时起点只在同一服务进程使用，服务重启不恢复旧会话授权。

M1对时钟变化只做合成时间判定案例；实际服务端强制中断、系统睡眠与停止监听属于M2/M3验收，尚未完成。

## 8. 实际验证边界

| 证据 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| 本机接口发现与bind后关闭 | 当前调用可枚举候选并绑定某地址/端口 | 防火墙放行、AP互通、文件服务已启动 |
| 标准QR生成与独立解码 | 合成内容编码可回读 | 手机已扫码、链接可连接 |
| 两次工具调用间的有限子进程探针 | 当前Codex执行工具的有限后台存活与自行结束 | 整段聊天结束后或另一客户端60分钟运行保证 |
| 合成失败报告与请求案例 | 协议结构和状态约束可检查 | 云端、Windows/Linux或WorkBuddy实际故障已复现 |

M1的宿主关系与长期生命周期仍需要实际分享时重新核对。M2不能直接拿M1摘要文件作为放行凭证。

## 9. 复现与资料

```sh
python3.12 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-m1.txt
.venv/bin/python tools/probe_m1_environment.py --out outputs/m1/local
.venv/bin/python -m unittest discover -s tests -v
```

探针输出的本机地址、路径和进程详情仅在outputs中，默认不打印。使用tools/summarize_m1.py生成白名单字段摘要后才可纳入evidence/m1。以上命令不启动文件服务。

依据：[Segno文档](https://segno.readthedocs.io/en/latest/)、[Segno包元数据](https://pypi.org/project/segno/)、[Python socket](https://docs.python.org/3/library/socket.html)、[Python time](https://docs.python.org/3/library/time.html)、[Python os](https://docs.python.org/3/library/os.html)、[Apple连续时钟](https://developer.apple.com/documentation/kernel/1646199-mach_continuous_time)、[Windows含休眠计时](https://learn.microsoft.com/en-us/windows/win32/sysinfo/interrupt-time)、[jsonschema文档](https://python-jsonschema.readthedocs.io/)。2026-11-06核对；运行时接口以所选解释器版本为准。

## 10. M2实现补充（2026-11-06）

协议1.0字段不变。实际源码位于skills/lan-file-share-assistant，独立于tools/m1_contract.py。M2工程范围进一步明确如下：

- 当前只实现并放行macOS网卡、POSIX文件/私有目录和mach_continuous_time后端；Windows/Linux返回platform_unverified，不能使用推测的ACL或普通单调时钟绕过。原跨平台方案保留为后续待验收目标。
- CLI的逐项--file是调用方具体授予的文件范围，--host-kind/--host-evidence必须来自独立的本机依据。生产CLI不接受自带授权的请求JSON。内部API也需要单独传入authorized_paths和host_attestation。
- probe创建最长60秒、无网络的受控子进程；下一次独立工具调用需看到新心跳并验证受控停止，验证凭证最多有效30秒。启动进程必须在预检后30秒内接管任务，不能恢复旧会话。
- 准备目标限时120秒；复制后的动态预检重新检查来源身份、当前地址、端口、依赖及空间。空间余量扣除已创建的本会话快照，避免重复预留同一份数据；文件内容/路径身份不一致立即失败。TTL不包含前面的复制阶段。
- 首版运行目录使用显式新目录、0700及项目标记，私有文件0600；不接管已有普通目录。文件逐层使用dir_fd和O_NOFOLLOW打开，拒绝父级及最终符号链接、物理硬链接重复、管道、设备和越界参数。
- 实际看门周期0.1秒，连接I/O超时0.75秒，最多8个请求处理线程及2个下载传输。到期先撤销访问，主动关闭已接收连接，再停止监听与清理，不依赖正在发送数据的线程自行苏醒。
- HTTP路由只包括精确会话页、files/<file_id>与受访问凭据保护的health。health用随机挑战及会话归属回读核验，初次启动还逐项HEAD验证快照访问，之后status/stop的归属检查不争用文件传输配额，避免忙时无法停止。
- 前端使用无外部资源的白蓝模板，名称HTML转义，脚本CSP摘要授权。Host必须是选定IP及实际端口，跨来源Origin拒绝；不提供CORS、目录路由或控制HTTP端点。
- 停止控制仅为私有本地原子文件，校验会话、owner_instance、独立控制令牌和30秒请求时效。准备阶段也可响应停止；不按PID或端口杀进程。
- 新增细分原因包括scope_unconfirmed、request_invalid、platform_unverified、preflight_expired、preflight_failed、preparation_timeout、health_unverified、owner_unverified、heartbeat_stale、cleanup_incomplete。异常只记录类型或错误码，不记录可能含路径/凭据的异常原文。
- 状态写入失败时仍尝试关闭所属服务及清理；如果宿主强制终止或系统异常留下状态目录，返回无法核验，不恢复旧凭据。M2不自动清理无法验证归属的遗留会话。

M2的本机实际链路、60秒过期、进行中传输和手动停止证据见[evidence/m2](../evidence/m2/README.md)。真实手机、系统睡眠/时钟变更与目标客户端结果仍单列M3。
