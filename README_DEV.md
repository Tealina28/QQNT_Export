# QQNT_Export - 重构版

## 🎉 重构说明

本项目已在 `dev` 分支完成重构，采用全新的解耦架构。

### 主要变化

#### ✨ 新特性
- **解析与导出解耦**：清晰的三层架构（数据库 → 解析 → 导出）
- **支持 ChatLab 格式**：符合 [ChatLab v0.0.2](https://github.com/ChatLab/ChatLab) 标准
- **插件化导出器**：轻松添加新的导出格式
- **可扩展解析器**：注册机制添加新的消息元素类型
- **流式处理**：JSONL 格式支持超大规模数据导出

#### 📦 导出格式
- `chatlab_json`：ChatLab JSON 格式（适合 <100万条消息）
- `chatlab_jsonl`：ChatLab JSONL 流式格式（适合 >100万条消息）

### 快速开始

```bash
# 1. 克隆项目并切换到 dev 分支
git clone <repo-url>
cd QQNT_Export
git checkout dev

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 3. 配置导出参数
cp example.toml my_config.toml
# 编辑 my_config.toml 设置数据库路径等

# 4. 运行导出
python main.py my_config.toml
```

### 配置文件示例

```toml
db_path = "./databases/"  # 解密后的数据库目录
pic_path = "./chatpic/"   # chatpic目录（可选）
output_path = ""          # 导出路径（默认为 databases/../output）

c2c_filters = []          # 私聊过滤（QQ号列表，空=全部）
group_filters = []        # 群聊过滤（群号列表，空=全部）

# 导出格式：chatlab_json 和/或 chatlab_jsonl
output_format = ["chatlab_json", "chatlab_jsonl"]
```

### 架构概览

```
QQNT_Export/
├── db/                   # 数据库层（未改动）
│   ├── models.py         # SQLAlchemy 模型
│   └── man.py            # DatabaseManager
├── parser/               # 解析层（新）
│   ├── models.py         # 数据模型（ParsedMessage, ParsedElement, ParsedMember）
│   ├── elements.py       # Element 解析器（注册机制）
│   └── message.py        # 消息解析器
├── exporters/            # 导出层（新）
│   ├── base.py           # 导出器基类
│   ├── chatlab_json.py   # ChatLab JSON 导出器
│   └── chatlab_jsonl.py  # ChatLab JSONL 导出器
└── main.py               # 主程序（重写）
```

### ChatLab 格式示例

**JSON 格式** (小中型记录)：
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
      "groupNickname": "群主",
      "timestamp": 1703001600,
      "type": 0,
      "content": "大家好！"
    }
  ]
}
```

**JSONL 格式** (大规模记录)：
```jsonl
{"_type":"header","chatlab":{"version":"0.0.2"},"meta":{"name":"技术交流群","platform":"qq","type":"group"}}
{"_type":"member","platformId":"uid_123","accountName":"张三","roles":[{"id":"owner"}]}
{"_type":"message","sender":"uid_123","timestamp":1703001600,"type":0,"content":"大家好！"}
```

### 测试

运行架构测试：
```bash
python test_architecture.py
```

### 扩展性

#### 添加新的消息元素类型

编辑 `parser/elements.py`：

```python
@ElementParser.register(99)  # 新的 element.type
def parse_new_type(element) -> ParsedElement:
    return ParsedElement(
        type=ElementType.OTHER,
        content={'custom_field': element.customField}
    )
```

#### 添加新的导出格式

1. 在 `exporters/` 创建新文件
2. 继承 `BaseExporter` 并实现接口
3. 在 `exporters/__init__.py` 注册导出器

### 数据库解密

本项目仅处理**已解密**的数据库。解密工具：
- Android: [qqnt_backup](https://github.com/xCipHanD/qqnt_backup)
- Windows: 参考 [qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)

---

## 原版说明

查看 `main` 分支获取原始版本的文档和代码。

## 讨论与贡献

- 答疑讨论：[Discussions](https://github.com/Tealina28/QQNT_Export/discussions)
- 协作开发：欢迎 SQL/Protobuf 相关经验的贡献者

## 许可

本项目基于 [GPLv3](https://www.gnu.org/licenses/gpl-3.0.zh-cn.html) 开源。

## 免责声明

本项目仅供学习交流使用，严禁用于任何违反法律法规的行为。开发者不承担任何相关行为导致的直接或间接责任。
