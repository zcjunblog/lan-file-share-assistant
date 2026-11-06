# Windows/Linux 后端适配实施计划

> 按已有M3协议执行。用户已明确选择先做跨平台，当前会话继续实施；平台后端按独立文件分工，主Agent集成和复核。

日期：2026-11-06。基础提交61d0044。隔离分支feat/cross-platform；托管工作树工具未返回且Git未创建工作树，采用Git工作树回退。原项目主分支保留已验收版本。

## 目标、接口与边界

标准Skill继续Python3.9+、Segno1.6.6，协议1.0、文件和期限上限不变。保留macOS后端，Linux复用POSIX文件/0700/0600原语，新增物理接口发现和CLOCK_BOOTTIME。Windows使用CreateFileW拒绝重解析点、原生DACL私有工作区、GetTickCount64与原生后台进程选项，不以chmod位假装ACL。

新增windows_backend.py仅导出：validate_path(str)->str、safe_open(str)->fd、open_private(str)->fd、workspace(Path)->Path、check_private(Path)->None、runtime_available()->None、interfaces()->list[dict(interface,address)]、continuous_seconds()->float、detached_options()->dict；补充create_private、make_private_dir及replace_private。函数异常使用core.ShareError；模块在非Windows可导入，原生API惰性加载。

core负责延迟分派和公共流程；load与下载快照在Windows使用允许删除共享的内部只读句柄，避免原子状态替换/到期删除受打开句柄阻碍。source safe_open的句柄策略独立，拒绝写入/删除及重解析扩展。Windows路径拒绝UNC、设备名、ADS、遍历、尾随点/空格和通配符。

## 实施顺序

- [x] 先写Linux与公共分派的失败测试，再实现Linux接口/连续时钟、Windows分派、启动选项及内部读句柄适配。
- [x] 独立实现windows_backend.py及test_windows_backend.py。原生测试覆盖用户SID私有ACL、宽ACL拒绝、普通文件、重解析/联接拒绝、源只读及内部读允许替换。
- [x] 添加原生平台验收程序与GitHub Actions，只执行合成文件、私有工作区、跨进程probe、环回HTTP和真实到期/停止；原始状态和凭据不上传，只输出脱敏JSON摘要。
- [x] 在macOS跑回归，并运行原生Windows/Linux CI。四组成功；云端系统测试不代表用户局域网或Agent客户端实测，unknown/remote生产预检保持拒绝。
- [x] 检查原生文件/权限、替换、异常清理、跨调用探针、环回下载与到期终态；复核Windows句柄/ACL和Linux接口筛选。慢连接实际到期的既有证据在macOS，Windows/Linux完整生产worker与传输中截止仍待设备验收。
- [x] 更新Skill说明、设计、待办与证据；GitHub同步到主分支，不公开仓库、不提交市场。

## 验证准则

原生API/文件安全失败必须阻止，不降级为跟随符号链接或普通monotonic。Mac旧行为回归通过。云端原生CI只能证明其操作系统上的合成原语和环回流程；真实Windows/Linux局域网、具体客户端、系统睡眠及手机副本摘要独立待验收。用户暂不睡眠约束继续有效。

## 实施记录

- Linux元数据筛选、CLOCK_BOOTTIME、公共分派与原生私有文件适配已实现。Windows原生DACL、重解析拒绝、创建时显式当前SID所有权、源只读和后台进程已实现。
- 独立复核发现并修复可选control.json缺失误判、ShareError阻断失败清理；回归涵盖部分凭据、真实监听关闭和原子事务残留清理。
- 首轮/二轮原生CI的Linux双版本通过；Windows发现打开目标时os.replace失败和PowerShell5继承PowerShell7模块路径问题。原生FileRenameInfoEx私有同目录替换、子进程专属PSModulePath修复后，CI3 Windows文件/ACL测试通过，网卡查询尚未通过，CI4补充有界诊断。失败历史不覆盖。
- macOS生产CLI真实60秒到期、独立二维码回读、下载SHA-256、关闭与清理通过，见evidence/platforms/macos-regression.json。
- CI4确认活动物理网卡没有IPv4时的精确无匹配异常，修复后CI5 Windows3.12完整通过。CI5 Windows3.9仅独立Get-Acl工具模块加载失败，改为绝对WinPS5路径与.NET直接ACL读取；生产权限断言未放宽。
- 最终CI6源码e41754b、运行42192469347：Windows2022/Ubuntu24.04各Python3.9与3.12四组全部成功。macOS75项中61通过/14 Windows原生项跳过；3.9独立环境子集10通过/14跳过。独立复核未发现新增确认问题，脱敏摘要见evidence/platforms/native-ci.json。
