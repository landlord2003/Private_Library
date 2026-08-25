# CHANGELOG — 我的私有图书馆 (Private_Lib)

记录 `Private_Lib.py` 的重大改动，按时间倒序。换电脑 `git pull` 后看本文件即可知道改了啥。

---

## [2026-08-25] 单文件大改版（commit `61fc7bb`）

本次提交把近几日的多项改造一次性落地，覆盖阅读体验、界面、阅读器与存储治理。

### 🟢 新增 / 增强
- **📝 阅读笔记系统（P2-A）**
  - 每本书详情页底部「📝 阅读笔记」：写内容 + 可选填页码 → 保存。
  - 笔记**编辑按钮** ✏️：回填后保存变为「💾 更新笔记」。
  - **全部笔记汇总页** `?p=notes`：跨书列出全部笔记（书名/页码/时间/内容），带内容搜索；左侧导航新增「📝 笔记 (N)」入口。
  - 防 XSS：笔记渲染用 `textContent`，不执行注入内容。
- **🌙 暗色模式（P2-B）**：`[data-theme="dark"]` 覆盖层方案，不破坏原浅色 CSS；`localStorage` 记忆偏好。
- **📚 智能书架扩维（P2-C）**：`shelves` 表新增 `author / tags / year` 三个筛选维度，规则化筛选与保存链路全打通。
- **📐 页面响应式自适应**：桌面端 `nav` 用 `clamp()` 流体宽度、书卡网格 `auto-fill` 随屏宽自动铺满、超宽屏(≥1700px)限宽居中；移动端 2 列抽屉布局保持不动。两台不同宽度显示器表现一致。
- **📖 EPUB 服务端直读（替代 epub.js）**：新增 `/api/books/<id>/epub/info`、`/epub/chapter/<i>`、`/epub/asset/<path>` 路由；`/read` 对 epub 返回章节阅读页（目录/上章/下章/字号/进度续读）。标准库 `zipfile` 解包，**零第三方依赖、内容 100% 可见**。
- **🗜️ 压缩包读取健壮性**：
  - ZIP 改用标准库 `zipfile` 直读，**免装 7-Zip** 即可列出并阅读内文。
  - RAR / 7z 未装 7-Zip 时，阅读页显示友好提示（不再假显示「0 个文件」）。
- **🌐 在线元数据补全（功能化、可开关）**：`ENABLE_ONLINE_METADATA` 默认关（离线优先）。开启后 `run_metadata_async` 用 urllib 调 Open Library + Google Books（无需 key、自动读代理、超时即跳），仅填空字段、按相似度阈值写入并记 `metadata_source/metadata_conf`；导入末尾自动 kick。

### 🐛 修复
- **阅读笔记致命 bug**：`reading_notes` 表是旧 schema（`content/position/...`），`CREATE TABLE IF NOT EXISTS` 看到表已存在就跳过补列，导致 `no such column: note` 全部 500。改为检测 `note` 列缺失即 DROP+重建（当前 0 行，零损失）。✅ 增/删/改/查全链路验证通过。
- **启动卡顿根治**：`text_content`（每本全文，最大 20 万字符）从 `books` 主表**迁出到 `book_text` 副表**，`UPDATE books`（盘符路径修正/状态）从此只改窄行 → **启动秒级**（旧版曾卡 40 分钟）。
- **双服务冲突**：清理了同监听 8000 的两个 python 进程，重启单一实例。

### 🗂️ 治理 / 文档
- **存储治理**：删除 4 个 8/11 失控连刷的损坏 `.bak` 备份（各 ~15.5GB，sqlite malformed 无恢复价值），释放约 62GB。详见 `storage-governance-report.md`。
- **知识图谱方案（P2-D，仅方案未实现）**：`p2-d-knowledge-graph-plan.md`，设计 `graph_node/graph_edge` 两表 + 本地 Ollama 抽实体关系 + 详情页 SVG 图谱 + Obsidian 导出。
- **`.gitignore` 补 `startup_log.txt`**：防运行时日志入库（运行产物 `data/`、`.db*`、`.bak` 等早已忽略）。
- **`epubjs/`** 静态资源随仓库提交，保持自包含。

### ⚠️ 已知限制 / 待办
- **P2-D 知识图谱层尚未实现**（仅方案），建议先在另一台电脑验证「在线元数据补全」使语料更全后再做。
- **RAR / 7z 压缩包内读**需本机装 7-Zip（`C:\Program Files\7-Zip\7z.exe`），ZIP 已免装。
- **在线元数据补全**需北京网络走代理出网（Open Library / Google Books 为境外站），否则每本 5s 超时跳过。
- **当前零有效备份**：旧备份已清，建议用 `backup.bat` 新建一份 integrity_check 校验过的备份。

---

## [早前] 初始对标与架构确认
- 对标 GitHub `booklore` / `deepread`，确认差异化护城河：**本地 AI + 引用模式 + 零依赖 + 知识图谱层**。
- 确认当前主项目为单文件 `Private_Lib.py`（纯标准库、零第三方依赖），非早期 FastAPI/React 原型。
