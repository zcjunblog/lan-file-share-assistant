# 参与贡献

欢迎提交问题、文档改进和代码PR。Windows/Linux的真实局域网与Agent验收尤其有帮助。

## 反馈问题

请说明操作系统、Python版本、Agent客户端及版本、执行步骤、预期结果和实际reason_code。用可以公开的合成文件复现，保留必要的文件类型与大小即可。

分享链接、二维码、访问/控制凭据、本机IP、真实文件和完整原始状态属于本地运行资料，请从公开Issue、截图及日志中移除。程序的本机自检与另一设备下载应分别记录。

## 提交改动

先阅读[项目设计](memory-bank/design.md)和[协作约定](Agent.md)。修复可复现问题，说明触发条件、行为变化及验证结果；涉及新的使用场景时先开Issue沟通范围。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-m2-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/check_m2_repository.py
```

运行时保持Python3.9+，二维码直接依赖Segno1.6.6。开发依赖不进入Skill包。修改资源时同步维护tools/distribution.py的显式资源登记，两个包的业务文件继续共享同一来源。

自动化测试默认使用合成文件及局部测试服务。完整生产链路验收会短时启动局域网监听，应按[evidence/m4](evidence/m4/README.md)明确选择执行；不要对他人的文件或设备发起测试。

## 需要保持的行为

- 分享前检测，不把云端或未知执行位置当作用户电脑。
- 逐项授权文件、原文件只读、私有快照与随机访问凭据。
- 截止后关闭监听和进行中传输，不静默续期或恢复旧凭据。
- 不自动关闭防火墙、修改VPN/路由或绑定所有网卡以绕过预检。
- 如实标明平台和客户端验证范围，未验证项继续保留。

提交PR表示你有权按本项目的[MIT许可证](LICENSE)提供这些改动。依赖继续遵循各自的上游许可证。
