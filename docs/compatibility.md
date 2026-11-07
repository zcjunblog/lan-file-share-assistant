# 安装与兼容性

当前 GitHub 版本为 0.2.1。标准包与 WorkBuddy 包均包含完整运行源码，业务脚本、HTML 页面、参考和依赖清单逐字节一致。WorkBuddy 包扩展 SKILL.md 的展示元数据。版本来自 Skill 根目录 VERSION。

## 安装包

- [标准包](../releases/0.2.1/lan-file-share-assistant-0.2.1.zip)。
- [WorkBuddy 包](../releases/0.2.1/lan-file-share-assistant-workbuddy-0.2.1.zip)。
- 对照同目录SHA256SUMS核验下载摘要，再解压或导入。无需复制仓库开发测试、证据或示例状态。

标准包解压后只有一个lan-file-share-assistant顶层目录。保留SKILL.md、VERSION、requirements.txt、scripts、references、assets和agents完整相对位置；不要只复制入口文件。

## 标准客户端

按照客户端当前版本的Skills说明安装整个目录。常见接入位置如下；这是目录规则，不是这些宿主的网络运行验收。

| 客户端 | 项目范围目录 | 实际运行状态 |
| --- | --- | --- |
| Codex | `.agents/skills/lan-file-share-assistant/` | macOS执行工具已完成开发链路；最终包另做独立CLI验收 |
| Claude Code | `.claude/skills/lan-file-share-assistant/` | 入口格式适配；客户端实测待补 |
| Cursor | `.cursor/skills/lan-file-share-assistant/` | 入口格式适配；客户端实测待补 |
| 其他Agent | 客户端明确支持的Skills位置或自定义导入 | 逐宿主执行能力检测，不承诺通用后台服务 |

可使用系统复制或文件管理器操作，更新前保留现有版本。启动后由 Agent 读取 SKILL.md，执行 `start --chat`，再在下一次独立工具调用执行 `status`，核验后展示二维码。

目录规则参考：[Codex Skills](https://developers.openai.com/codex/skills/)、[Claude Code Skills](https://code.claude.com/docs/en/skills)、[Cursor Skills](https://cursor.com/docs/context/skills)。以具体客户端版本和策略为准。

## WorkBuddy

使用WorkBuddy包通过客户端自定义技能导入或开放平台添加技能。入口含name/display_name、双语介绍、版本、作者及等量双语示例，格式依据[官方Skill文档](https://open.workbuddy.cn/docs/skill)。

0.1.0 曾在 macOS WorkBuddy 5.9.3 中完成加载、扫码链接下载与停止验收，开放平台显示该版已公开发布。0.2.1 已通过平台解析并以免费更新提交审核。详见[提审回执](../evidence/release/workbuddy-0.2.1-submission.json)。

## 准备运行时

选定本机Python3.9+并在任务目录建立虚拟环境。macOS/Linux命令示例，`<skill>`替换为实际安装目录：

```sh
python3 -m venv .lan-share-venv
.lan-share-venv/bin/python -m pip install -r "<skill>/requirements.txt"
.lan-share-venv/bin/python "<skill>/scripts/lan_share.py" interfaces
```

Windows PowerShell示例使用解释器本身，不需要激活脚本或修改执行策略：

```powershell
py -3 -m venv .lan-share-venv
& ".\.lan-share-venv\Scripts\python.exe" -m pip install -r "<skill>\requirements.txt"
& ".\.lan-share-venv\Scripts\python.exe" "<skill>\scripts\lan_share.py" interfaces
```

选择Python3.9+实际版本；缺少解释器或依赖时先说明需求，不凭开发者绝对路径运行，不自动安装全局包。只有首次准备依赖可能联网，文件服务和二维码不依赖外部模型或二维码API。

## 系统要求与证据

| 系统 | 后端要求 | 支持状态 |
| --- | --- | --- |
| macOS | 可执行Python、物理RFC1918接口、POSIX私有权限与mach_continuous_time | 本机客户端开发链路已验收；候选包另做独立解压验收 |
| Windows | 本机固定卷、持久ACL、FileRenameInfoEx POSIX替换语义、可读NetAdapter/NetTCPIP与GetTickCount64 | 实验性；Windows2022原生CI通过，真实LAN/Agent待验收 |
| Linux | POSIX O_NOFOLLOW、可信sysfs物理设备元数据、IPv4 ioctl、CLOCK_BOOTTIME | 实验性；Ubuntu24.04原生CI通过，真实LAN/Agent待验收 |

Windows拒绝UNC、网络/可移动卷、设备路径、备用数据流及重解析点。Linux缺少物理设备元数据或可信连续时钟会阻止。多网卡应核对用途后明确选择；私有IP本身不能证明程序运行在用户电脑。

云端CI只执行合成组件，不能冒充桌面Agent或手机扫码。生产程序对unknown/remote宿主保持阻止。各系统都需要可写专用运行目录、足够磁盘余量及跨调用后台存活能力，完整命令见[运行参考](../skills/lan-file-share-assistant/references/runtime.md)。

## 出现问题

依次区分：宿主不明、解释器/依赖缺失、文件授权或路径错误、运行目录权限、接口选择、端口绑定、生命周期检测，以及接收方网络互通。按程序reason_code和remediation复检，不通过关闭安全功能或伪造本机证明绕过。已停止或到期的会话应新建，不能恢复旧凭据。
