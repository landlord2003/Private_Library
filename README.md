# 个人电子图书馆 — 部署指南

## 🚀 部署到移动硬盘（推荐）

### 为什么部署在移动硬盘？

- 🔌 **即插即用**：插到任何电脑，双击 `start.bat` 就能用
- 💾 **不占电脑空间**：C 盘 D 盘 0 占用
- 📦 **数据随身带**：书、数据库、封面全在硬盘里
- 🔒 **物理隔离**：拔掉硬盘，数据完全离线
- 💪 **无大小限制**：硬盘多大就能存多少
- 🔄 **备份简单**：复制整个文件夹到另一块硬盘即可

### 步骤

1. 将 `personal-ebook-library` 文件夹复制到移动硬盘，例如 `H:\my-library\`
2. 双击 `start.bat`（或命令行运行 `python server.py`）
3. 浏览器打开 **http://localhost:8000**

```
移动硬盘 H:\my-library\
├── backend\          # Python 后端
├── frontend\build\   # 前端（已构建好）
├── data\             # 数据库和导入的文件（自动创建）
├── server.py         # 服务入口
├── start.bat         # 一键启动
├── start.sh          # Mac/Linux 启动脚本
├── requirements.txt  # Python 依赖
└── README.md
```

---

## 📋 前置条件

1. **Python 3.11+** — https://www.python.org/downloads/
2. 安装依赖：`pip install -r requirements.txt`

可选：
- **FFmpeg** — 音视频元数据提取（https://ffmpeg.org/）
- **Ollama** — 本地 AI 摘要（https://ollama.com/）
- **Whisper** — 语音转文字：`pip install openai-whisper`

---

## ⚙️ 配置

在项目目录创建 `library_config.json`：

```json
{
  "data_dir": "H:\\my-library-data",
  "storage_mode": "copy"
}
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `data_dir` | 数据存储位置 | `./data`（项目目录下） |
| `storage_mode` | `"copy"` 复制到库 / `"reference"` 引用原路径 | `"copy"` |

也可以用环境变量：
```cmd
set LIBRARY_DATA_DIR=H:\my-books
python server.py
```

---

## 🔄 备份

整个图书馆就是一个文件夹，备份极其简单：

```
源盘 H:\my-library\  ──复制──→  备份盘 G:\backup\my-library\
```

建议定期备份 `data\library.db`（数据库）和 `data\books\`（书籍文件）。

---

## 🔧 存储模式说明

| 模式 | 行为 | 适合场景 |
|------|------|---------|
| `copy`（默认） | 导入时复制文件到 `data/` | 文件需要随图书馆一起移动 |
| `reference` | 只记录原路径，不复制 | 文件已在移动硬盘上，不想重复占用空间 |

> ⚠️ reference 模式下，如果原文件被移动或删除，图书馆将无法访问。

---

## ❓ 常见问题

**Q: 换了一台电脑，双击 start.bat 没反应？**
需要在新电脑上也安装 Python 和依赖。

**Q: 数据库文件越来越大？**
正常。几千本书的数据库约几十 MB。可以定期用 SQLite 的 VACUUM 命令压缩。

**Q: 想在其他电脑上访问？**
启动时加参数：`python server.py --host 0.0.0.0`，然后通过 `http://你的IP:8000` 访问。
