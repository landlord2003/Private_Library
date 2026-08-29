# Unlimited-OCR × my-library 集成与接手报告

> 状态：**✅ 已验证可用（端到端跑通）**，2026-08-29
> 部署侧：E:/Workbuddy/Unlimited-OCR/　模型：baidu/Unlimited-OCR（6.67GB，ModelScope 源）
> 接手方：my-library 项目（G:/my-library，扫描 PDF 文本抽取）

---

## 一、一句话结论

Unlimited-OCR 已在本机（Win11 + RTX 5070 12GB）**端到端验证可用**：从一本 50MB 真实扫描 PDF（《图说中国绘画史》）抽出了准确的中文正文（书名/作者/ISBN/CIP/大段书评），单页 ~3.6s、6 页 ~70s、显存占用 6.8GB。图书馆项目只需改 `Private_Lib.py` **3 处**即可接手，彻底解决"4538 本扫描 PDF 抽不到正文"的老问题。

---

## 二、运行环境（已钉死，务必照此复现）

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.13.12（受管） | `C:/Users/Lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe` |
| 虚拟环境 | **`.venv_uocr`** | `E:/Workbuddy/Unlimited-OCR/.venv_uocr`（专用，勿动 Chatterbox 的 venv） |
| torch | **2.10.0+cu128** | Blackwell(RTX5070) 需 ≥2.10 |
| torchvision | 0.25.0+cu128 | |
| transformers | **4.57.1** | ⚠️ **关键**：模型自定义代码面向 4.x，5.2 会 CUDA 越界 |
| 精度 | **bfloat16** | float16 会 dtype 不匹配（masked_scatter Half vs Float）；bf16 正常 |
| 其余 | pymupdf 1.28 / einops 0.8.2 / addict / easydict / matplotlib / psutil | 见 `install_uocr_torch.log` |

模型文件：`E:/Workbuddy/Unlimited-OCR/model/`（6.67GB safetensors + 自定义 modeling_*.py）。
已打 1 处兼容补丁：`modeling_deepseekv2.py` 里 `is_torch_fx_available` 改为 try/except 兜底（transformers 4.57.1 已含该符号，补丁无害）。

---

## 三、验证证据（确凿）

| 项 | 实测 |
|----|------|
| 模型加载 | 3.8s，显存 **6.8GB**（12GB 卡有余量） |
| 单页 `infer` | 3.6s，中文准确 |
| 多页 `infer_multi`（6 页 / 50MB 扫描本） | ~70s，输出 `result.md` 干净中文 |
| 样本输出片段 | 图说中国绘画史 / [美] 高居翰（James Cahill）著 李渝 译 / ISBN 978-7-108-04785-4 / "我推荐大家来读这一本图文并茂的中国绘画史…"（大段书评完整） |

验证脚本：`verify_single.py`（单页）、`verify_uocr.py`（多页→result.md）、`uocr_cli.py`（CLI 包装，图书馆调用形态）、`uocr_service.py`（可选 HTTP 服务）、`uocr_client_test.py`（urllib 调用示例）。

---

## 四、早前阻塞的根因与修复（供排错参考）

最初在 Chatterbox venv（transformers **5.2**）下推理触发 `CUDA device-side assert`（deepencoder.py gather index OOB）。
**根因**：模型自定义代码（modeling_deepseekv2 / modeling_unlimitedocr / deepencoder）面向 **transformers 4.x** 编写，引用了 5.2 已删除/改动的 API（`is_torch_fx_available`、`self.num_heads`、`rotary_emb` 位置等），导致视觉编码器推理越界。
**修复**：建专用 venv 钉 `transformers==4.57.1`（README 验证过的组合）+ `torch==2.10.0+cu128` + **bf16**。重跑即通过。
（float16 会再撞 `masked_scatter_` 的 Half/Float dtype 不匹配，必须用 bf16。）

---

## 五、图书馆集成改造（`Private_Lib.py` 共 3 处）

### 编辑 1：放开 >50MB 硬跳过（根因）
第 1443 行：
```python
        # 原：>50MB 直接跳过 → 4538 本扫描 PDF 永不进 OCR
        if size_mb > 50:
            print(f"[跳过大文件] {size_mb:.0f}MB {fmt} {title_short}", flush=True)
            return _title_fallback(book_id)
```
改为（仅跳过极端巨型文件，避免显存/时长爆炸；普通 50–几百 MB 扫描本正常进 OCR）：
```python
        # 修改：50MB 不再跳过；仅 >1500MB 极端大文件才跳过
        if size_mb > 1500:
            print(f"[跳过超大文件] {size_mb:.0f}MB {fmt} {title_short}", flush=True)
            return _title_fallback(book_id)
```

### 编辑 2：扫描分支改调 Unlimited-OCR（替换 tesseract）
在第 1459–1466 行的扫描 fallback 处，把 `_ocr_pdf(...)` 换成 Unlimited-OCR CLI（tesseract 单维上限 32767px，扛不住超大扫描页；Unlimited-OCR 内部缩到 1024，无此限制、中文更强）：
```python
            # Scanned PDF fallback: 优先 Unlimited-OCR，tesseract 作兜底
            if not text.strip():
                ocr = _ocr_unlimited(file_path, max_pages=20)
                if not ocr.strip():
                    ocr = _ocr_pdf(file_path, max_pages=15)   # 保留原 tesseract 兜底
                if ocr.strip():
                    text = ocr
                    print(f"[扫描版PDF] OCR 获取 {len(ocr)} 字: {title_short}", flush=True)
                else:
                    print(f"[扫描版PDF] 无文字层且OCR不可用, 用书名兜底: {title_short}", flush=True)
                    return _title_fallback(book_id)
```

### 编辑 3：新增 `_ocr_unlimited()` 函数（subprocess 调 CLI）
在 `_ocr_pdf` 附近新增（零额外依赖，纯 stdlib subprocess + 受管 venv）：
```python
import subprocess as _sp
_UOCR_PY  = r"E:/Workbuddy/Unlimited-OCR/.venv_uocr/Scripts/python.exe"
_UOCR_CLI = r"E:/Workbuddy/Unlimited-OCR/uocr_cli.py"

def _ocr_unlimited(file_path, max_pages=20):
    """调用 Unlimited-OCR 抽扫描版PDF正文；每本独立进程，最稳。返回 markdown 字符串。"""
    try:
        out = _sp.run([_UOCR_PY, _UOCR_CLI, file_path, str(max_pages)],
                      capture_output=True, timeout=1800)
        if out.returncode == 0:
            return out.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[Unlimited-OCR] 调用失败: {e}", flush=True)
    return ""
```

> ⚠️ 路径核对：原 `_ocr_pdf` 可能硬编码了 `F:\my-library\...` 临时目录（项目已迁 G 盘）。若保留 tesseract 兜底，请把其中的 `F:` 改为 `G:` 或改用 `tempfile.gettempdir()`。Unlimited-OCR 路径（`uocr_cli.py`）已用 `tempfile`，无此坑。

---

## 六、调用形态（两种，任选）

**A. CLI + subprocess（推荐，已实测）**：如上 `_ocr_unlimited`，每本 PDF 起一个独立进程加载模型，结束即释放显存。最契合"批量抽取 4538 本"的场景，无长驻进程/并发坑。
**B. HTTP 服务（可选）**：`uocr_service.py` 常驻 `127.0.0.1:10500`，图书馆用 `urllib.request` POST `{"pdf_path":..., "max_pages":20}` 调用（见 `uocr_client_test.py`）。注意：连续请求下服务稳定性待增强，**批量任务建议用 A**。

---

## 七、批量抽取实操建议

- **分页**：`infer_multi` 一次吃 N 页合一序列，`max_pages=20` 较稳；超长书按 20 页/次循环调用（CLI 每次重加载模型 ~4s，可接受）。
- **显存**：OCR 时占 6.8GB；图书馆后端本身是 CPU/FastAPI，与 OCR 的 GPU 占用不冲突（subprocess 结束即释放）。
- **时长估算**：样本 50MB/6 页 ≈ 70s → 一本 200 页扫描书（10 次调用）约 12–15 分钟；4538 本建议**夜间分批 + 并发数=1**（GPU 单卡，勿并行多进程抢显存）。
- **输出**：`uocr_cli.py` 输出含 `<|det|>类型 [bbox]<|/det|>` 版面标记 + 正文的 markdown。若只要纯文本，按 `<|det|>` 块过滤文本类（text/title/header/footer）即可，或后续用正则剥离标签。

---

## 八、注意事项

1. 模型与 venv 在 **E:/Workbuddy/Unlimited-OCR/**，不在 my-library 仓库内；若迁移机器，需连同 `model/`(6.67GB) + `.venv_uocr/` 一起搬，或重跑 `install_uocr_torch.log` 的安装命令。
2. 跑 OCR 的 Python **必须清掉 `PYTHONPATH` 与 `ACC_PRODUCT_CONFIG_V3`**（WorkBuddy 注入的 shim 会干扰子进程），CLI 已假设干净环境；若在 WorkBuddy 内调用，确保 subprocess 环境已 unset。
3. 模型自定义代码受 `trust_remote_code=True` 加载，已审计无外联/无执行副作用；如需升级模型，重新从 ModelScope 拉 `PaddlePaddle/Unlimited-OCR` 并复查 `modeling_*.py`。
4. 本机无 SkillManage 写入通道，部署脚本与报告存于 `E:/Workbuddy/Unlimited-OCR/` 与 `G:/my-library/`，供团队接手。
