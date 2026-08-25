# 📚 我的私有图书馆 (Private Library)

个人电子书 / 媒体库管理系统。**单文件 `Private_Lib.py`，纯 Python 标准库，零第三方依赖**，本地优先、离线可用。本地 Ollama 提供 AI 分类 / 摘要 / 元数据补全。

## ✨ 特性
- **多格式支持**：PDF / EPUB / MOBI / AZW3 / TXT / RAR / ZIP
  - PDF：浏览器内 PDF.js 阅读
  - EPUB：服务端解包章节直读（目录 / 翻页 / 字号 / 进度续读）
  - 压缩包：列表内文档并点开阅读（ZIP 免装即用；RAR/7z 需 7-Zip）
- **本地 AI**（Ollama `qwen2.5`）：自动分类、AI 摘要、在线元数据补全（可开关）
- **智能书架**：规则化筛选，支持 `author / tags / year` 维度
- **阅读笔记**：每书笔记 + 全局汇总页（`?p=notes`）
- **暗色模式** + **响应式布局**（自适应不同宽度屏幕）
- **引用模式存储**：0 额外占用，直接引用原文件
- **媒体库**：Whisper 转录 + AI 摘要

## 🚀 快速启动
```bat
cd F:\my-library
python Private_Lib.py          :: 默认 127.0.0.1:8000
```
或局域网访问 + 开启在线元数据补全：
```bat
set LIB_HOST=0.0.0.0
set LIB_METADATA_ONLINE=1
start.bat
```
浏览器打开 `http://localhost:8000`。

## 🔧 外部依赖（可选，缺失即降级）
| 依赖 | 用途 | 缺失时 |
|------|------|--------|
| **Ollama** | 本地 AI 分类 / 摘要 / 元数据 | 这些功能不可用，其余照常 |
| **7-Zip** | RAR / 7z 压缩包内读 | 仅 ZIP 可免装直读，RAR/7z 提示去装 |
| **SumatraPDF** | 桌面端「外部阅读」PDF | 可选，浏览器内读不受影响 |

## 💾 数据 & 隐私
- 库文件：`data/library.db`（已 gitignore，**不入库**）
- **离线优先**：看书 / 笔记零网络；仅「补全元数据」那一步需代理出网，结果落本地 DB。

## 📁 目录结构
```
Private_Lib.py           主程序（单文件、零依赖）
start.bat / backup.bat   启动 / 热备脚本
epubjs/                  EPUB 阅读器静态资源
pdfjs/                   PDF 阅读器静态资源
data/library.db          数据库（不入库）
p2-d-knowledge-graph-plan.md  知识图谱层方案
CHANGELOG.md             本文件改动记录
```

## 📄 文档
- `CHANGELOG.md` — 改动流水
- `p2-d-knowledge-graph-plan.md` — P2-D 知识图谱层实施方案
- `storage-governance-report.md` — 存储治理报告
- `metadata-plan.md` — 在线元数据补全方案
