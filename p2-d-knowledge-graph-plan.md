# P2-D 知识图谱层 实施方案

> 状态：方案阶段（未实现）。待「在线元数据补全」在那台电脑验证后，再动手实现。
> 定位：本地 AI + 引用模式 + 知识图谱层 = 差异化护城河（BookLore / DeepRead 都没有的本地三位一体）。

## 0. 已锁定决策（2026-08-29，用户拍板）

| 项 | 决策 | 理由 |
|---|---|---|
| 抽取模型 | **qwen2.5:14b** | KG 为高价值护城河，14b 关系/实体抽取更准；本机已装 14b |
| 批量范围 | **仅含 summary 的书**（约 15000 本） | 语料稳、质量高；无摘要书跳过不浪费算力 |
| OCR 前置 | **先解锁 Unlimited-OCR，再跑 B** | OCR 跑通后 `book_text` 覆盖提升，正文维度语料更全；**解锁工作由另一独立任务负责，本会话不推进**（见下） |

约束：B 需在 `library.db` 建 `graph_node/graph_edge` 并批量写，**与后台元数据补齐批次同库冲突，须等批次跑完再实现**（同存储治理）。
> **OCR 解锁状态（2026-08-29 用户指示）**：Unlimited-OCR 解锁由另一台/人工任务独立进行，完成后会**重写一份交接报告**，届时由本会话接手。当前会话**不主动推进 OCR 解锁**，亦不引 MinerU。B 仍保持"先 OCR 后 B"顺序，等新版交接报告到位再排期。

## 1. 目标

为每本书构建**本地知识图谱**：从正文/摘要中抽取**实体**（人物、概念、组织、地点、技术、事件、方法）与**关系**，存入数据库；详情页新增「🕸 图谱」标签页用原生 SVG/Canvas 力导向图渲染；支持**导出 Obsidian Markdown**（双链 + dataview 友好），直投现有 Vault B。

价值：
- 把「一本书」从扁平列表变成「可漫游的知识网络」；
- 跨书实体聚合（同名实体出现在哪些书）→ 个人知识体系的「发现引擎」；
- 全程**本地 Ollama 抽取**，零云端泄露，契合项目隐私优先定位。

## 2. 数据模型（零第三方依赖，纯 SQLite）

新增表 `book_graph`（或拆 nodes/edges 两表，下面用单表+类型列简化）：

```sql
CREATE TABLE IF NOT EXISTS graph_node (
    id       TEXT PRIMARY KEY,          -- book_id + '|' + label + '|' + type
    book_id  TEXT NOT NULL,
    label    TEXT NOT NULL,
    type     TEXT NOT NULL,             -- person/concept/org/place/tech/event/method
    freq     INTEGER DEFAULT 1,         -- 在书中出现频次（决定节点大小）
    salience REAL DEFAULT 0            -- 显著度 0~1（模型给或按频次归一）
);
CREATE TABLE IF NOT EXISTS graph_edge (
    id       TEXT PRIMARY KEY,
    book_id  TEXT NOT NULL,
    source   TEXT NOT NULL,             -- node label
    target   TEXT NOT NULL,             -- node label
    relation TEXT NOT NULL,             -- 提及/属于/对抗/合作/因果/引用/例证…
    weight   REAL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_gn_book ON graph_node(book_id);
CREATE INDEX IF NOT EXISTS idx_ge_book ON graph_edge(book_id);
```

- 抽取**幂等**：重跑某书时先 `DELETE FROM graph_node/edge WHERE book_id=?` 再写。
- 类型体系（types）：`person 人物 / concept 概念 / org 组织 / place 地点 / tech 技术 / event 事件 / method 方法`。
- 关系（relations）：`提及 mentions / 属于 belongs_to / 对抗 against / 合作 cooperates / 因果 causes / 引用 cites / 例证 exemplifies`。

## 3. 抽取流程（本地 Ollama，qwen2.5:7b / 14b）

复用现有 `_task_status` 异步进度模式与 `book_text` 副表。

### 3.1 单本 `run_graph_async(book_id)`
1. 取语料优先级：`summary`（AI 摘要）> `book_text.text_content`（正文）> `description`（简介）。
   - 很多书正文为空 → **优先用 AI 摘要**；这正是「先补全元数据 / 跑摘要」再跑图谱更优的原因。
2. 构造 prompt：要求模型输出**严格 JSON** `{ "entities":[{label,type,freq}], "relations":[{source,target,relation}] }`，并约束类型/关系枚举。
3. 调本地 Ollama `http://localhost:11434/api/generate`（已用于分类/摘要，复用同一客户端封装）。
4. 解析 JSON → UPSERT 进 `graph_node` / `graph_edge`。
5. 健壮性：
   - Ollama 不可用 / 超时 → 标记 `graph_status=failed`，跳过不崩；
   - JSON 解析失败 → 重试一次或记录 raw 供人工看；
   - 空结果 → 标记 `graph_status=empty`。

### 3.2 批量 `run_graph_batch_async(limit=None, only_with_summary=True)`
- 遍历全库（或仅「有摘要」的书，质量更好），逐本调 3.1，更新 `_task_status['graph']` 进度。
- 与现有 `run_classify_async` / `run_summarize_async` / `run_metadata_async` 同构，保持一致的心智模型。

### 3.3 触发入口（前端）
- 详情页「🕸 图谱」tab 内放「⚙ 生成/重建图谱」按钮 → `POST /api/books/<id>/graph`（`action:build`）。
- 书库页/NAV 放「批量生成图谱」入口（可选，分阶段开放）。

## 4. 前端渲染（原生 SVG/Canvas，不引重型库）

### 4.1 详情页「🕸 图谱」标签页
- 数据接口 `GET /api/books/<id>/graph` 返回 `{nodes, edges}`。
- 渲染：自写**轻量力导向布局**（或 vendored 迷你库，如 d3-force 的精简本地版；优先自写以免破坏零依赖）。
  - 节点按 `type` 着色、半径按 `salience/freq`；
  - 边按 `relation` 用不同线型/透明度；
  - 悬停高亮邻居、点击弹出实体详情（类型、频次、相关关系）。
- 空状态友好提示：「本书暂无图谱，点「生成图谱」试试（需本地 Ollama）」。

### 4.2 跨书聚合页 `?p=graph`
- 聚合所有书的节点，**同名实体合并**，显示「该实体出现在哪些书」；
- 支持按类型筛选、按显著度排序；
- 点击实体 → 列出相关书籍链接。
- 这是个人知识库的「发现」入口，价值最高。

## 5. 导出 Obsidian

- 每本书导出 `图谱/<书名>.md`：
  - YAML frontmatter：`tags`、`category`、`entities`（实体列表）；
  - 正文：关系列表用 `[[实体A]] - 关系 - [[实体B]]` 形成**双链**；
  - 复用现有 Obsidian 导出习惯（Vault B，`D:\WorkBuddy\Claw\landlord知识库` 或 `E:\Workbuddy\...`）。
- 跨书聚合可导出 `图谱/索引.md`（dataview 友好），便于在 Obsidian 里反查。

## 6. 试点路线（先单本验证，再放开）

1. **单本试点**：选 1 本高质量书（摘要完整），手工跑 `run_graph_async`，检查抽取质量（实体是否准、关系是否合理）。
2. **调 prompt + 类型/关系体系**：根据试点结果收紧枚举、加 few-shot 示例。
3. **开放单本按钮**：详情页「生成图谱」可用。
4. **开放批量 + 跨书聚合页**：全库/筛选集批量生成，上线 `?p=graph`。
5. **接 Obsidian 导出**：一键导出当前书 / 全库图谱。

## 7. 依赖与风险

| 项 | 说明 | 缓解 |
|---|---|---|
| Ollama 本地模型 | 需 `qwen2.5:7b` 可用 | 不可用时降级跳过，不崩 |
| 语料质量 | 很多书正文/摘要空 | 优先摘要；**今晚先在另一台电脑验证「在线元数据补全」→ 补全简介/出版社后再全面跑图谱，抽取语料更丰富** |
| 抽取幻觉 | 模型可能造关系 | 限定枚举 + 只连已抽取实体，避免凭空关系 |
| 性能 | 15074 本全跑耗时 | 分批 + 仅对有摘要的书跑；可断点续跑 |
| 依赖 | 力导向布局 | 自写 canvas/SVG，不引入重型库，保持零依赖 |

## 8. 与现有架构契合度

- **零新增第三方依赖**：力导向用自写 canvas/SVG；若用库则 vendored 本地（如 `epubjs/` 同款做法）。
- 复用：`book_text` 副表（语料）、`_task_status` 异步模式、详情页多 tab 结构、Obsidian 导出习惯。
- 不改动已有 P2-A/B/C 与书库/阅读逻辑，独立增量。

---
**结论**：方案自洽、风险可控。建议**今晚在那台电脑验证「在线元数据补全」后**，再按第 6 节路线实现——语料越完整，图谱质量越高。
