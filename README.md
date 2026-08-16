# 📚 Private Lib — 个人电子图书馆

自托管、隐私优先的电子书管理系统。纯 Python 标准库实现，**零第三方依赖**即可运行。通过本地 [Ollama](https://ollama.com) 提供 AI 分类、摘要能力，数据不出本机。

> Self-hosted, privacy-first ebook library. Pure Python stdlib — **zero pip install** to run. AI-powered classification and summarization via local Ollama. Your data never leaves your machine.

---

## ✨ 功能 Features

| 功能 | 说明 |
|------|------|
| 📖 在线阅读 | PDF / EPUB 直接在浏览器中阅读 |
| 🤖 AI 分类 | 调用本地 Ollama 自动分类 + 打标签 |
| 📝 AI 摘要 | 自动生成书籍摘要（一句话总结 / 核心观点 / 难度评级） |
| 📄 文本提取 | 从 PDF / EPUB / MOBI / TXT 中提取全文，供 AI 处理 |
| 🖼️ 封面提取 | 自动从电子书中提取封面图片 |
| 🔍 全文搜索 | SQLite FTS5 全文索引（按需创建） |
| 🗂️ 去重导入 | SHA256 文件级去重，网页上传时自动检测 |
| 🎧 媒体库 | 音频 / 视频管理 + Whisper 语音转文字 + AI 摘要 |
| 📱 响应式 Web | 手机 / 平板 / 电脑均可访问 |
| 💾 引用模式 | 支持引用存储（0 额外磁盘占用） |

---

## 🚀 快速开始 Quick Start

### 前置条件 Prerequisites

- **Python 3.10+**（纯标准库，无需 pip install）
- **[Ollama](https://ollama.com)** + 任意模型（推荐 `qwen2.5:7b`）— 用于 AI 分类 / 摘要

### 启动 Start

```bash
# Windows
start.bat

# Mac / Linux
python3 Private_Lib.py

# 或直接运行
python Private_Lib.py
```

浏览器打开 **http://localhost:8000**

### AI 模型配置

安装 Ollama 后拉取模型：

```bash
ollama pull qwen2.5:7b
```

确保 Ollama 在 `http://localhost:11434` 运行即可，无需额外配置。

---

## ⚙️ 配置 Configuration

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIB_HOST` | 监听地址 | `127.0.0.1`（仅本机） |
| `LIB_PORT` | 监听端口 | `8000` |
| `OLLAMA_URL` | Ollama API 地址 | `http://localhost:11434` |

> 🔒 默认仅监听 `127.0.0.1`。如需局域网访问：`set LIB_HOST=0.0.0.0`

### library_config.json

```json
{
  "storage_mode": "copy",
  "scan_directories": []
}
```

| 配置项 | 说明 | 可选值 |
|--------|------|--------|
| `storage_mode` | 导入模式 | `copy`（复制到库）/ `reference`（引用原路径，0 额外占用） |
| `scan_directories` | 扫描导入目录列表 | 路径数组 |

---

## 📁 项目结构

```
my-library/
├── Private_Lib.py          # 主程序（单文件，含全部 Web UI）
├── start.bat               # Windows 一键启动
├── start.sh                # Mac/Linux 启动脚本
├── backup.bat              # 备份工具
├── library_config.json      # 配置文件
├── requirements.txt        # 可选依赖（AI / 封面提取 / 文本解析）
├── LICENSE
├── data/                   # 数据目录（不入 Git）
│   ├── library.db          # SQLite 数据库
│   └── books/              # 书籍文件 + 封面
└── scripts/                # 批量工具脚本
    ├── batch_import.py     # 批量导入
    ├── batch_extract_covers.py  # 批量提取封面（多进程）
    ├── extract_text.py     # 批量提取文本
    ├── auto_classify.py    # 自动分类（循环调用 API）
    ├── auto_summary.py     # 自动摘要（循环调用 API）
    └── ...
```

---

## 🔧 可选依赖 Optional Dependencies

主程序 `Private_Lib.py` **不依赖任何第三方库**。以下依赖仅用于工具脚本或增强功能：

```bash
pip install -r requirements.txt
```

| 依赖 | 用途 |
|------|------|
| PyMuPDF | PDF 封面渲染 / 文本提取 |
| EbookLib | EPUB 深度解析 |
| mobi | MOBI 格式解析 |
| Pillow | 图片处理 |
| FFmpeg | 音视频元数据（需单独安装） |
| faster-whisper | 语音转文字（媒体库） |

---

## 🎯 设计理念 Design Choices

### 为什么是单文件？

`Private_Lib.py` 将 Web 服务器 + HTML/CSS/JS 前端 + 后端逻辑全部写在一个 Python 文件里。这是**有意为之**的设计：

- **零部署门槛**：一个文件 + Python，双击即用
- **零依赖**：纯标准库，任何 Python 3.10+ 环境直接运行
- **易迁移**：拷到 U 盘 / 移动硬盘，插上任何电脑就能用
- **易维护**：不需要理解前后端分离架构，一个文件看懂全部

> Why a single file? Zero-friction deployment. One file + Python = done. No build step, no node_modules, no virtual env. Copy it to a USB drive and run it on any machine.

---

## ❓ FAQ

**Q: 换了电脑盘符变了怎么办？**
启动时自动检测并修正数据库中的路径，无需手动处理。

**Q: 数据库越来越大？**
正常。可用 `sqlite3 data/library.db "VACUUM"` 压缩。

**Q: 支持哪些格式？**
PDF、EPUB、MOBI、AZW3、TXT、RAR/ZIP（压缩包内自动识别）。

**Q: AI 分类 / 摘要按钮没反应？**
检查 Ollama 是否在运行：`curl http://localhost:11434/api/tags`

---

## 📜 License

[MIT](./LICENSE)
