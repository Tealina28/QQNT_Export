# QQNT_Export

> **Version 3.0.0** - 全新重构版本

一个用于导出 QQNT（QQ NT 版本）聊天记录的 Python 工具，支持导出为 ChatLab 标准格式。

## ✨ 主要特性

- **解析与导出解耦**：清晰的三层架构（数据库 → 解析 → 导出）
- **支持 ChatLab 格式**：符合 [ChatLab v0.0.2](https://github.com/ChatLab/ChatLab) 标准
- **丰富的消息类型**：文本/@、图片（含闪照）、文件/在线文件夹、语音、视频、QQ/商城/互动表情、引用、递归合并转发、结构化群提示、贴表情、红包/转账、Ark、Markdown/按钮/闪传、QQ 动态和位置等
- **插件化导出器**：轻松添加新的导出格式
- **可扩展解析器**：注册机制添加新的消息元素类型
- **导出进度条**：基于 tqdm 实时显示导出进度
- **流式处理**：JSONL 与 HTML 支持超大规模数据导出，HTML 按日期分块渲染
- **单次解析**：同时导出多个格式时共享消息解析结果，避免重复扫描数据库
- **离线头像**：ChatLab 输出成员/群头像，HTML 可复制 QQ NT 本地头像缓存
- **跨设备消息**：导出 `dataline_msg_table` 中“我的手机/电脑/平板”同步记录
- **QQ 系统表情**：读取可选的 `emoji.db`，HTML 优先显示 APNG、静态图并最终回退文字
- **语音播放**：兼容标准、扁平 MD5 和旧式 PTT 缓存，解码 QQ SILK 为 WAV 供 HTML 播放
- **可选批量解密**：批量解密用户已提取的 Android QQNT 数据库（`gpro` 除外）

## 📦 导出格式

- **chatlab_json**：ChatLab JSON 格式（适合 <100万条消息）
- **chatlab_jsonl**：ChatLab JSONL 流式格式（适合 >100万条消息）
- **html**：可搜索、按发送者/日期筛选的流式 HTML 聊天记录

## 🚀 快速开始

### 方式 1：使用预编译版本（推荐 Windows 用户）

1. 从 [Releases](https://github.com/Tealina28/QQNT_Export/releases) 下载最新的 `QQNT_Export-v3.0.0.exe`
2. 准备 `example.toml` 配置文件（设置数据库路径等），与 exe 放在同一目录
3. 在命令行运行：
   ```bash
   QQNT_Export.exe example.toml
   ```

### 方式 2：从源码运行

```bash
# 1. 克隆项目
git clone https://github.com/Tealina28/QQNT_Export.git
cd QQNT_Export

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 Windows: venv\Scripts\activate
pip install -r requirements.txt

# 如需解密 Android QQNT 加密数据库，再安装可选依赖
pip install -r requirements-decrypt.txt

# 3. 配置并运行
cp example.toml my_config.toml
# 编辑 my_config.toml
python main.py my_config.toml
```

## ⚙️ 配置文件

创建或编辑 `.toml` 配置文件：

```toml
db_path = "./databases/"  # 明文目录；启用 decrypt 时为 Android 加密库目录
pic_path = "./chatpic/"   # chatpic目录（可选）
output_path = ""          # 导出路径（默认为 databases/../output）

c2c_filters = []          # 私聊过滤（QQ号列表，空=全部）
group_filters = []        # 群聊过滤（群号列表，空=全部）
conversation_types = ["c2c", "group", "dataline"]
dataline_owner = "pc"    # 数据线中的本机设备：pc、phone 或 pad

# 导出格式：chatlab_json、chatlab_jsonl 和/或 html
output_format = ["chatlab_json", "chatlab_jsonl", "html"]
stream_batch_size = 1000 # JSONL/HTML 每批读取的消息数
copy_resources = true   # HTML 复制图片和本地头像
avatar_path = ""        # 可选：nt_data/avatar 或 nt_data 目录
emoji_path = ""         # 可选：nt_data 或 EmojiSystermResource 目录
ptt_path = ""           # 可选：nt_data 或 Ptt 目录
silk_transcode = true   # HTML 将 QQ SILK/.amr 解码为 WAV
embed_avatars = false   # ChatLab 是否嵌入本地头像 Data URL

[decrypt]
enabled = false
backend = "android_qqnt"
uid = ""                       # Android QUID
output_path = "./decrypted/"  # 持久明文数据库目录
overwrite = false
```

导出结果分别写入 `output/c2c/`、`output/group/` 和
`output/dataline/`。只会查询和创建 `conversation_types` 中启用的会话类型。
数据线会话无需过滤配置；`dataline_owner` 决定
ChatLab 的 `ownerId` 以及 HTML 中消息的收发方向。

## 📁 项目结构

```
QQNT_Export/
├── db/                   # 数据库层
│   ├── models.py         # SQLAlchemy 模型
│   ├── man.py            # DatabaseManager
│   └── decryption.py     # 可选的 Android QQNT 批量解密
├── parser/               # 解析层（新）
│   ├── models.py         # 数据模型
│   ├── avatar.py         # 头像 URL 与本地缓存解析
│   ├── dataline.py       # 数据线设备身份
│   ├── elements.py       # 元素解析器（注册机制）
│   └── message.py        # 消息解析器
├── exporters/            # 导出层（新）
│   ├── base.py           # 导出器基类
│   ├── chatlab_json.py   # ChatLab JSON 导出器
│   ├── chatlab_jsonl.py  # ChatLab JSONL 导出器
│   └── html.py           # 流式 HTML 导出器
├── main.py               # 主程序
├── example.toml          # 配置示例
└── README.md             # 本文档
```

## 📝 ChatLab 格式示例

### JSON 格式（中小型记录）

```json
{
  "chatlab": {
    "version": "0.0.2",
    "exportedAt": 1703001600,
    "generator": "QQNT_Export"
  },
  "meta": {
    "name": "技术交流群",
    "platform": "qq",
    "type": "group",
    "groupId": "123456"
  },
  "members": [
    {
      "platformId": "uid_123",
      "accountName": "张三",
      "groupNickname": "群主",
      "roles": [{"id": "owner"}]
    }
  ],
  "messages": [
    {
      "platformMessageId": "1",
      "sender": "uid_123",
      "accountName": "张三",
      "timestamp": 1703001600,
      "type": 0,
      "content": "大家好！"
    }
  ]
}
```

### JSONL 格式（大规模记录）

```jsonl
{"_type":"header","chatlab":{"version":"0.0.2"},"meta":{"name":"技术交流群","platform":"qq","type":"group"}}
{"_type":"member","platformId":"uid_123","accountName":"张三","roles":[{"id":"owner"}]}
{"_type":"message","sender":"uid_123","timestamp":1703001600,"type":0,"content":"大家好！"}
```

## 🔧 数据库解密

项目可在导出前解密用户已经合法提取的 **Android NT QQ** 数据库目录。
该功能不负责 root、ADB、备份提取或 Windows QQNT 密钥获取。

1. 安装可选依赖：`pip install -r requirements-decrypt.txt`。
2. 完全退出 QQ 后复制账号的 `nt_qq_<hash>` 数据库目录。
3. 将 `db_path` 指向该加密目录，并在配置中启用 `[decrypt]`、填写
   QUID 与独立的明文 `output_path`。

解密会遍历输入目录顶层的 `*.db`，不按本项目当前使用的数据库做白名单
筛选；已知不兼容的 `gpro_v1-6_u_*.db` 及上游遗留
`en_gpro_v1-6_u_*.db` 会被显式跳过。其余数据库先写入同目录下的私有
staging；单个数据库的头校验、复制、解密或明文验证失败时会记录警告并继续，
只要至少一个数据库成功就发布本轮成功集合，清单也只包含这些成功数据库；
全部失败时不发布，并保留已有的受管理输出。源文件不会被修改。

为避免静默丢失未 checkpoint 的最新数据，输入目录存在非空
`*.db-wal` 或 `*.db-journal` 时会直接拒绝处理。明文数据库包含完整聊天
资料，请妥善保管；默认不会在导出后自动删除。`overwrite = true` 也只能
替换带有本工具有效清单且文件集合完全匹配的旧解密目录，不会删除任意目录。
源目录在处理期间变化、目标目录不安全或发布失败等全局一致性/安全问题仍会
停止整批处理。若导出所必需的 `nt_msg.db` 未成功，已成功的明文数据库会保留，
但本次聊天记录导出不会继续。

Windows 下会在关闭 SQLite/SQLCipher 句柄后清理失败数据库的暂存文件，并对
Defender、索引器等造成的瞬时共享冲突做短暂重试。若文件持续被占用，仍会停止
发布并报告暂存目录，避免把失败的明文 `.partial` 混入结果。

参考实现明确标注暂不支持解密 `gpro_v1-6_u_*.db`，因此当前输出不包含
该数据库。其余数据库仍需用对应 QQ 版本的原始加密目录验证兼容性。

目前内置的密钥派生方式只适用于 Android。Windows 数据库仍需先通过其他
方式取得密钥或完成解密，例如参考
[qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)。

## 🛠️ 开发指南

### 添加新的消息元素类型

编辑 `parser/elements.py`：

```python
@ElementParser.register(99)  # 新的 element.type
def parse_new_type(element) -> ParsedElement:
    return ParsedElement(
        type=ElementType.OTHER,
        content={'custom_field': element.customField}
    )
```

### 添加新的导出格式

1. 在 `exporters/` 创建新文件
2. 继承 `BaseExporter` 并实现接口：

```python
class MyExporter(BaseExporter):
    def export(self, meta, members, messages):
        # 实现导出逻辑
        pass
    
    def get_file_extension(self) -> str:
        return '.myformat'
```

3. 在 `exporters/__init__.py` 的 `EXPORTER_MAP` 中注册

## 📄 许可证

本项目基于 [GPLv3](https://www.gnu.org/licenses/gpl-3.0.zh-cn.html) 开源。

## 🙏 鸣谢

| 对象 | 贡献 |
|------|------|
| [@yllhwa](https://github.com/yllhwa) | 初始代码和Protobuf定义 |
| [QQDecrypt](https://docs.aaqwq.top/) | 数据表部分列含义，Protobuf的消息段部分字段含义 |
| [@shenapex](https://github.com/shenapex) | 解读数据库和导出聊天记录的研究工作 |
| [nt_msg.py](https://github.com/BrokenC1oud/nt_msg.py) | SQLAlchemy模型, DatabaseManager |
| [qq-dump](https://github.com/miniyu157/qq-dump) | Protobuf 字段映射参考（撤回、互动表情、Ark 卡片等消息语义） |
| [QQNT-Database-Export-Tool](https://github.com/star-picker/QQNT-Database-Export-Tool) | 消息元素解析逻辑参考 |
| [ChatLab](https://github.com/ChatLab/ChatLab) | 标准化聊天数据交换格式 |

## 💬 讨论与贡献

- 答疑讨论：[Discussions](https://github.com/Tealina28/QQNT_Export/discussions)
- 协作开发：欢迎 SQL/Protobuf 相关经验的贡献者
- Issue 反馈：[Issues](https://github.com/Tealina28/QQNT_Export/issues)

## ⚠️ 免责声明

本项目仅供学习交流使用，严禁用于任何违反中国大陆法律法规、您所在地区法律法规、QQ软件许可及服务协议的行为。开发者不承担任何相关行为导致的直接或间接责任。

本项目不对生成内容的完整性、准确性作任何担保，生成的一切内容不可用于法律取证，您不应当将其用于学习与交流外的任何用途。
