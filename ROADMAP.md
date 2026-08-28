# 私有图书馆 private_library · 后续工作计划与竞品对标

> 整理时间：2026-08-28
> 当前状态：OCR 重抽**已暂停**——实测 ~4538 本扫描版 PDF 多为**超大尺寸扫描图像**（fitz 渲染即报 `Overly large image`，tesseract 单维上限 32767px 亦无法处理），现有 fitz+tesseract 工具链直接抽取收益≈0%，需专项方案（降分辨率渲染 / 换引擎）另行评估；全量正文已落库 10445 本（text_extracted=1），其余回落空壳；库已备份至 E 盘；tesseract+chi_sim 本机已装好（已复制至 F 盘项目目录 `tools/tesseract_ocr` 以适配沙箱）。OCR 抽取代码已健全（F 盘探测 + F 盘临时文件 + 超大页降 dpi），待书源问题解决即可启用。

---

## 一、项目现状快照

| 维度 | 现状 |
|---|---|
| 代码形态 | 单文件 `Private_Lib.py`，**纯 Python 标准库、零第三方依赖**可运行（Ollama 走 urllib） |
| 规模 | 15074 本书 + 2398 个音视频；库文件 24.4GB（含 10445 本内嵌全文） |
| AI 能力 | 本地 Ollama（qwen2.5:7b）做 AI 分类 / 摘要；**引用模式**存储（0 额外占用） |
| 阅读 | PDF.js 浏览器读 PDF；EPUB 服务端 zipfile 直读（目录/章节/字号/进度续读，零依赖、手机可读）；SumatraPDF 仅作可选桌面「外部阅读」 |
| 元数据缺口 | 简介 0.5%、出版社 2.9%、ISBN 1.8%、语言 10.9%（在线补全 = 头号 P0） |
| 知识图谱 | 尚未做（无实体/关系抽取层） |
| 备份 | 仅手动 1 份（E 盘，已 integrity_check） |

---

## 二、GitHub 竞品对标矩阵（2026-08 实测）

| 产品 | 技术栈 | 热度 | 在线元数据 | 浏览器阅读器 | 多用户 | AI 能力 | 知识图谱 | 设备同步 |
|---|---|---|---|---|---|---|---|---|
| **BookLore** | Java/Angular | ~842★ | ✅ 多源(Google/Amazon/OL/Goodreads) | ✅ EPUB/PDF/漫画 | ✅ 权限+OIDC | ❌ 无 AI 摘要 | ❌ | Kobo/KOReader/OPDS |
| **Calibre-Web-Automated** | Python | ~4.8k★ | ✅ 自动抓取+格式转换 | ✅ | ✅ | ❌ | ❌ | Send-to-Kindle/OPDS |
| **Talebook**（国产） | Calibre 核 | ~5.6k★ | ✅ +AI 元数据 | ✅ candle-reader(EPUB/PDF/MOBI/AZW3) | ✅ SSO | ✅ AI 元数据 | ❌ | Kindle/OPDS |
| **Kavita** | .NET | 活跃 | ✅ 漫画源(ComicVine 等) | ✅ 全格式 | ✅ | ❌ | ❌ | OPDS |
| **KapitelShelf** | .NET/React | 新(254 commit) | ✅ OpenLibrary/Amazon | ✅ | ✅ | ✅ Ollama 生成标签/分类 | ❌ | OPDS(规划) |
| **DeepRead** | JS | ~90★ | ❌ | ❌ | ❌ | ✅ Gemini 书籍知识图谱 | ✅ 实体/关系→Obsidian | ❌ |
| **karpathy/reader3** | Python | ~3.7k★ | ❌ | ✅ | ❌ | ✅ LLM 辅助阅读 | ❌ | ❌ |
| **本项目 private_library** | **Python stdlib** | 自托管 | ⚠️ 缺失率极高 | ✅ EPUB 直读(zipfile) | ❌ 单机 | ✅ Ollama 分类/摘要 | 🔜 规划中 | ❌ |

---

## 三、差距分析：护城河 vs 短板

### 🟢 护城河（竞品不全有，本项目的差异化优势）
1. **零依赖单文件**：纯 stdlib 可跑，部署门槛最低（BookLore 要 Java+MariaDB，Kavita 要 .NET，Calibre 系要 Calibre 本体）。
2. **引用模式（0 额外占用）**：BookLore/Calibre/Talebook 都"复制进库"，本项目只存索引/元数据，原文件原地引用——适合大库（15074 本）省空间。
3. **本地 AI 自托管（Ollama）**：不依赖任何云端 API（DeepRead 依赖 Gemini、有泄露/费用风险）；分类/摘要全本地。
4. **知识图谱层（规划）**：计划本地 Ollama 抽取实体关系 → Obsidian Vault B，与 DeepRead 思路同但**全程本地**，是三位一体护城河的最后一块。

### 🔴 短板（竞品领先，需补齐）
1. **在线元数据补全**：简介/出版社/ISBN/语言缺失率极高；BookLore/Talebook/Calibre-Web-Automated/KapitelShelf 均自动抓取。→ **P0**
2. **存储治理**：24GB 主库内嵌全文，备份慢；应剥离 `text_content`。→ **P1**
3. **自动备份**：仅手动 1 份；缺定时备份脚本。→ **P1**
4. **知识图谱可视化 + 阅读笔记 UI + 响应式/暗色**：竞品均有；本项目待做。→ **P2**
5. **OPDS / 设备同步**：个人库价值有限（可选）。→ **P3**

> ✅ **EPUB 阅读已具备**（`61fc7bb`，2026-08 重写）：`/read` 对 epub 返回浏览器内章节阅读器（目录/上章/下章/字号/进度续读），后端 `zipfile` 解包直读、零第三方依赖、手机/平板局域网可读；SumatraPDF 仅作可选「外部阅读」桌面按钮。故**不再列为短板**。

---

## 四、后续工作计划（优先级排序）

### 🔴 P0 — 数据补全（立即执行，价值最高）
| # | 任务 | 做法 | 对标参照 | 依赖 |
|---|---|---|---|---|
| 1 | **在线元数据补全** | `urllib` 调 Open Library / Google Books 回填 简介/出版社/ISBN/语言（零新依赖，可后台续跑） | BookLore / Talebook / KapitelShelf | 无 |
| 2 | **AI 摘要修复** | 扫描版 OCR 专项方案落地后重跑 AI 摘要，修 ~528 本"内容空白"假摘要（需真全文）；当前因扫描版为超大图像、OCR 收益≈0% 而**暂挂** | — | 扫描版 OCR 专项方案 |

### 🟡 P1 — 存储 + 备份
| # | 任务 | 做法 | 对标参照 | 依赖 |
|---|---|---|---|---|
| 3 | **存储治理** | `text_content` 从主库剥离到独立 `library_text.db`（或文件库），主库回 ~12GB | — | 无 |
| 4 | **自动备份** | 定时 `sqlite3.backup()` → 异盘 + `integrity_check` 校验（脚本化，替代手动 E 盘拷贝） | — | 无 |

> ✅ EPUB 浏览器阅读器已于 2026-08 完成（zipfile 服务端直读 + 章节阅读器），不再列入 P1。

### 🟢 P2 — 知识图谱 + 书架 + 笔记 + UI（差异化护城河）
| # | 任务 | 做法 | 对标参照 | 依赖 |
|---|---|---|---|---|
| 6 | **知识图谱层** | 本地 Ollama 抽取实体/关系 → Obsidian Vault B；加力导向图可视化 | DeepRead（但全程本地） | 真全文就绪 |
| 7 | **书架规则扩维** | 规则化智能书架：按主题/难度/标签动态生成（Magic Shelves 思路） | BookLore Magic Shelves | 无 |
| 8 | **阅读笔记 UI** | reading_notes 表已有，做可视化笔记/高亮界面 | BookLore Private Notes | 无 |
| 9 | **UI 响应式/暗色** | 移动端适配 + 暗色主题 | Talebook 6 主题明暗 | 无 |

### ⚪ P3 — 可选增强（个人库价值有限，按需）
| # | 任务 | 对标参照 |
|---|---|---|
| 10 | **OPDS 输出** | 让 KyBooks/KOReader 直连（纯 stdlib 可加，轻量） |
| 11 | **多用户/权限** | BookLore 强项，个人库暂不做 |
| 12 | **Kindle/设备推送** | Calibre-Web/Talebook，按需 |

---

## 五、差异化护城河定位（保持，不盲目跟风）

**不要**去卷 BookLore 的"多用户 + Kobo 同步 + 社交"——那是家庭/小团队场景，且要重型栈。
**要守住**的四点别人不全有的组合：
1. 本地 AI（Ollama 自托管，零云端泄露）
2. 引用模式（0 额外占用，适配大库）
3. 零依赖单文件（最低部署门槛）
4. 知识图谱层（本地抽取 → Obsidian，P2 落地后形成"本地三位一体"）

这四点叠加 = BookLore（无 AI）/ DeepRead（依赖云端）/ Calibre（复制进库）都给不了的"隐私 + 大库 + AI + 图谱"组合。
