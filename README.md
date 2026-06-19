# QQNT_Export

> **Version 3.0.0** - 全新重构版本

一个用于导出 QQNT（QQ NT 版本）聊天记录的 Python 工具，支持导出为 ChatLab 标准格式。

## ✨ 主要特性

- **解析与导出解耦**：清晰的三层架构（数据库 → 解析 → 导出）
- **支持 ChatLab 格式**：符合 [ChatLab v0.0.2](https://github.com/ChatLab/ChatLab) 标准
- **丰富的消息类型**：文本、图片（含闪照）、文件、语音、视频、QQ/商城表情、引用、撤回、拍一拍、红包、Ark 卡片、位置等
- **插件化导出器**：轻松添加新的导出格式
- **可扩展解析器**：注册机制添加新的消息元素类型
- **导出进度条**：基于 tqdm 实时显示导出进度
- **流式处理**：JSONL 格式支持超大规模数据导出

## 📦 导出格式

- **chatlab_json**：ChatLab JSON 格式（适合 <100万条消息）
- **chatlab_jsonl**：ChatLab JSONL 流式格式（适合 >100万条消息）

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

# 3. 配置并运行
cp example.toml my_config.toml
# 编辑 my_config.toml
python main.py my_config.toml
```

## ⚙️ 配置文件

创建或编辑 `.toml` 配置文件：

```toml
db_path = "./databases/"  # 解密后的数据库目录
pic_path = "./chatpic/"   # chatpic目录（可选）
output_path = ""          # 导出路径（默认为 databases/../output）

c2c_filters = []          # 私聊过滤（QQ号列表，空=全部）
group_filters = []        # 群聊过滤（群号列表，空=全部）

# 导出格式：chatlab_json 和/或 chatlab_jsonl
output_format = ["chatlab_json", "chatlab_jsonl"]
```

## 📁 项目结构

```
QQNT_Export/
├── db/                   # 数据库层
│   ├── models.py         # SQLAlchemy 模型
│   └── man.py            # DatabaseManager
├── parser/               # 解析层（新）
│   ├── models.py         # 数据模型
│   ├── elements.py       # 元素解析器（注册机制）
│   └── message.py        # 消息解析器
├── exporters/            # 导出层（新）
│   ├── base.py           # 导出器基类
│   ├── chatlab_json.py   # ChatLab JSON 导出器
│   └── chatlab_jsonl.py  # ChatLab JSONL 导出器
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

本项目仅处理**已解密**的数据库。解密工具：

- **Android**: [qqnt_backup](https://github.com/xCipHanD/qqnt_backup)
- **Windows**: 参考 [qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)

## 🧪 测试

运行架构测试：
```bash
python test_architecture.py
```

运行特殊消息测试：
```bash
python test_special_messages.py
```

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

## 🔄 版本历史

### v3.0.0 (2026-06-14)

- 🎉 全面重构：解析和导出完全解耦
- ✨ 支持 ChatLab v0.0.2 标准格式
- ✨ 插件化导出器架构
- ✨ 注册机制的元素解析器
- ✨ JSONL 流式导出支持超大规模数据
- ✨ 丰富消息语义解析（撤回、拍一拍/戳一戳、闪照、商城表情、Ark 卡片路由等）
- ✨ 导出进度条（tqdm）
- 🐛 优化图片和引用消息的 ChatLab 格式
- 📝 完整的文档和测试

### v2.x 及更早版本

查看 [v2.x 分支](https://github.com/Tealina28/QQNT_Export/tree/main) 获取原始版本。
