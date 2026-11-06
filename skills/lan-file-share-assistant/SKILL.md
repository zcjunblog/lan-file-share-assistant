---
name: lan-file-share-assistant
description: 将用户指定的本机文件临时分享给同一局域网内的手机或电脑，先检测本地配置，再生成扫码下载页，支持自动过期与提前停止。适用于“把这些文件发到手机”“局域网分享”“扫码取文件”；首版运行后端仅验证macOS，不提供上传、公网传输或目录共享。
---

# 局域网文件分享助手

把明确选定的文件交付到另一台设备。使用随附确定性程序处理预检、文件快照和到期关闭；Agent负责确认范围、解释结果与展示已核验的链接。

## 确认本次任务

- 列出用户逐项指定的文件；“分享刚生成的文件”可依据本次产物清单确定范围。不要扫描桌面、工作区或默认分享整个目录。
- 默认10分钟，可选1至60分钟；1至20个普通文件，单个不超过2GiB、合计不超过5GiB。容量是设计上限，大文件性能尚未验收。
- 使用可信局域网，HTTP未加密；需要加密、公网、上传或目录时说明首版不支持，不能静默降级。
- 核实程序在拥有文件的电脑上执行。只有桌面执行适配器的实际证据或用户对执行位置的确认，才能选择本机参数；私有IP、操作系统名称和请求JSON不能自行证明本机身份。无法判断时以unknown预检，展示需要采取的步骤。

## 准备与运行

首次运行或遇到依赖、接口、停止问题时，阅读[运行与故障处理](references/runtime.md)。选择可运行Python3.9+和Segno1.6.6的解释器；不使用开发者的绝对路径，也不改全局环境。`<scripts>`表示本Skill的scripts目录，`<runtime>`是用户任务下一个新的专用目录，使用绝对物理路径。该目录保存凭据，权限0700；不能复用普通资料目录。

1. 用同一解释器执行：
   ```sh
   <python> <scripts>/lan_share.py probe --work-dir <runtime>
   ```
   此步骤没有文件服务。取得probe_id后，在**下一次独立执行工具调用**的60秒内继续；同一脚本里串联probe和start不能证明跨调用存活。
2. 根据确立的本机依据、文件授权与有效期执行：
   ```sh
   <python> <scripts>/lan_share.py start --work-dir <runtime> --probe-id <probe_id> --host-kind local --host-evidence desktop_adapter --file <file1> --file <file2> --title "项目交付资料" --ttl-seconds 600
   ```
   `desktop_adapter`仅用于真实桌面执行适配器；用户确认用`user_confirmed`。不确定时使用`--host-kind unknown --host-evidence none`，不得为通过检测伪造依据。只检测可将start替换为preflight；预检报告永远不是可展示分享链接的依据。
3. 若返回blocked，按八项检查中的reason_code、summary、remediation说明具体原因和复检方法；不生成假链接。多网卡时用`interfaces`读取候选，确定实际连接用途后`--bind-address`选择，无法确定则请用户选择。不要修改VPN、防火墙、路由或停止其他进程。
4. preparing表示快照尚在准备；用status轮询，不称分享成功。无论start是否返回ready，在**下一次独立工具调用**执行：
   ```sh
   <python> <scripts>/lan_share.py status --work-dir <runtime> --id <session_id>
   ```
   只有`state=ready`且`can_publish=true`才展示链接和qr_png/qr_svg。将二维码作为本地图片展示，并给出文件清单、截止时间、HTTP提示和停止方式。链接和二维码含访问凭据，仅交给本次用户，不上传公共图床、仓库或外部二维码网站。
5. 明确“本机启动自检通过；另一设备连通尚未验证”。用户手机完成下载后才记录实际跨设备结果；电脑上的二维码解码、本机访问不等于手机验收。
6. 用户要求提前停止时执行stop，等待stopped/expired并确认temporary_resources_removed。到期由后台程序强制执行，无需Agent定时提醒：
   ```sh
   <python> <scripts>/lan_share.py stop --work-dir <runtime> --id <session_id>
   ```

## 结果与边界

- 默认白蓝移动端页面，自带文件名、大小、下载入口与倒计时；页面刷新不会续期。
- 服务只读取私有快照，原文件只读。源文件在准备期间改变会阻止分享；ready之后原文件变化不会更新已固定的快照，重新分享应新建会话。
- 到期拒绝新请求、终止未完成传输、关闭监听并清理快照和二维码。已保存副本不能撤回；服务关闭后浏览器可能显示无法连接，不能承诺还能加载“已过期”页面。
- unverified_stale表示无法确认进程。不要展示旧链接、按PID或端口杀进程、恢复旧凭据。异常终止的遗留资源处理见运行参考。
- M2仅在macOS本机完成实际HTTP验证。Windows/Linux、WorkBuddy或其他Agent的后台存活、手机互通、真实睡眠恢复尚待验证；安装格式通用不代表所有客户端网络能力相同。
- 每次汇报说明已完成内容、当前状态、下一步及未验证项。
