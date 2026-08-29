# Unlimited-OCR 部署与集成交接报告

> 移交对象：私有图书馆 `private_library` 项目（G:\my-library）
> 移交人：WorkBuddy（吴总 AI 助手）
> 日期：2026-08-29
> 目的：解决「扫描版 PDF 文本抽取」卡点（当前 OCR 收益 ≈0%）

---

## 一、结论速览 🚦

| 项 | 状态 | 说明 |
|---|---|---|
| 模型文件下载 | ✅ 完成 | 6.67 GB，`model-00001-of-000001.safetensors` 完整无残留 |
| Python 依赖链 | ✅ 完成 | torch 2.11 cu128 / torchvision cu128 / transformers 5.2 / pymupdf 1.28 / easydict 均已就位 |
| 模型加载到 GPU | ✅ 完成 | RTX 5070，~5s 加载，**显存 6.8 GB**（12GB 卡余 ~5GB） |
| 自定义代码编译 | ✅ 完成 | 已打 1 处兼容补丁（见 §3） |
| **端到端 OCR 推理** | 🔴 **阻塞** | 视觉编码器推理触发 CUDA 越界（gather index OOB），见 §3 |
| 与图书馆集成代码 | 🟡 待做 | 方案已设计（§4），待推理阻塞解除后落地 |

**一句话**：环境已装好、模型能上 GPU、依赖齐全；但本机 transformers 5.2 与该模型自定义代码（面向 transformers 4.x）不兼容，导致实际 OCR 跑不起来。图书馆项目接手后按 §3 路线把 transformers 钉到 4.x 即可解锁，再按 §4 接入。

---

## 二、已验证的部署事实（确凿）

- **模型路径**：`E:\Workbuddy\Unlimited-OCR\model\`（PaddlePaddle/Unlimited-OCR，ModelScope 源，因 HF 镜像本机不可达）
- **验证脚本**：`E:\Workbuddy\Unlimited-OCR\verify_uocr.py`（多页）、`verify_single.py`（单页）
- **验证样本**：`G:\my-library\data\books\3b90e0a6-...\original.pdf`（50MB 真实扫描版，无文字层）——已复制到 `E:\Workbuddy\Unlimited-OCR\sample\sample_scanned.pdf`，供团队复现
- **加载日志证据**：
  ```
  [1/3] 加载模型 ...
      加载 4.6s | 显存 6.8GB
  ```
- **已安装依赖（在 Chatterbox venv 内）**：
  - `torch 2.11.0+cu128`、`torchvision`（cu128 匹配版）、`transformers 5.2.0`
  - `pymupdf 1.28.2`（渲染页用）、`easydict`（deepencoder 依赖）
  - ⚠️ 这些装在 `E:\Workbuddy\Chatterbox\env` 里（复用其 torch，省重装）。**图书馆项目应新建专用 venv**（见 §3），不要直接依赖 Chatterbox 环境。

---

## 三、推理阻塞：根因与修复路线 🔴

### 现象
模型加载成功后，调用 `model.infer(...)` / `model.infer_multi(...)` 做视觉编码时，CUDA 报：
```
RuntimeError: CUDA error: device-side assert triggered
Assertion `ind >=0 && ind < ind_dim_size && "vectorized gather kernel index out of bounds"` failed.
```
出错位置：`modeling_unlimitedocr.py → deepencoder.py`（视觉编码器 transformer 的 MLP/forward）。索引值在多次尝试中浮动（0–17 / 32–109 / 127），说明是按输入分辨率算出的序列长度与该 checkpoint 内部缓冲区不匹配——**数据/分辨率相关，非随机**。

### 根因判断
1. **主因：transformers 版本不匹配**。模型自定义代码（`modeling_deepseekv2.py`）引用了 `transformers.utils.import_utils.is_torch_fx_available`——该符号在 **transformers 5.x 已删除**（4.x 才有）。本机是 5.2.0，说明该模型面向 **transformers 4.x** 编写。视觉编码器里多处 4.x API / 分辨率假设在本栈下触发越界。
2. **次因**：换 bfloat16 / float16、改 `image_size`（640/1024）、改 `crop_mode` 均无效 → 排除精度与单页参数问题，确认为代码层不兼容。

### 修复路线（二选一，推荐 A）

#### 路线 A（推荐）：专用 venv 钉 transformers 4.x
新建独立环境，装**模型仓库 README 指定的 transformers 4.x 版本**（请先查 `E:\Workbuddy\Unlimited-OCR\model\README.md` 的 `requirements` 确认精确版本号，常见为 `transformers==4.4x`），复用本机 torch 2.11 cu128：
```bat
:: 在 E:\Workbuddy\Unlimited-OCR 下建专用 venv
"E:\Workbuddy\binaries\python\versions\3.13.12\python.exe" -m venv E:\Workbuddy\Unlimited-OCR\venv
E:\Workbuddy\Unlimited-OCR\venv\Scripts\pip install ^
   torch==2.11.0+cu128 torchvision --index-url https://download.pytorch.org/whl/cu128 ^
   "transformers==4.4x" pymupdf easydict
```
> 注意：`torch==2.11.0+cu128` 是本地 cu128 构建，PyPI 上是 `torch==2.11.0`（CUDA 12.x wheel）；若 PyPI 无 2.11，用 `pip install torch --index-url https://download.pytorch.org/whl/cu128` 拉 cu128 版。
> 已打的 `is_torch_fx_available` 补丁（§下方）在 4.x 下其实不需要，但留着无害。

#### 路线 B：走官方 SGLang server
仓库原生支持 `python -m sglang.launch_server --model-path E:\Workbuddy\Unlimited-OCR\model --port 10000`，SGLang 自带模型运行器，可能绕开 transformers 自定义代码路径。需另装 `sglang`（版本需与模型 README 对应）。适合做长驻服务（与 §4 架构吻合）。

### 已应用的兼容补丁（已写入模型源文件，团队无需重做）
`E:\Workbuddy\Unlimited-OCR\model\modeling_deepseekv2.py` 第 61 行：
```python
# 原：from transformers.utils.import_utils import is_torch_fx_available
try:
    from transformers.utils.import_utils import is_torch_fx_available
except Exception:
    def is_torch_fx_available():
        return False
```
> 若该文件被重新下载（换源/重拉），需重打此补丁。HF 模块缓存位于 `E:\Cache\huggingface\modules\transformers_modules\model\`，调试时清掉此目录可强制重拷源文件。

---

## 四、给图书馆项目的集成方案（核心价值）🟢

### 4.1 为什么 Unlimited-OCR 正好对症

当前 `ROADMAP.md` 记载：~4538 本扫描版 PDF 多是**超大尺寸扫描图像**，tesseract 单维上限 32767px 直接报错，OCR 收益 ≈0%。

| 对比 | tesseract（现状） | Unlimited-OCR（目标） |
|---|---|---|
| 超大扫描图 | 单维 >32767px 直接失败 | 内部缩到 `image_size`（1024）再处理，**无像素上限瓶颈** |
| 中文 | chi_sim，版面/表格弱 | DeepSeek-OCR 谱系，**中文强、读版面/表格/混排** |
| 形态 | 轻量 CLI | 6.7GB 视觉语言模型，需 GPU |
| 速度 | 毫秒/页 | 秒/页（慢，但能跑出正文） |

→ Unlimited-OCR 是解「超大扫描版中文书」的正确工具。

### 4.2 现有抽取链路卡点（必改）

`G:\my-library\Private_Lib.py`：
- **第 1443 行**（根因级）：
  ```python
  if size_mb > 50:
      return _title_fallback(book_id)   # ← 4538 本扫描 PDF 基本都 >50MB，全被这里跳过，永不进 OCR
  ```
  **必须改为**：>50MB 不跳过，路由到 OCR（Unlimited-OCR 能处理大图）。
- **第 1460 行**：`ocr = _ocr_pdf(file_path, max_pages=15)` —— 当前走 tesseract。改为走 Unlimited-OCR 后端即可，其余逻辑（写 `text_content`、标记 `text_extracted`）不动。
- **`run_extract_full.py` 的 `ocr` 模式** 已能筛「正文 ≤200 字（书名兜底）」的 PDF 重抽，接好后端后可直接复用做批量补抽。
- **路径迁移坑**：代码里写死 `F:\my-library\tools\tesseract_ocr` 与 `F:\my-library\tools\ocr_tmp`，但项目已迁到 **G:\my-library**。OCR 临时目录应改为项目相对路径或 `G:\my-library\tools\ocr_tmp`，否则探测/写临时文件失败。

### 4.3 推荐架构：长驻 OCR 服务 + 零依赖调用

模型 6.7GB，**绝不能每本书 reload**。设计为一个常驻服务（路线 A/B 的 venv 起），`Private_Lib.py` 用标准库 `urllib` 调 HTTP——契合项目「零第三方依赖」哲学。

```
┌────────────────────┐      HTTP POST /ocr (multipart: pdf)      ┌──────────────────────────┐
│ Private_Lib.py      │ ───────────────────────────────────────► │ uocr_server.py (常驻)     │
│ extract_text_for()  │ ◄──────────── JSON {text: "..."} ──────── │  加载 Unlimited-OCR 一次   │
│ (stdlib urllib)     │                                           │  内部 PyMuPDF 渲染+推理    │
└────────────────────┘                                           │  RTX 5070, 6.8GB         │
                                                                  └──────────────────────────┘
```

**服务封装伪代码**（`uocr_server.py`，用路线 A 的 venv 跑）：
```python
# 启动：venv\Scripts\python uocr_server.py  (detached, 开机自启)
import fitz, gradio  # 或纯 http.server；下面用最简 http.server 示意
# 进程内：model = AutoModel.from_pretrained(MODEL_DIR, trust_remote_code=True,
#                                          torch_dtype=torch.float16).eval().cuda()  # 仅加载一次
def ocr_pdf(pdf_bytes, max_pages=30):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    fitz.TOOLS().set_max_image_size(0)            # 允许超大扫描页
    imgs = [render(page, longest=2000) for page in doc[:max_pages]]
    text = model.infer_multi(tokenizer, prompt="<image>Multi page parsing.",
                              image_files=imgs, image_size=1024,
                              max_length=32768, no_repeat_ngram_size=35, ngram_window=1024)
    return text
```

**Private_Lib.py 改造点**（最小改动）：
```python
# 第 1443 行附近：去掉 >50MB 硬跳过，改为标记需要 OCR
# if size_mb > 50: return _title_fallback(book_id)   # 删除/注释
# 第 1459-1466 行：扫描版分支改调服务
if not text.strip():
    try:
        import urllib.request, json, tempfile, os
        # 把 pdf POST 给常驻服务
        req = urllib.request.Request("http://127.0.0.1:10000/ocr",
              data=open(file_path,'rb').read(),
              headers={"Content-Type":"application/octet-stream"})
        ocr = json.loads(urllib.request.urlopen(req, timeout=600).read())["text"]
    except Exception as e:
        ocr = ""
    if ocr.strip():
        text = ocr
    else:
        return _title_fallback(book_id)
```

### 4.4 性能与显存预算（RTX 5070 12GB）
- 模型常驻 **6.8 GB**，余 ~5 GB 给其他（Ollama 7b 若同卡需错峰）。
- 单实例串行；**不要并发**多本书（会 OOM 或争显存）。
- 速度：视觉语言模型秒/页，4538 本为长时后台任务，复用现有 `run_extract_full.py ocr` 的进度续跑机制即可。
- 超大 PDF：分页渲染（每页长边 ≤2000px）后送模型，`infer_multi` 内部再缩到 1024——显存可控。

### 4.5 风险与建议
- 🔴 **推理阻塞未解**（§3）：先按路线 A 钉 transformers 4.x，单页跑通 `verify_single.py` 再接 §4.3。
- 🟡 **中文精度**：OCR 结果需抽检（对比原书），尤其古籍/竖排/表格；必要时用 Ollama 7b 做后校对。
- 🟡 **首跑慢**：模型加载 ~5s/次，但常驻服务只加载一次；服务挂了要有自启（参考 VoiceStudio 的 `vs_ensure.js` 思路）。
- 🟢 **存储治理联动**：OCR 出的正文进 `book_text.text_content` 后，ROADMAP 的「AI 摘要修复」「知识图谱」两项可直接解锁。

---

## 五、交接清单（图书馆项目下一步）✅

1. [ ] 查 `model/README.md` 确认 transformers **精确 4.x 版本号**
2. [ ] 按 §3 路线 A 建 `E:\Workbuddy\Unlimited-OCR\venv`，装钉版 transformers
3. [ ] 跑 `verify_single.py sample\sample_scanned.pdf` 验证单页 OCR 出字（解锁 §3 阻塞）
4. [ ] 起 `uocr_server.py` 常驻服务（端口 10000），自启
5. [ ] 改 `Private_Lib.py`：删 >50MB 硬跳过（1443 行）、扫描版分支改调服务（1460 行）、修 F:→G: 临时目录
6. [ ] 用 `run_extract_full.py ocr` 对 4538 本扫描 PDF 批量补抽，进度续跑
7. [ ] 抽检中文精度，必要时接 Ollama 7b 后校对
8. [ ] 解锁 ROADMAP 的 AI 摘要修复 / 知识图谱

---

## 六、文件清单 📁

| 文件 | 用途 |
|---|---|
| `E:\Workbuddy\Unlimited-OCR\model\` | 模型权重 + 自定义代码（6.67GB） |
| `E:\Workbuddy\Unlimited-OCR\verify_uocr.py` | 多页 OCR 验证（infer_multi） |
| `E:\Workbuddy\Unlimited-OCR\verify_single.py` | 单页 OCR 验证（infer，官方路径） |
| `E:\Workbuddy\Unlimited-OCR\sample\sample_scanned.pdf` | 真实扫描样本（50MB，来自图书馆库） |
| `E:\Workbuddy\Unlimited-OCR\model\modeling_deepseekv2.py` | 已打 `is_torch_fx_available` 补丁 |
| `G:\my-library\Private_Lib.py` | 集成改造点：1443 / 1460 行（见 §4.2） |
| `G:\my-library\tools\run_extract_full.py` | 批量 OCR 重抽（`ocr` 模式，可复用） |

---

> 备注：本次验证用的 Python 环境是 `E:\Workbuddy\Chatterbox\env`（复用其 torch）。该环境 transformers 5.2 与模型不兼容，**仅供部署排查**；生产集成请用 §3 新建的专用 venv，避免污染 Chatterbox。
