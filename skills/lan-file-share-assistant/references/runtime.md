# 运行与故障处理

## 当前适用范围

M3跨平台验收中的开发版，Python3.9+、Segno1.6.6。已实现三个原生后端：

| 系统 | 文件与私有目录 | 网卡与连续计时 |
| --- | --- | --- |
| macOS | POSIX逐层O_NOFOLLOW、目录0700/文件0600 | networksetup/ifconfig物理网卡、mach_continuous_time |
| Linux | POSIX逐层O_NOFOLLOW、目录0700/文件0600 | sysfs物理设备元数据与IPv4 ioctl、CLOCK_BOOTTIME |
| Windows | CreateFileW拒绝重解析点、仅当前用户SID的受保护DACL、原生原子替换 | PowerShell NetAdapter/NetTCPIP物理网卡、GetTickCount64 |

Windows要求支持持久ACL和FileRenameInfoEx POSIX替换语义的本机固定卷；拒绝UNC、网络卷、设备路径、备用数据流与重解析点。Linux缺少可信sysfs元数据或CLOCK_BOOTTIME时阻止启动。未实现的平台仍返回platform_unverified；不得用权限或计时降级绕过。

Windows 2022与Ubuntu 24.04各Python3.9/3.12四组原生CI通过。它只证明合成文件原语、跨调用后台探针与环回服务组件；云端runner仍被生产预检按远端或未知宿主拒绝。实际Windows/Linux生产worker、传输中截止、同网扫码、具体Agent和整机睡眠尚待设备验收，不能由CI替代。macOS的Codex与WorkBuddy开发版已完成本机链路，用户手机内容回读和停止后失效已有反馈。

无需模型API、互联网、外部二维码服务或管理员权限。仅准备依赖时可能联网，文件下载页面不引用外部资源。HTTP不加密；只在可信、可互通的局域网分享。

## 依赖与路径

选择现有可用解释器，或在用户授权的任务目录建立虚拟环境：

```sh
python3 -m venv <venv>
<venv>/bin/python -m pip install -r <skill>/requirements.txt
<venv>/bin/python <skill>/scripts/lan_share.py interfaces
```

Windows命令使用`<venv>\Scripts\python.exe`，创建虚拟环境可用`py -3 -m venv <venv>`；在PowerShell调用带空格的解释器路径时使用`& "<解释器路径>"`。后续CLI参数在各系统一致，解释器与文件路径应分别正确引用。

不要复用此项目开发环境的绝对路径，不自动安装全局依赖。解释器缺失时说明需要本地Python3.9+；Segno缺失时报告dependency_missing，使用同一解释器安装并重新预检。

工作目录必须新的、专用的、父目录已存在的物理绝对路径。运行程序会建立POSIX 0700或Windows仅当前用户ACL目录及标记文件；拒绝接管未标记已有目录。源文件必须显式授权且使用物理路径，不能放在运行状态目录内。输入含符号链接时不要自行解析并扩大授权；请明确实际文件范围后再执行。

## 检查及状态

八项预检是host_context、runtime、source_files、workspace、qr、interface、bind、lifecycle。它们全部通过才允许准备分享。预检can_publish永远为false；start内部重新检查，不接受外部报告作为通行证。

probe是最长60秒的无网络子进程。下一次独立工具调用需要看到新心跳并确认该探针自行响应停止，才算当前宿主的有限存活证据。已完成探针的验证凭证最多再用30秒；过时重新probe。不能拿本项目M1记录放行。

start会先核验文件和空间，再复制私有快照，复制后重做动态预检；固定文件清单不变才监听。快照准备目标限时120秒，大文件若超时减少本次规模后重试。TTL从准备完成后的服务启动阶段开始，不能因重试或页面刷新延长。

| 状态/原因 | 含义及下一步 |
| --- | --- |
| supported / can_start | 预检具备本机启动条件，尚未发布链接 |
| needs_action | 依赖、权限、选址或生命周期未通过；依据逐项remediation修复后重检 |
| unsupported / remote_host_only | 当前仅远端执行，请在拥有文件的本机运行 |
| host_unconfirmed | 确认真实执行位置，不能用IP替代依据 |
| platform_unverified | 此平台尚无完成验证的运行后端 |
| interface_ambiguous | interfaces查看候选，确认用途后选择；不猜VPN或修改网络 |
| source_invalid / source_changed | 检查文件是否为已授权普通文件、物理路径及准备期间变化 |
| port_in_use / bind_denied | 用端口0或另选非特权端口后复检；不停止其他程序 |
| lifecycle_unverified | 重新probe，在下一次独立工具调用中及时复检 |
| preparing | 不展示链接，status轮询；准备超时会失败并清理 |
| ready + can_publish | 进程心跳与本机授权健康检查通过；仍未证明手机可达 |
| stopping | 关闭连接和清理中，继续status查询实际结果 |
| stopped / expired | 已手动停止/到期；核对temporary_resources_removed |
| failed | 启动或清理失败，查看reason_code；不得继续展示链接 |
| state_unreadable | 状态JSON损坏，返回unverified_stale；保留私有目录，不展示旧链接或猜测进程归属 |
| local_setup_failed / insufficient_space | 准备资料写入失败，先撤销本次部分凭据，再报告空间或权限原因 |
| unverified_stale | 无法验证进程，不显示旧链接，不按PID/端口终止程序 |

## 接收方打不开时

先用status区分服务已停与网络未互通。若本机状态正常，请核对接收设备与分享设备的实际网络、访客Wi-Fi/AP隔离、分享设备防火墙与设备局域网访问权限。只解释已观察到的原因；程序不会关闭防火墙、端口映射或开启公网隧道。手机成功保存后才算跨设备下载，不能由HTTP200推断完整保存。

## 停止与遗留资料

stop通过私有本地控制凭据请求所属服务关闭，控制凭据不会放入URL、二维码或页面。停止/到期会撤销快照、PNG/SVG、原始路径清单及凭据；本地终态和检查报告留在私有目录以便核对。

正常可调度状态下，看门循环每0.1秒核对墙钟和原生连续时钟，以先到为准；目标2秒内停止监听及进行中传输。机器暂停、断电或内核阻塞不属于实时保证。强制杀进程或宿主清理后台进程可能留下私有目录，不能将旧会话恢复为ready。

当前不自动删除无法核验的遗留会话或杀进程。先确认原有进程已结束、端口已关闭，再由用户删除该专用share目录；无法确认时保留隔离状态，不能把残留目录当作运行中服务。重新分享使用新会话、新凭据。完整宿主异常/跨系统验证属于M3。


## M3验收发现

当前已验证用户参与的同网手机扫码内容回读、提前停止后的旧链接失效；手机系统/浏览器未提供，手机副本字节摘要仍未独立核验。WorkBuddy开发包安装与运行记录、故障和生命周期证据见项目evidence/m3（发布包内无需包含这些开发资料）。

WorkBuddy首轮60秒测试中，工具调用延迟使下载落在截止之后，服务按期关闭且资源清理。有效期包含Agent在ready之后的工具调用/思考/交付时间，默认10分钟通常比极短有效期留有更多交互时间。测试或交付超时不能假装成功，也不能替用户静默延长。

正常停止会清理快照和凭据；SIGKILL这类强制终止会让操作系统关闭监听，但可能保留POSIX 0700/0600或Windows用户专属ACL私有资源。M3实测这种状态不再展示链接。只有已独立确认该会话进程结束后才能清理其专用目录；绝不根据旧PID或端口猜测并杀进程。
