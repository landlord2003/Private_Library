# CHANGELOG — 我的私有图书馆 (Private_Lib)

记录 `Private_Lib.py` 的重大改动，按时间倒序。换电脑 `git pull` 后看本文件即可知道改了啥。

---

## [2026-08-27] 工具中心增强 + 元数据根因诊断 + 后续改进路线图

### 🟢 近期已交付（commit `fb58968` → `7940acf`）
- **🔧 kg_build NUL 崩溃修复**：剔除书名/作者中的 NUL 控制字符（`ord(ch)>=32` 过滤 + `content.replace("\x00","")`），已跑完 15074 本（kg_l1 done=15074）。
- **🚀 双击 restart.bat 闪退修复**：根因是 .bat 硬编码中文路径「吴自强」被 GBK 解码成乱码触发语法错误；改用 `%USERPROFILE%` + 纯 ASCII 重写，双击/debug 均正常。
- **📐 书名规则化对比表**：工具中心新增 `?p=title-norm` 页，展示「原始书名 → 规则化书名 → 状态」对比表 + 重算写回（单连接批量事务，~12s / 15074 本）。
- **📊 统计页 + 书名采纳**：新增 `?p=stats`（规模 / 字段覆盖率 / 工具进度）；书名规则化每页增加 勾选 / 全选本页 / 采纳为正式书名（`POST /api/title-norm/adopt`）。
- **🌐 元数据源换 Open Library**：`libtools_common.fetch_online_metadata` 原把 OL 锁在 `LIB_PROXY` 检查后 → 全走 Douban → 主机也全量 403。`meta_complete.py` 改 **OL 直连优先（免代理、境外站）→ Google Books → Douban 代理兜底**，`meta.log` 不再被全标 skip。
- **🔥 摘要修复改全量**：UI 默认 `lim=20000` + 「🔥全量修复」按钮 + 待修数；`/api/summary-fix/pending` 暴露 `{pending, has_text, no_text}`，不再因默认 limit=50 只修 16/550。

### 🔍 元数据补全度诊断（影响评估）
当前库 15074 本，关键字段覆盖率：

| 字段 | 覆盖率 | 备注 |
|---|---|---|
| 封面 cover | 99.5% | 已基本解决 |
| 简介 desc | 99.9% | **含 528 条「假摘要」**（AI 摘要回填占位，非真作者简介） |
| 出版社 publisher | 22.7% | 偏低 |
| ISBN | 21.1% | 偏低 |
| 语言 lang | 30.6% | 偏低 |
| 正文全文 text_content | ~0% | **致命缺口：当前几乎无正文可抽取** |

摘要修复待修：`{pending:528, has_text:35, no_text:493}` —— 528 条里仅 35 条有正文可修，493 条无正文只能造占位。

**影响链**：
1. 检索 / 分类语料稀疏 → AI 分类、摘要质量受限；
2. 知识图谱层（P2-D 方案已定）抽取语料不足 → 图谱稀疏、关系偏少；
3. 封面 / ISBN 关联弱 → 无法用 ISBN 反查权威书目、跨库去重；
4. 引用 / 导出 BibTeX 字段缺失，引用管理信息不全。

**结论**：元数据补不全的**根本病根是「正文全文缺失（~0%）」**——没有正文，AI 摘要只能填占位，图谱只能抽版权页零碎信息。补在线元数据只是治标，**补正文才是治本**。

### 🗺️ 后续改进路线图（P0 → P3）

#### P0（根因 · 必做）— 文本提取回归
- 集成 **OCR（PyMuPDF / 调起 calibre）**：PDF 抽文本 + 扫描页 OCR；EPUB 已可 `zipfile` 解包取 XHTML 正文。
- 目标：把 `text_content` 覆盖率从 ~0% 拉到可用水位（目标 ≥ 70%），这是假摘要 & 稀疏图谱的唯一病根。
- 断点续跑 + 单本重试，复用现有 `_task_status` 异步模式。

#### P1 — 多源元数据融合
- Open Library / Google Books / Douban(代理) 三家并发查，按 `metadata_conf` 置信度加权回填空字段；
- 用 ISBN 反查权威书目，校正作者 / 出版社 / 出版年 / 语言；
- 已有 `metadata_source / metadata_conf` 列，扩为三源融合即可。

#### P2 — 封面 / ISBN 交叉补全 + 跨书关联
- 用 OL covers API 补剩余 0.5% 封面（当前 99.5% 已高）；
- 按（书名 + 作者）归一聚类 → 跨格式 / 跨源去重与合并展示。

#### P3 — 编辑 UI 收尾
- 书名采纳已上线；补 出版社 / 语言 / 分类 的详情页内联编辑；
- 修复后清掉 528 条假摘要，改用「有正文才回填」硬规则，杜绝占位。

> 优先级依据：先 **P0（正文）** 打开语料天花板，再 **P1** 多源融合精确化元数据，**P2 / P3** 为体验与治理收尾。知识图谱层（P2-D）建议在 P0 落地、语料变厚后再全量跑。

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
