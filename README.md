# QQNT_Export

## 讨论

- **答疑**：可能会在 [Discussions](https://github.com/Tealina28/QQNT_Export/discussions) 提出开发中的问题，欢迎协助解答。
- **讨论**：技术方案等各类讨论欢迎在 [Discussions](https://github.com/Tealina28/QQNT_Export/discussions) 中发起。
- **协作开发**：如果您有 SQL/Protobuf 相关经验，特别欢迎参与项目改进。

## 介绍

本项目用于读取并导出**解密后的**QQNT数据库中的聊天记录。

解密数据库请使用[qqnt_backup](https://github.com/xCipHanD/qqnt_backup)（Android）或参照[qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)。


## 使用流程

有两种使用方式

1. 使用二进制文件（Windows）。

2. 使用源代码。

### 获取二进制文件

Windows用户可到[Releases](https://github.com/Tealina28/QQNT_Export/releases)中下载二进制文件。

### 获取源代码

1. 克隆或下载本仓库。

2. 确保你拥有[Python 3](https://www.python.org/downloads/)环境，建议使用较新的版本。

3. 使用`pip install -r requirements.txt`安装项目依赖。

### 使用

创建`.toml`文件，并按照仓库中`example.toml`的格式修改配置。使用时传入该`.toml`文件的路径作为唯一参数即可。

示例：`python main.py .\example.toml`

> 对于之前版本，仍可使用`python main.py --help`查看帮助信息。

若一切正常，你应该看到在生成了`output`目录，目录中对于每个私聊对象和群聊生成了一个`.txt`或`.json`文件。

## 关于

本项目基于[GPLv3](https://www.gnu.org/licenses/gpl-3.0.zh-cn.html)开源。

## 鸣谢


| 对象                                                    | 内容                                                                                                                            |
|-------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| [@yllhwa](https://github.com/yllhwa)                  | 初始代码和Protobuf定义                                                                                                               |
| [QQDecrypt](https://docs.aaqwq.top/)                  | 数据表部分列含义，Protobuf的消息段部分字段含义。<br/>该网站的设立者[@shenapex](https://github.com/shenapex)为解读数据库和导出聊天记录做了大量的研究工作，向他致敬🫡。 |
| [nt_msg.py](https://github.com/BrokenC1oud/nt_msg.py) | SQLAlchemy模型, DatabaseManager（抄了好多，大佬好强）                                                                                      |

## 免责声明

本项目仅供学习交流使用，严禁用于任何违反中国大陆法律法规、您所在地区法律法规、QQ软件许可及服务协议的行为，开发者不承担任何相关行为导致的直接或间接责任。

本项目不对生成内容的完整性、准确性作任何担保，生成的一切内容不可用于法律取证，您不应当将其用于学习与交流外的任何用途。
