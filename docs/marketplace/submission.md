# WorkBuddy发布准备单

日期：2026-11-06（Asia/Shanghai）。状态：**发布执行中。初次候选解析通过；用户要求升级Logo，更新候选包受旧草稿同名占用，正在完成最终包安装验收。未提交审核，未上线。**

- 中文名称：局域网文件分享助手。
- 英文名称：LAN File Share Assistant。
- 候选版本：0.1.0，单一版本源为Skill根目录VERSION。
- 包：releases/0.1.0/lan-file-share-assistant-workbuddy-0.1.0.zip。
- 图标：skills/lan-file-share-assistant/assets/icon-512.png，512×512；同目录icon.svg为配套简化矢量版本，正式位图原图保存在icon-original.png。
- 封面：docs/images/cover.png；流程：docs/images/workflow.svg。均为产品示意，不含有效二维码、地址或私有资料。
- 展示介绍与三组双语示例：distribution/workbuddy.json。静态构建要求双语示例非空且数量一致。
- 建议分类：办公协同/工具，最终以平台实际可选项为准。
- 支持口径：macOS已有实际客户端证据；Windows/Linux为实验性支持、原生CI通过，真实LAN及Agent待验收。HTTP未加密。
- 用户已授权本次WorkBuddy发布；GitHub源码继续私有，许可证另行决定。价格及市场范围按平台实际配置记录。

## 授权后的平台核验

1. 对照manifest.json和SHA256SUMS确认将上传的具体包。
2. 上传后读取实际解析结果，核对名称、版本、双语介绍和三组示例。
3. 上传512px Logo，检查实际裁切和清晰度。
4. 安装该候选包，以合成文件完整执行Agent预检、二维码、下载摘要和停止清理；安装前备份已有自有Skill。
5. 核对支持范围、展示分类、公开与价格，用户授权后提交审核。
6. 分别记录平台解析、安装、审核提交、审核结果与上线状态，不以ZIP成功代替平台接受。

字段来源：[WorkBuddy官方Skill文档](https://open.workbuddy.cn/docs/skill)，2026-11-06核对。README素材与详情页“试试这样用”不是同一配置项，不保证封面自动成为平台案例展示。
