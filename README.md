# QQNT_Export

## 介绍

本项目用于解密并读取QQNT数据库中的聊天记录。

⚠目前仅能解密QQNT（Android）数据库。

由于作者对SQL和Protobuf一窍不通，所以代码水平较差，需要合作者。

## 使用流程

存在两种使用方式

1. 使用二进制文件（Windows）。

2. 使用源代码。

### 获取二进制文件

Windows用户可到[Releases](https://github.com/Tealina28/QQNT_Export/releases)中下载二进制文件。

### 获取源代码

1. 克隆或下载本仓库。

2. 确保你拥有[Python 3.12.8](https://www.python.org/downloads/release/python-3128/)或近似的Python版本（仅限Python3.11和Python3.12）。

3. 使用`pip install -r requirements.txt`安装项目依赖。

### 使用

#### 解密

`path`指数据库目录路径，如`X:/nt_qq_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`。

`uid`的获取方法见于[qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)。

在仓库根目录打开命令行，运行

```bash
python main.py decrypt [path] [uid]
```

或

```bash
[二进制文件名] decrypt [path] [uid]
```

若一切正常，你应该看到在`path`的上级目录生成了解密后的的数据库目录。

#### 读取

`path`指解密后的的数据库目录路径。

```bash
python main.py decode [path]
```

或

```bash
[二进制文件名] decode [path]
```
若一切正常，你应该看到在`path`的上级目录生成了`outputs`目录，目录中对于每个私聊对象生成了一个`.txt`文件（不知道`0.txt`是怎么回事）。



## 关于

本项目基于[GPLv3](https://www.gnu.org/licenses/gpl-3.0.zh-cn.html)开源。

## 鸣谢

解密部分代码来自[qqnt_backup](https://github.com/xCipHanD/qqnt_backup)。

读取部分代码基础来自[qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)和[@yllhwa](https://github.com/yllhwa)

## 免责声明

本项目仅供学习交流使用，严禁用于任何违反中国大陆法律法规、您所在地区法律法规、QQ软件许可及服务协议的行为，开发者不承担任何相关行为导致的直接或间接责任。

本项目不对生成内容的完整性、准确性作任何担保，生成的一切内容不可用于法律取证，您不应当将其用于学习与交流外的任何用途。