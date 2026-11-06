# M2 首版实现验证

日期：2026-11-06（Asia/Shanghai）。范围为标准Skill源码、macOS生产预检与本机HTTP端到端验证。使用全部由测试工具生成的合成文件，未读取或分享用户真实资料，未更改网络配置。

## 实际执行

| 项目 | 结果与证据 |
| --- | --- |
| 自动化测试 | 39项通过，含M1的12项方法及M2的27项；[完整输出](automated-tests.txt) |
| Skill入口 | skill-creator的quick_validate通过，标准名称、描述与参考路径有效；不是市场安装通过 |
| 生产预检 | 八项实际检查全部通过；生产报告另经M1的独立Schema/语义检查，未使用fixture作为生产依据 |
| 解释器差异 | Python3.12.14虚拟环境执行生产链路；系统Python3.9.6可执行CLI并准确报告二维码依赖缺失、宿主未知和未做生命周期探针；[摘要](runtime-compat.json) |
| 后台存活 | 无网络探针跨独立工具调用产生新心跳、响应受控停止；分享服务在start返回后的另一工具调用中仍通过status挑战核验 |
| 文件交付 | 5份合成文件：中文文本、中文长文件名、有效空白PDF、ZIP和64MiB中断样本；接收字节大小和SHA-256全部一致，源文件未变 |
| 真实二维码 | Segno生成实际会话PNG/SVG，zxing-cpp通过Pillow独立解码PNG，再使用解码URL进行真实本机HTTP下载；不是手机扫码 |
| 实际到期 | 有效期60秒，截止前发起未消费完的64MiB下载；截止后连接中断、监听关闭、状态expired、快照/凭据/二维码删除；[结果](local-integration.json) |
| 实际停止 | 错误控制令牌不能停止；正确本地停止请求中断两条进行中下载，监听关闭且清理完成；[结果](manual-stop.json) |
| 请求限制 | 实际HTTP拒绝错误访问凭据、未知文件ID、路径越界、编码越界及错误Host；自动测试还覆盖跨来源、下载配额及真实socket中断 |
| 失败与取消 | 自动测试验证预检未通过不启动、准备阶段取消、准入凭证过时、绑定失败及QR失败均不发布链接并清理所属资源 |
| 页面 | 独立无头Chrome、1280px桌面/390px手机宽度，中文长文件名无横向溢出、5个入口、无JS错误；前端失效态以浏览器时钟模拟；[检查结果](ui-checks.json) |

[桌面截图](download-desktop.png) · [移动端截图](download-mobile.png) · [前端失效态截图](download-expired-mobile.png)

三张截图均已逐张查看。没有显示真实本机IP、访问/控制凭据或二维码，截图内容均为合成测试资料。页面失效截图与服务端真实到期是两份独立证据，不相互替代。

## 复现方式

先在本机准备Python3.10+开发虚拟环境与requirements-m2-dev.txt，再运行：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

下面是**主动监听本机局域网的集成测试**，只用于已允许短时本机分享的开发任务。不要拿它分享真实资料，也不要在远端环境伪造desktop_adapter。脚本固定使用outputs/m2下自行创建的合成文件。

第一次独立工具调用：

```sh
.venv/bin/python tools/m2_e2e.py prepare
```

下一次独立工具调用，在60秒内执行：

```sh
.venv/bin/python tools/m2_e2e.py start60
.venv/bin/python tools/m2_e2e.py watch
```

watch验证二维码与文件后等待真实截止，约60秒结束；执行工具应短时yield，避免阻塞与用户沟通。二维码、链接和原始状态只留outputs/m2，脚本向控制台只打印布尔/计数摘要。

手动停止及页面检查另用一组有限会话。先在独立工具调用运行probe，下一调用start180，后续调用verify、可选浏览器检查、stop：

```sh
.venv/bin/python tools/m2_e2e.py probe
# 下一次独立工具调用
.venv/bin/python tools/m2_e2e.py start180
# 后续独立调用
.venv/bin/python tools/m2_e2e.py verify
# 可选：已准备开发用Playwright与Chrome的Node环境执行tools/m2_ui.cjs
.venv/bin/python tools/m2_e2e.py stop
```

不得省略stop；若未手动停止，180秒到期也会由服务自行关闭。集成测试在本机只有一个明确物理接口候选时自动选择；有多个候选会阻止并要求选址，不关闭VPN或修改防火墙。跨设备连通性始终为not_tested。

## 能证明与不能证明

目前验证了当前macOS/Codex本地执行工具中的有限后台运行、真实下载与实际强制停止。并未验证物理手机扫码、WorkBuddy/其他客户端、Windows/Linux、60分钟长运行、系统真实睡眠、改变系统时间、异常断电或宿主强制回收。

系统时钟回拨/前跳及连续时钟到期使用注入时钟单元测试；mach_continuous_time API在实际服务中使用，包含休眠的性质依据M1核对的Apple语义，不能据此声称做过物理睡眠实验。64MiB样本不是2GiB/5GiB上限吞吐验收。

M2原始数据留outputs/m2；仓库只保留白名单脱敏结果、自动化输出和无凭据截图。正常终止清理服务持有的快照及凭据；开发测试脚本的合成源文件和私有诊断记录留在忽略目录，便于复核。强制终止后的遗留资源核验仍需M3补充。

下一阶段为M3真实同网手机、目标客户端、物理生命周期与故障验收；M4发布包、品牌素材、公开及提审尚未开始。
