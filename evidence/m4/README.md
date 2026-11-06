# 0.1.0 发布候选验收

日期：2026-11-06（Asia/Shanghai）。本轮只准备本地发布候选并同步私有GitHub；未上传WorkBuddy解析、未覆盖安装最终包、未提交审核、未上线，未决定公开范围、许可证或价格。

## 包与源码

单一版本源：Skill根目录VERSION=0.1.0。标准包保留标准name/description入口，WorkBuddy包添加官方展示字段及三组等量、非空的双语示例。其余文件逐字节一致。ZIP固定条目时间、Unix普通文件权限及压缩设置，重复构建归档摘要一致。

[归档与逐文件摘要](../../releases/0.1.0/manifest.json) · [SHA256SUMS](../../releases/0.1.0/SHA256SUMS)

构建与测试使用显式资源白名单；拒绝意外文件、符号链接、越界/丢失引用、失效图标路径，以及双语示例类型/数量错误或平台元数据覆盖标准名称/版本。包内不包含测试、原始资料、状态、访问凭据、开发环境或字体文件。

## 独立解压运行

全新macOS系统Python3.9.6虚拟环境只安装Skill运行依赖。pip freeze为segno1.6.6、importlib_metadata8.7.1和zipp3.23.1；后两项为Python3.9条件依赖。Pillow与zxing-cpp只在外部开发解释器用于独立二维码解码，未安装进该运行环境或分发包。

两个包分别解压到含中文和空格的隔离目录。逐项核验ZIP摘要、条目、普通文件类型、源码字节及完整资源引用；CLI从各自解压目录调用，不导入仓库业务模块。prepare、start、verify分为独立执行工具调用，不能用同一调用串联冒充跨调用存活。

- 两包八项实际预检与独立状态/健康检查通过。
- PNG二维码由外部解码器回读，与实际分享链接一致。
- 各下载8,400字节合成资料，原文件/私有快照/HTTP内容SHA-256一致；原文件未修改。
- 标准包提前停止，WorkBuddy包真实60秒自然到期；关闭监听、凭据/二维码/快照清理通过。
- 验收后停止所属会话并核对终态，再清理本工具拥有的隔离目录；没有按端口/PID杀进程。

准确字节数、每个包的摘要和结果以[archive-smoke.json](archive-smoke.json)为准。首轮验收脚本在停止成功、reason_code为空时错误拼接消息，修复前已复现、补回归后重跑；首轮会话已安全停止并清理。该问题属于验收脚本，业务源码未变动。

独立复核进一步收紧构建和验收工具：输出文件拒绝符号链接/非普通文件并使用临时文件原子替换；资源登记为明确15项，未登记PNG等不能入包；Markdown/图标引用必须实际入包；验收要求两个唯一profile，并校验proof中的路径、解释器、标识和监听地址归属于本次物理目录。相关问题先用临时哨兵、模拟probe和副本复现，再补回归修复。最终包业务文件与修复前相同，归档摘要未变。

## 视觉与说明

白蓝办公家族。Logo为文件交接与扫描四角组合，含512×512 PNG与可编辑SVG；封面1600×720，流程图1600×440，均有可编辑源。封面明确为界面示意，不含有效二维码、地址或真实文件。实际Chrome渲染及人工查看通过；标题9个中文字符使用PingFang SC，无横向/文本溢出或JavaScript错误。系统字体未分发。

正式README包含完整七步流程、示例、双包入口、依赖、接入、故障处理与验证矩阵。Windows/Linux统一写为实验性支持：原生CI通过，实际生产worker/局域网/Agent仍待设备验收。整机睡眠继续依用户要求暂缓。

## 最终回归与CI

本地87项回归：73通过、14项Windows原生检查跳过。新增12项分发测试纳入Windows2022/Ubuntu24.04各Python3.9/3.12的原生CI，四组全部成功；后端单测、独立调用probe和原生合成组件也保持通过。见[native-ci.json](native-ci.json)和[CI运行](https://github.com/zcjunblog/lan-file-share-assistant/actions/runs/42203566963)。

首轮新增分发CI在Windows的解压源字节比较环节失败。独立Git autocrlf检出复现14项文本资源差异，增加仓库LF规范并明确PNG/ZIP为二进制后，新检出全部15项与最终标准包逐字节一致，四组CI通过。未改运行时逻辑、未更改交付归档摘要；见[检出复现](checkout-normalization.json)。本地既有检出若自行改了源文件或换行，严格字节检查会阻止，不静默认作同一候选包。

生命周期验收在截止附近可能读到HTTP已撤销、worker仍清理的过渡态；脚本不展示该状态的入口，仅在有界等待后要求明确expired、资源已清理且监听已关闭。已补状态序列回归，并完整重跑最终归档验收。

## 复现

```sh
<dev-python> -m unittest discover -s tests -v
<dev-python> tools/build_release.py
<runtime-python> -m pip install -r skills/lan-file-share-assistant/requirements.txt
```

在macOS本地执行，准备的虚拟环境只用于运行解压CLI，`<dev-python>`另需Pillow和zxing-cpp。依次在**独立工具调用**中执行下列三步；probe创建后60秒内必须继续start，start后及时verify。会短时启动仅含合成资料的真实局域网服务：

```sh
<dev-python> tools/smoke_archive.py prepare --python <runtime-python>
```

```sh
<dev-python> tools/smoke_archive.py start
```

```sh
<dev-python> tools/smoke_archive.py verify
```

verify等待WorkBuddy包60秒到期。成功或失败后调用`<dev-python> tools/smoke_archive.py cleanup`，仅清理该工具确认拥有的会话和目录。原始输出只在outputs/m4，仓库提交脱敏结果。

## 后续

本地归档通过与平台接受分别记录。用户授权后再进行WorkBuddy上传解析、Logo裁切检查、最终包安装后Agent烟测和审核；Windows/Linux真机LAN/Agent、手机副本摘要和整机睡眠保持各自待验收状态。
