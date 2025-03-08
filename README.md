# QQNT_Export

## 介绍

本项目用于读取并导出**解密后的**QQNT数据库中的聊天记录。

解密数据库请使用[qqnt_backup](https://github.com/xCipHanD/qqnt_backup)（Android）或参照[qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)。

由于作者对SQL和Protobuf一窍不通，所以代码水平较差，寻求合作者。

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

`path`指**解密后的**数据库目录路径。

```bash
python main.py [path]
```

或

```bash
[二进制文件名] [path]
```
若一切正常，你应该看到在`path`的上级目录生成了`outputs/c2c`目录，目录中对于每个私聊对象生成了一个`.txt`文件（不知道`0.txt和None.txt`是怎么回事）。

## 关于

本项目基于[GPLv3](https://www.gnu.org/licenses/gpl-3.0.zh-cn.html)开源。

## 鸣谢


| 对象                                       | 内容                          |
|------------------------------------------|-----------------------------|
| [@yllhwa](https://github.com/yllhwa)     | 初始代码和Protobuf定义             |
| [@shenapex](https://github.com/shenapex) | 数据表部分列含义，Protobuf的消息段部分字段含义 |
| [QQDecrypt](https://qq.sbcnm.top/)       | 数据表部分列含义，Protobuf的消息段部分字段含义 |

## 免责声明

本项目仅供学习交流使用，严禁用于任何违反中国大陆法律法规、您所在地区法律法规、QQ软件许可及服务协议的行为，开发者不承担任何相关行为导致的直接或间接责任。

本项目不对生成内容的完整性、准确性作任何担保，生成的一切内容不可用于法律取证，您不应当将其用于学习与交流外的任何用途。