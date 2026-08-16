# 📚 Private Lib — 个人电子图书馆

自托管、隐私优先的电子书管理系统。纯 Python 标准库实现，**零第三方依赖**即可运行。通过本地 [Ollama](https://ollama.com) 提供 AI 分类、摘要能力，数据不出本机。

> Self-hosted, privacy-first ebook library. Pure Python stdlib — **zero pip install** to run. AI-powered classification and summarization via local Ollama. Your data never leaves your machine.

---

## ✨ 功能 / Features

| 功能 | Description |
|------|-------------|
| 📖 在线阅读 | PDF / EPUB 直接在浏览器中阅读 — Read PDF / EPUB directly in browser |
| 🤖 AI 分类 | 调用本地 Ollama 自动分类 + 打标签 — Auto-classify & tag via local Ollama |
| 📝 AI 摘要 | 一句话总结 / 核心观点 / 难度评级 — Summaries: key points / difficulty rating |
| 📄 文本提取 | PDF / EPUB / MOBI / TXT 全文提取 — Full-text extraction from all formats |
| 🖼️ 封面提取 | 自动从电子书中提取封面 — Auto-extract cover images |
| 🔍 全文搜索 | SQLite FTS5 全文索引（按需创建）— SQLite FTS5 full-text search (on demand) |
| 🗂️ 去重导入 | SHA256 文件级去重 — SHA256 file-level deduplication on upload |
| 🎧 媒体库 | 音频 / 视频管理 + Whisper 转文字 + AI 摘要 — Media library with Whisper transcription + AI summary |
| 📱 移动访问 | 手机 / 平板通过局域网浏览器访问 — Mobile / tablet access via LAN browser |
| 💾 引用模式 | 引用存储（0 额外磁盘占用）— Reference mode (zero extra disk usage) |

---

## 🚀 快速开始 / Quick Start

### 前置条件 / Prerequisites

- **Python 3.10+**（纯标准库，无需 pip install / Pure stdlib, no pip install needed）
- **[Ollama](https://ollama.com)** + 任意模型（推荐 `qwen2.5:7b`）— 用于 AI 分类 / 摘要

### 启动 / Start

```bash
# Windows
start.bat

# Mac / Linux
python3 Private_Lib.py

# 或直接运行 / Or run directly
python Private_Lib.py
```

浏览器打开 / Open in browser: **http://localhost:8000**

### 📱 手机 / 平板访问 / Mobile Access

无需安装 App，手机/平板用浏览器即可访问。前提：设备与电脑在**同一 WiFi** 下。

> No app needed — just open in your mobile browser. Requirement: phone/tablet and computer on the **same WiFi**.

**Step 1 — 电脑端以局域网模式启动 / Start server in LAN mode:**

```bash
# Windows
set LIB_HOST=0.0.0.0
python Private_Lib.py

# Mac / Linux
LIB_HOST=0.0.0.0 python3 Private_Lib.py
```

启动后控制台会显示局域网地址（如 `192.168.1.100`）。

> The console will show your LAN IP (e.g. `192.168.1.100`).

**Step 2 — 手机浏览器打开 / Open on mobile browser:**

```
http://<电脑IP>:8000
```

**注意事项 / Notes:**

| 事项 | Note |
|------|------|
| 同一 WiFi | 手机和电脑必须连同一局域网 / Same LAN required |
| 电脑不能关 | 电脑是服务器，关机则不可访问 / Server must stay running |
| 防火墙 | Windows 首次弹窗点「允许」/ Click "Allow" on Windows firewall prompt |
| 外网访问 | 需配置端口转发或内网穿透 / Requires port forwarding or tunnel |

> 💡 **添加到主屏幕 / Add to Home Screen**: 手机浏览器 → 分享 → 添加到主屏幕，可像 App 一样全屏使用。

### AI 模型配置 / AI Model Setup

安装 Ollama 后拉取模型 / Install Ollama and pull a model:

```bash
ollama pull qwen2.5:7b
```

确保 Ollama 在 `http://localhost:11434` 运行即可。

> Ensure Ollama is running at `http://localhost:11434`. No extra config needed.

---

## ⚙️ 配置 / Configuration

### 环境变量 / Environment Variables

| 变量 / Variable | 说明 / Description | 默认值 / Default |
|------|------|--------|
| `LIB_HOST` | 监听地址 / Listen address | `127.0.0.1`（仅本机 / localhost only） |
| `LIB_PORT` | 监听端口 / Listen port | `8000` |
| `OLLAMA_URL` | Ollama API 地址 / Ollama API URL | `http://localhost:11434` |

> 🔒 默认仅监听 `127.0.0.1`。如需局域网访问：`set LIB_HOST=0.0.0.0`
>
> Default binds to `127.0.0.1` only. For LAN access: `set LIB_HOST=0.0.0.0`

### library_config.json

```json
{
  "storage_mode": "copy",
  "scan_directories": []
}
```

| 配置项 / Key | 说明 / Description | 可选值 / Options |
|--------|------|--------|
| `storage_mode` | 导入模式 / Import mode | `copy`（复制到库）/ `reference`（引用原路径，0 额外占用 / zero extra disk） |
| `scan_directories` | 扫描导入目录列表 / Directories to scan | 路径数组 / Array of paths |

---

## 📁 项目结构 / Project Structure

```
my-library/
├── Private_Lib.py          # 主程序（单文件，含全部 Web UI）— Main app (single file)
├── start.bat               # Windows 一键启动 — Windows launcher
├── start.sh                # Mac/Linux 启动脚本 — Mac/Linux launcher
├── backup.bat              # 备份工具 — Backup utility
├── library_config.json      # 配置文件 — Config file
├── requirements.txt        # 可选依赖 — Optional dependencies
├── LICENSE
├── data/                   # 数据目录（不入 Git）— Data dir (not in Git)
│   ├── library.db          # SQLite 数据库 — SQLite database
│   └── books/              # 书籍文件 + 封面 — Book files + covers
└── scripts/                # 批量工具脚本 — Batch utility scripts
    ├── batch_import.py     # 批量导入 — Batch import
    ├── batch_extract_covers.py  # 批量提取封面（多进程）— Batch cover extraction (multiprocess)
    ├── extract_text.py     # 批量提取文本 — Batch text extraction
    ├── auto_classify.py    # 自动分类 — Auto classification
    ├── auto_summary.py     # 自动摘要 — Auto summarization
    └── ...
```

---

## 🔧 可选依赖 / Optional Dependencies

主程序 `Private_Lib.py` **不依赖任何第三方库**。以下依赖仅用于工具脚本或增强功能：

> The main program `Private_Lib.py` has **zero third-party dependencies**. The following are only needed for utility scripts or enhanced features:

```bash
pip install -r requirements.txt
```

| 依赖 / Package | 用途 / Used For |
|------|------|
| PyMuPDF | PDF 封面渲染 / 文本提取 — PDF cover rendering / text extraction |
| EbookLib | EPUB 深度解析 — EPUB deep parsing |
| mobi | MOBI 格式解析 — MOBI format parsing |
| Pillow | 图片处理 — Image processing |
| FFmpeg | 音视频元数据（需单独安装）— A/V metadata (install separately) |
| faster-whisper | 语音转文字（媒体库）— Speech-to-text (media library) |

---

## 🎯 设计理念 / Design Choices

### 为什么是单文件？ / Why a single file?

`Private_Lib.py` 将 Web 服务器 + HTML/CSS/JS 前端 + 后端逻辑全部写在一个 Python 文件里。这是**有意为之**的设计：

> `Private_Lib.py` packs the web server, HTML/CSS/JS frontend, and backend logic into a single Python file. This is **by design**:

- **零部署门槛**：一个文件 + Python，双击即用 — Zero-friction: one file + Python, double-click to run
- **零依赖**：纯标准库，任何 Python 3.10+ 环境直接运行 — Zero deps: pure stdlib, runs on any Python 3.10+
- **易迁移**：拷到 U 盘 / 移动硬盘，插上任何电脑就能用 — Portable: copy to USB drive, run anywhere
- **易维护**：不需要理解前后端分离架构，一个文件看懂全部 — Maintainable: one file, full picture

---

## ❓ FAQ

**Q: 换了电脑盘符变了怎么办？**
启动时自动检测并修正数据库中的路径，无需手动处理。

> **Q: Changed drive letter?**
> Auto-detects and fixes paths in the database on startup. No manual action needed.

**Q: 数据库越来越大？**
正常。可用 `sqlite3 data/library.db "VACUUM"` 压缩。

> **Q: Database growing too large?**
> Normal. Compress with `sqlite3 data/library.db "VACUUM"`.

**Q: 支持哪些格式？**
PDF、EPUB、MOBI、AZW3、TXT、RAR/ZIP（压缩包内自动识别）。

> **Q: Supported formats?**
> PDF, EPUB, MOBI, AZW3, TXT, RAR/ZIP (auto-detected inside archives).

**Q: AI 分类 / 摘要按钮没反应？**
检查 Ollama 是否在运行：`curl http://localhost:11434/api/tags`

> **Q: AI classify / summarize buttons not working?**
> Check if Ollama is running: `curl http://localhost:11434/api/tags`

---

## 📜 License

[MIT](./LICENSE)
