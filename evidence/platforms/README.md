# Windows/Linux后端验收

日期：2026-11-06。仅使用项目生成的合成文件；没有分享真实资料、修改防火墙/VPN/路由、使电脑睡眠或提交市场。

## 最终结果

源码提交e41754b的[原生CI矩阵](https://github.com/zcjunblog/lan-file-share-assistant/actions/runs/42192469347)四组全部成功：Windows 2022与Ubuntu 24.04，各覆盖Python3.9/3.12。每组均完成运行依赖安装、后端测试、独立调用probe、环回下载/停止/真实短时到期及清理；不是仅通过导入或编译。

- Windows每组24项后端测试：22通过，2项仅POSIX检查跳过。
- Linux每组24项后端测试：10通过，14项Windows原生检查跳过。
- macOS完整本地回归75项：61通过，14项Windows原生检查跳过；独立Python3.9运行环境的后端子集10通过、14跳过。
- 独立代码复核覆盖Windows句柄/ACL/原子替换、精确无IPv4处理、脱敏诊断及异常清理，最终未发现新的确认问题。

摘要见[native-ci.json](native-ci.json)，包含真实运行版本、跳过数和各组件结果。无IPv4网卡被跳过不代表所有接口可用；本机预检仍须获得可信的物理RFC1918地址。Windows要求本机固定卷、持久ACL与扩展原子替换能力，其他卷或能力缺失会阻止。

## 证据范围

| 验收 | 内容 | 不能替代 |
| --- | --- | --- |
| 本机macOS生产回归 | 跨调用probe与健康检查、生产worker、独立二维码解码、下载摘要、真实60秒到期及资源清理 | 其他操作系统、其他Agent、真实整机睡眠 |
| 原生Linux/Windows CI | Python3.9/3.12上的安全文件、权限、计时、跨调用后台probe；512KiB环回HTTP、状态、控制、短时实际到期和清理组件 | 用户局域网、手机扫码、完整生产worker与Agent适配 |
| 策略/异常回归 | Linux元数据筛选、Windows路径策略/PowerShell合成对象、原生异常清理 | 同网设备可达或实际网络策略 |

GitHub Actions的宿主为云端。验收工具确认生产preflight/start对unknown和remote保持阻止；没有伪造桌面本机依据、放行云端网卡或添加生产TTL绕过。组件到期用1秒内部Deadline，不改变CLI的60至3600秒限制。

## 修订记录

1. 原生CI暴露Windows缺少可选control.json被误判为安全错误；仅缺失记录保留FileNotFoundError，ACL/重解析等错误继续阻止。
2. 复核发现ShareError可能绕过准备失败和worker清理；先加入失败回归，再修复异常处理及自有原子写入残留清理，真实监听关闭通过。
3. Windows打开目标文件时传统os.replace返回拒绝访问；使用原生FileRenameInfoEx POSIX原子替换，限定相同私有父目录。源和目标ACL均核验，失败不降级为先删后移。
4. Windows PowerShell5继承PowerShell7的模块路径导致自动加载失败；只在子进程环境指定系统内置模块路径，不改全局环境。
5. 活动物理网卡无IPv4时Get-NetIPAddress返回精确的无匹配异常；只跳过这一种正常缺省，其余查询或权限失败保持阻止。原生PowerShell合成策略测试覆盖筛选和错误分支。

失败CI记录保留在GitHub，不覆盖成成功。原始日志、状态、凭据、地址和二维码只保存在忽略目录；仓库仅保存脱敏白名单摘要。

## 后续设备验收

- Windows/Linux本机完整八项预检、生产worker、独立调用状态和手机扫码下载；记录OS、Agent和浏览器。
- 手机保存副本SHA-256、真实局域网大文件行为。
- 整机睡眠仍按用户要求暂缓；宿主完整退出、系统时钟实际变更也未验收。
- M4最终归档、独立安装、WorkBuddy平台解析与正式包烟测另行执行；当前没有提审或上线。

[macOS生产回归](macos-regression.json) · [脱敏CI摘要](native-ci.json) · [实施计划](../../memory-bank/cross-platform-plan.md) · [原生合成验收工具](../../tools/native_platform_acceptance.py)
