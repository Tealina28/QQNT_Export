# 发布 v3.0.0 指南

## 📦 Windows 版本打包

由于项目在 WSL 中开发，需要在 Windows 环境下打包 .exe：

### 方法 1：在 Windows 中打包（推荐）

1. **在 Windows PowerShell 或 CMD 中运行**：

```powershell
# 进入项目目录（通过 WSL 路径）
cd \\wsl$\Ubuntu\home\tealina\QQNT_Export

# 创建 Windows 虚拟环境
python -m venv venv-windows

# 激活虚拟环境
venv-windows\Scripts\activate

# 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 打包
pyinstaller --clean QQNT_Export.spec

# 打包完成后，exe 文件在 dist\QQNT_Export.exe
```

2. **创建发布包**：

```powershell
# 在 dist 目录中创建发布文件夹
mkdir dist\QQNT_Export-v3.0.0
copy dist\QQNT_Export.exe dist\QQNT_Export-v3.0.0\
copy example.toml dist\QQNT_Export-v3.0.0\
copy README.md dist\QQNT_Export-v3.0.0\
copy LICENSE dist\QQNT_Export-v3.0.0\

# 压缩
# 使用 7-Zip 或 Windows 资源管理器压缩为 zip
```

### 方法 2：使用 Wine（不推荐，可能有兼容性问题）

在 WSL 中通过 Wine 运行 Windows Python：

```bash
# 安装 Wine
sudo apt install wine64

# 下载 Windows Python...
# （过程复杂，不推荐）
```

## 📋 发布清单

### 准备工作

- [x] 更新 README.md
- [x] 添加版本号标识
- [x] 测试所有功能
- [x] 创建 .spec 文件
- [ ] 在 Windows 上打包 .exe
- [ ] 测试 .exe 可用性

### 发布内容

创建 GitHub Release（v3.0.0），包含以下文件：

1. **QQNT_Export-v3.0.0-windows.zip**（Windows 预编译版）
   - QQNT_Export.exe
   - example.toml
   - README.md
   - LICENSE

2. **Source code (zip)**（自动生成）

3. **Source code (tar.gz)**（自动生成）

### Release 说明模板

```markdown
## QQNT Export v3.0.0 - 全面重构版

### 🎉 主要变化

- 🚀 全新架构：解析与导出完全解耦
- ✨ 支持 ChatLab v0.0.2 标准格式
- ⚡ 插件化导出器，易于扩展
- 📦 JSONL 流式导出，支持超大规模数据
- 🐛 修复图片和引用消息格式问题

### 📦 下载

- **Windows 用户**：下载 `QQNT_Export-v3.0.0-windows.zip`
- **其他系统**：下载源码并参考 README.md 运行

### 🚀 快速开始

1. 解压 zip 文件
2. 编辑 `example.toml` 配置数据库路径
3. 运行：`QQNT_Export.exe example.toml`
4. 导出的文件在 `output/` 目录

### 📝 导出格式

- **chatlab_json**：适合中小型数据（<100万条）
- **chatlab_jsonl**：适合大规模数据（>100万条）

### 🔗 相关链接

- [ChatLab 格式规范](https://github.com/ChatLab/ChatLab)
- [使用文档](https://github.com/Tealina28/QQNT_Export/blob/dev/README.md)
- [问题反馈](https://github.com/Tealina28/QQNT_Export/issues)

### ⚠️ 注意事项

- 需要先使用工具解密 QQ 数据库
- 导出过程需要一定时间，请耐心等待
- 大规模数据推荐使用 chatlab_jsonl 格式

### 🙏 致谢

感谢所有贡献者和测试用户！

---

**完整更新日志**：见下方 CHANGELOG
```

## 🏷️ Git 标签

发布前打标签：

```bash
git tag -a v3.0.0 -m "Release v3.0.0 - 全面重构版"
git push origin v3.0.0
```

## ✅ 发布后检查

- [ ] 测试 Windows exe 可正常运行
- [ ] 验证配置文件格式正确
- [ ] 检查导出结果符合 ChatLab 规范
- [ ] 更新项目 Wiki（如有）
- [ ] 在 Discussions 发布公告

## 📞 技术支持

如遇到问题：
1. 先查看 README.md 文档
2. 检查 GitHub Issues 是否有类似问题
3. 在 Discussions 提问
4. 提交新的 Issue
