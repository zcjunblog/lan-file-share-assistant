# M3 补充验收：基础解释器、容量与修订版客户端

日期：2026-11-06（Asia/Shanghai）。基于e618681的Skill源码补验，未改动生产源码、运行参数上限或默认有效期。整机睡眠依用户选择继续暂缓；未提交市场或公开仓库。

## Python3.9与独立解压

使用macOS系统Python3.9.6新建独立虚拟环境，只按Skill的requirements.txt安装运行依赖。直接声明仍为Segno1.6.6；其Python<3.10条件依赖自动安装importlib-metadata和zipp。环境中没有jsonschema、Pillow、zxing-cpp或PyYAML开发依赖。

将当前标准Skill的10份源码打成开发归档并解压到独立目录，核对逐文件内容一致，使用解压后的程序而非仓库源码运行。无网络probe与后续启动分两次独立工具调用，实际预检、自检、文件访问和停止均通过。

## 2GiB单文件与5GiB总量

合成文件大小为2GiB、2GiB、1GiB，恰好达到设计上限；它们由测试新建的稀疏零数据文件组成，不包含用户资料。实际生成了完整5GiB私有快照，通过所选局域网地址上的本机HTTP读取全部5GiB字节，逐文件比较独立计算的零数据SHA-256、快照报告摘要与下载摘要，全部一致。

准备耗时约6.37秒；实际时间和内存采样见[原始白名单结果](runtime-39-capacity.json)。服务子进程观测到的峰值RSS约21MiB。这说明本次样本按块处理，不能将采样值视为任何系统下的硬内存上限。

本次是**同一电脑的合成容量验收，不是手机大文件传输或真实Wi-Fi吞吐基准**。测试期间源文件身份未改变；停止后核实监听关闭、私有快照和凭据删除，再清理本次大合成样本。未保存第二份5GiB下载副本，接收端流式计算摘要。

复现需要当前macOS后端与至少20GiB可用空间。以下仅用于已授权的开发验收，会短时监听本机私有地址，并临时写入约5GiB快照：

```sh
/usr/bin/python3 -m venv outputs/m3/baseline-39-env
outputs/m3/baseline-39-env/bin/python -m pip install -r skills/lan-file-share-assistant/requirements.txt
outputs/m3/baseline-39-env/bin/python tools/m3_capacity.py prepare
# 下一次独立工具调用，60秒内执行
outputs/m3/baseline-39-env/bin/python tools/m3_capacity.py exercise
```

工具保留既有证据：outputs/m3/capacity-39已存在时拒绝重建，可在新的隔离检出目录复现。prepare不启动文件服务；exercise确认来源、预检和私有工作区后才启动，结束后停止并清理本次数据。原始地址、凭据、归档和进程诊断不进入仓库。

## 修订后WorkBuddy完整流程

WorkBuddy V5.9.3重新读取已安装的M3修订版说明，用新runtime与新合成文件执行四次独立调用：probe → start → status加下载摘要核验 → stop加终态核验。此次TTL明确为300秒，没有等到自然到期。

源文件、下载副本和status三方SHA-256一致，页面及文件HTTP200，副本7,300字节；stop后为stopped、监听关闭、敏感资源清理。本轮不覆盖前两次60秒验证记录。主Agent额外逐字节比较副本、计算摘要、核对当前安装的10份源码、实际终态与端口关闭，见[白名单结果](workbuddy-current.json)。

这补齐了上轮安装更新后尚未完整运行Agent的缺口；**正式M4构建包安装烟测仍是独立待办**。本机Agent重跑也不能替代手机副本摘要、其他系统或其他客户端的实测。

## 仍待完成

整机睡眠、真实系统时钟改变、整个宿主退出、手机副本SHA-256及具体机型/浏览器、Windows/Linux后端和真机、其他Agent、60分钟长运行仍未验证。未发现本机现成的Docker/Podman/Colima/Lima/QEMU/Wine运行工具，本轮没有安装虚拟机或推断跨系统通过。
