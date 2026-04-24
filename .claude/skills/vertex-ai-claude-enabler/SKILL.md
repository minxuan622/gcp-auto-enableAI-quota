---
name: vertex-ai-claude-enabler
description: 在 GCP Vertex AI 上開通 Anthropic Claude 模型（EULA 同意 + 配額提升），並協助維護 gcp-claude-manager 工具本身。當使用者要求「幫我開 Claude X.X」、「在專案 XXX 開通 Claude 新模型」、「Claude Opus/Sonnet/Haiku X.X 發布了幫我開」、「提升 Claude X 的配額」、「新 Claude 模型在 Vertex AI 還沒開通」、或提及 Vertex AI Model Garden、anthropic-claude base_model、Cloud Quotas、RPM/TPM 等情境時必須觸發；也適用於修改本工具程式碼（新增模型、改 Routing 分類、擴充 CLI 子指令、修 EULA 自動填表）。此 Skill 限於 gcp-claude-manager 專案目錄下才會載入。
---

# Vertex AI Claude Model Enabler

協助 Kevin 在 GCP Vertex AI 上**全自動**開通 Claude 模型 + 提升配額，並且在需要改 `gcp-claude-manager` 程式碼時當作參考手冊。本 Skill 只在 cwd 為本專案底下時才會載入，不會汙染全域。

---

## Part A：執行（使用這個工具）

當 Kevin 說「幫我在 X 專案開 Claude Y」或「提升 Z 配額」時適用。

### 核心原則

1. **先驗證模型在 Vertex AI 上是否已上架，再動手**——Anthropic 發布 ≠ Vertex AI 上架
2. **不要猜模型 ID**——用 WebFetch 或 Anthropic 官方文件確認
3. **在 Kevin 確認後直接執行**——用 CLI 子指令 + `--yes` 跑完整流程，不要停在「請你執行 `./run.sh`」
4. **確認機制用 chat，不用 CLI prompt**——chat 複誦目標 → Kevin 回 yes → 加 `--yes` 跑

### CLI 子指令（主要工具）

**開通模型：**

```bash
cd /Users/kevin/Claude/gcp-claude-manager && source .venv/bin/activate && \
python main.py enable --project <PROJECT_ID> --models <slug1,slug2> --yes
```

- `--models` 接**逗號分隔**的 URL slug（可多模型同時開）
- `--yes` 跳過 CLI 自帶的確認提示（已在 chat 確認過）
- 預設開瀏覽器讓 Kevin 看進度；遠端/手機場景加 `--headless`

**提升配額：**

```bash
python main.py quota --project <PROJECT_ID> \
                     --model <slug> \
                     --routing global \
                     --rpm <N> --input-tpm <N> --output-tpm <N> \
                     --yes
```

- `--routing`：`global` / `us` / `eu` / `regional`（Kevin 預設都用 `global`）
- 三個 `--*-tpm` / `--rpm` **可以只給部分**——沒給的就不動
- Global 是**無溢價**的 endpoint；其他都有 +10% 溢價

### 標準執行流程

#### Step 1：確認模型在清單中 + 已上架

```
Grep pattern="CLAUDE_MODELS" path="main.py" -A 10
```

**如果已在清單中** → 跳 Step 3。

**如果不在清單中** → WebFetch 驗證 Vertex AI 是否已上架：

```
WebFetch url="https://platform.claude.com/docs/en/api/claude-on-vertex-ai"
        prompt="Is Claude <Family> <Version> available on Vertex AI? What is the exact base_model ID and URL slug?"
```

- 上架了 → Step 2
- 沒上架 → 誠實告訴 Kevin「還沒上架，Vertex AI 通常晚幾天」，**不要**硬塞進清單

#### Step 2：加入 `CLAUDE_MODELS`

Edit `main.py`，在 `CLAUDE_MODELS` 最頂端加一列（新的在前）：

```python
("Claude 4.7 Opus", "anthropic-claude-opus-4-7", "claude-opus-4-7"),
```

格式：`(display_name, base_model, url_slug)`
- `base_model` **帶** `anthropic-` 前綴
- `url_slug` **不帶** `anthropic-` 也**不帶**日期

#### Step 3：chat 確認目標

複誦要做的事給 Kevin 確認：

> 我要在 `kevin-480608` 開通 **Claude 4.7 Opus**，確定嗎？

等 Kevin 回 yes / 確定 / 對 / 嗯。

#### Step 4：執行 enable 子指令

```bash
python main.py enable --project kevin-480608 --models claude-opus-4-7 --yes
```

- 預設顯示瀏覽器，Kevin 能看 Playwright 操作進度
- 遠端/手機情境加 `--headless`（需 `.browser_state/` 已存在）

#### Step 5：提升配額（如 Kevin 有要求）

```bash
python main.py quota --project kevin-480608 \
                     --model claude-opus-4-7 \
                     --routing global \
                     --rpm 100 --input-tpm 500000 --output-tpm 100000 \
                     --yes
```

如果 Kevin 沒明說數值，先問他目標（或建議「目前 5 倍以內自動核准」）。

### 遠端 / 手機場景

Kevin 可能從手機 SSH 到 Mac 觸發你。判斷原則：

- cwd 在 `/Users/kevin/Claude/gcp-claude-manager`（本地桌機）→ 預設顯示瀏覽器
- Kevin 明確說「我在手機 / 遠端」→ 加 `--headless`
- 不確定時主動問：「要 headless 嗎？」

**前置**：headless 模式需要 `.browser_state/` 已存在。如果不存在，Kevin 必須先在桌機互動式跑過一次 `./run.sh` 登入 Google。

### 範例對話

**範例 1：清單中沒有、已上架**

> Kevin：「Claude Opus 4.7 發布了，幫我在 kevin-480608 開通」

1. Grep CLAUDE_MODELS → 沒 4.7
2. WebFetch 確認已上架 Vertex AI，base_model 是 `anthropic-claude-opus-4-7`
3. Edit 加進 CLAUDE_MODELS
4. chat 確認：「已加入 Claude 4.7 Opus 到清單。我要在 `kevin-480608` 執行 EULA 開通，確定嗎？」
5. Kevin 回 yes
6. Bash: `python main.py enable --project kevin-480608 --models claude-opus-4-7 --yes`

**範例 2：已在清單中**

> Kevin：「幫我在 prod-gcp 也開 Claude 4.7 Opus」

1. Grep → 有 4.7
2. chat 確認 → Kevin yes → Bash 執行

**範例 3：未上架**

> Kevin：「Claude Sonnet 5 幫我開」

1. WebFetch docs → 沒 Sonnet 5 條目
2. 告訴 Kevin：「Anthropic 有公告 Sonnet 5，但 Vertex AI 還沒上架。等一兩天再試，需要我追蹤嗎？」

**範例 4：提升配額**

> Kevin：「幫我把 kevin-480608 的 Claude 4.7 Opus Global RPM 拉到 200」

1. chat 確認：「要把 `kevin-480608` / Claude 4.7 Opus / Global RPM 提升到 200，其他不動，確定嗎？」
2. Bash: `python main.py quota --project kevin-480608 --model claude-opus-4-7 --routing global --rpm 200 --yes`

---

## Part B：實作（修改這個工具）

當 Kevin 要求改 code、擴充功能、修 bug 時適用。

### 專案架構

```
gcp-claude-manager/
├── main.py               # 所有邏輯（2000+ 行，刻意單檔）
├── config.json           # EULA 表單企業資訊
├── .env                  # 瀏覽器行為、預設值
├── requirements.txt
├── setup.sh / setup.bat
├── run.sh / run.bat
├── README.md
└── .claude/skills/       # 本 Skill
```

**全部邏輯在 `main.py` 一檔**——部署簡單、耦合低。檔案 > 2500 行再考慮拆。

### `main.py` 分區地圖

行號大略（會漂移，以實際 Grep 為準）：

| 區塊 | 行號 | 內容 |
|------|------|------|
| Imports + .env | 1–40 | `argparse`, `dotenv`, Playwright, google-cloud-* |
| 常數 | 40–80 | `CLAUDE_MODELS`, `ROUTING_KEYWORDS`, `ROUTING_PRICING`, `ROUTING_CLI_MAP`, `QUOTA_TYPE_KEYWORDS` |
| 設定與驗證 | 100–230 | `load_config()`, `check_gcloud_auth()`, `get_accessible_projects()`, `select_project()`, `select_models()` |
| Billing / N/A 警示 | 250–310 | `check_billing()`, `_warn_no_billing()`, `_check_all_quotas_na()` |
| 瀏覽器狀態 | 310–330 | `_load_browser_state()`, `_save_browser_state()` |
| API 啟用 | 330–370 | `_enable_single_api()`, `enable_api()` |
| Playwright EULA | 370–940 | `auto_fill_eula()` + `_fill_form_sequential()` + 一堆輔助 |
| 配額查詢/提交 | 940–1170 | `get_quota_info()`, `_classify_quota()`, `submit_single_quota()` |
| 互動配額流程 | 1177–1560 | `quota_flow()`（狀態機 Step 1–4） |
| 批次 / OpResult | 1890–2040 | `_quota_one_project()`, `run_batch_quota()`, `print_batch_summary()` |
| CLI 非互動 | 2042–2200 | `cmd_enable()`, `cmd_quota()`, `cmd_list_models()`, `parse_args()` |
| 互動選單主流程 | 2200–2300 | `interactive_menu()` |
| 入口 | 最底 | `main()` 分派 |

### `CLAUDE_MODELS` 格式

Tuple 三元素，**順序不可顛倒**：

```python
(display_name, base_model_dimension, url_slug)
```

| 欄位 | 命名規則 | 範例 |
|------|---------|------|
| `display_name` | `Claude <版本> <家族>` | `"Claude 4.7 Opus"` |
| `base_model_dimension` | `anthropic-claude-<家族>-<版本>`（含前綴，不含日期） | `"anthropic-claude-opus-4-7"` |
| `url_slug` | `claude-<家族>-<版本>`（不含前綴，不含日期） | `"claude-opus-4-7"` |

**歷史教訓**：早期 4.5 系列曾誤寫成 `claude-sonnet-4-5-20250514`（帶日期），Vertex AI 現在一律用不帶日期的 alias。加新模型時**嚴格遵守不含日期**。

### 新增模型完整步驟

1. **WebFetch 驗證上架**：
   ```
   WebFetch url="https://platform.claude.com/docs/en/api/claude-on-vertex-ai"
   ```
2. **Edit `CLAUDE_MODELS`** 在最頂端加一列
3. **驗證 CLI help 自動更新**：
   ```bash
   python main.py enable --help | grep <new_slug>
   ```
4. **sandbox 端對端測試**：
   ```bash
   python main.py enable --project <sandbox> --models <new_slug> --yes
   ```

CLAUDE_MODELS 會自動灌進 argparse help 和互動選單，不需要改別處。

### Routing 分類實作細節

`ROUTING_KEYWORDS` 用 **metric 前綴** 比對：

```python
ROUTING_KEYWORDS = {
    "Global":           ["global_online_prediction", "global_generate_content"],
    "US Multi-region":  ["us_multi_region"],
    "EU Multi-region":  ["eu_multi_region"],
    "Regional":         [],  # fallthrough
}
```

`_classify_quota()` 比對順序：EU → US → Global → Regional（防禦性寫法，避免關鍵字互相包含）。

實際 metric 樣式（來自 Cloud Quotas API）：

```
aiplatform.googleapis.com/global_online_prediction_input_tokens_per_minute_per_base_model
aiplatform.googleapis.com/us_multi_region_online_prediction_input_tokens_per_minute_per_base_model
aiplatform.googleapis.com/eu_multi_region_online_prediction_input_tokens_per_minute_per_base_model
aiplatform.googleapis.com/online_prediction_input_tokens_per_minute_per_base_model  # ← Regional
```

**陷阱**：Gemini 某些 metric 結尾是 `_global`（例：`generate_content_image_gen_per_project_per_base_model_global`），那是 Gemini 的「全球影像生成」quota、跟 Claude 無關。我們的關鍵字 `global_online_prediction` 有**底線前綴**才能正確匹配、不會誤判尾綴 `_global`。

### 函數可重用性分類

**純資料（CLI 子指令可安全呼叫）：**

- `load_config()`, `check_gcloud_auth()`
- `check_billing(project_id)` → bool
- `enable_api(project_id)` — Service Usage SDK
- `get_quota_info(project_id, base_model)` — REST + SDK
- `submit_single_quota(project_id, quota_info, new_limit)` — SDK
- `_classify_quota(name, metric)` — 純邏輯
- `_check_all_quotas_na(route_quotas)` — 純邏輯
- `auto_fill_eula(project_id, models, config)` — 開瀏覽器但不需 TTY（headless 可用）

**互動式（CLI 子指令不可用）：**

- `select_project()`, `select_models()` — InquirerPy
- `quota_flow()` — 整個狀態機都 InquirerPy
- `interactive_menu()` — 主選單

**規則**：CLI 子指令 handler（`cmd_enable`/`cmd_quota`）**只能**呼叫「純資料」那組。任何 prompt 由 Claude 在 chat 代理，或 `--yes` 跳過。

### CLI 子指令設計

#### `cmd_enable` 流程

1. `check_gcloud_auth()` + `load_config()`
2. 解析 `--models`（逗號分隔）→ `_find_model_by_slug()`
3. `check_billing()` 失敗 → `_warn_no_billing()` + exit
4. 顯示摘要 + `inquirer.confirm()`（除非 `--yes`）
5. `--headless` → `globals()["BROWSER_HEADLESS"] = True`
6. `enable_api()` → `auto_fill_eula()`

#### `cmd_quota` 流程

1. `_find_model_by_slug()` + `ROUTING_CLI_MAP[...]`
2. `check_billing()`
3. `get_quota_info()` → `_classify_quota()` 分組
4. `_check_all_quotas_na()` 若 True 提示先 enable
5. 根據 `--rpm`/`--input-tpm`/`--output-tpm` 組 submissions
6. 顯示現況 + 確認 + 逐一 `submit_single_quota()`

#### 加新子指令模板

在 `parse_args()` 加 subparser、實作 `cmd_xxx()`、在 `main()` 分派 dict 加一行。

### Playwright EULA 穩定化

`auto_fill_eula()` 是最脆弱部分——依賴 GCP Console SPA DOM 結構。

**已實作的防護：**

1. `.browser_state/state.json` 持久化 cookies + localStorage
2. 多重選擇器：`button:has-text("Enable"), [role="button"]:has-text("Enable"), a:has-text("Enable"), :text-is("Enable")`
3. **30 秒 timeout**（15 秒不夠，4.7 頁面實測 20+ 秒才渲染完）
4. **Tab 鍵循序填表**（`_fill_form_sequential`）比 CSS selector 穩
5. Agreement 彈窗重試 3 次（`_try_check_terms` + `_force_click_all_checkboxes`）

**如果 EULA 頁面結構變動：**

| 症狀 | 調查方向 |
|------|---------|
| Enable 按鈕找不到 | `page.screenshot()` 看實際頁面；檢查按鈕文字是否改了 |
| 表單欄位順序變動 | Tab 循序會錯亂——重新確認順序調 `_fill_form_sequential` |
| 下拉選單不展開 | 調 `_tab_select_dropdown` 的 key 序列（ArrowDown/Enter） |
| Terms checkbox 點不到 | 檢查 `_is_checkbox_checked` 的 `aria-checked` 讀法 |

Debug 時先 non-headless + `BROWSER_SLOW_MO=1500` 慢速觀察。

### 配額提交細節

`submit_single_quota()` 用 `google-cloud-cloudquotas` SDK（**不是**舊的 Service Usage API）：

- **Parent 格式**：`projects/{id}/locations/global`（**不含** `/services/...`，含的話 400）
- **Location 固定 `global`**（Cloud Quotas 設計，不是區域）
- **quota_preference_id 必須唯一**——uuid 後綴避免衝突
- **回傳 `reconciling`**：`False` = APPROVED、`True` = PENDING

狀態對應：

| `reconciling` | Exception | status |
|---------------|-----------|--------|
| `False` | 無 | APPROVED |
| `True` | 無 | PENDING |
| — | `InvalidArgument` | DENIED |
| — | `PermissionDenied` | ERROR |
| — | 其他 | ERROR |

### 測試原則

**沒有 pytest suite**——大部分邏輯依賴 GCP SDK + Playwright + 真實瀏覽器，mock 成本高。可做：

1. **Syntax / argparse**：`python main.py --help`, `enable --help`, `quota --help`
2. **Error path**：`python main.py enable --project x --models nonexistent --yes`
3. **Dry-run 等級**：手動呼叫 `_classify_quota()` 測分類
4. **端對端**：sandbox 專案實測

### 修改檢查清單

改動前問自己：

- [ ] 是否需要改 `CLAUDE_MODELS`？
- [ ] 是否影響 CLI help 輸出？（`python main.py --help` 檢查）
- [ ] 是否影響互動選單？（`./run.sh` 檢查）
- [ ] 是否影響 headless 流程？（`--headless` 跑一次）
- [ ] README 需要同步？（支援模型表、CLI 範例）
- [ ] 改了 Routing 分類 → 用實際 metric 字串測 `_classify_quota()`

### 設計決策

**為什麼單檔？** 部署簡單（`scp main.py` 就搬）、耦合低、改動範圍清楚。

**為什麼 CLI + 互動並存？** 互動選單給新手/探索/首次登入；CLI 子指令給熟手/腳本/AI agent。兩者共用底層函數。

**為什麼 `--headless` 在執行時 override 全域？** `BROWSER_HEADLESS` 是模組層級常數（從 .env 讀），`_make_browser_and_page` 直接讀它。用 `globals()[...] = True` 比重構所有呼叫傳 param 更輕量。

**為什麼 REST + SDK 兩條路？** `get_quota_info()` 用 REST（回應結構直觀好 debug），`submit_single_quota()` 用 SDK（型別安全、錯誤處理好）。

---

## 共用參考

### 三種配額類型

| 配額 | 含意 |
|------|------|
| RPM | Requests per minute |
| Input TPM | Input tokens per minute |
| Output TPM | Output tokens per minute |

### Routing 溢價對照

| 策略 | metric 前綴 | 溢價 | 備註 |
|------|------------|------|------|
| **Global** | `global_online_prediction_*` | **無** | 推薦預設、最高可用性 |
| **US Multi-region** | `us_multi_region_online_prediction_*` | +10% | 美國資料落地 |
| **EU Multi-region** | `eu_multi_region_online_prediction_*` | +10% | 歐盟資料落地 |
| **Regional** | `online_prediction_*`（無前綴） | +10% | 單區域 / provisioned throughput |

**Global 跟 US Multi-region 是不同 quota**——metric 前綴決定一切。

### 自動核准閾值

- **5 倍以內** → 通常 APPROVED（立即生效）
- 超過 5 倍 → PENDING（Google 人工審核 24-48 小時）
- 超過區域硬上限 → DENIED

### 常見錯誤對照

| 症狀 | 原因 | 解法 |
|------|------|------|
| 配額全部 N/A | 模型尚未開通 EULA | 先跑 `enable` 子指令 |
| 「專案尚未綁定 Billing」 | 專案沒計費 | Kevin 到 Console 綁定 |
| Enable 按鈕找不到 | SPA 載入慢 / 已開通 / slug 錯 | 工具已設 30 秒 timeout；仍失敗手動確認 |
| 「Terms of service not accepted」彈窗 | Angular Material checkbox 未生效 | 工具自動重試 3 次 |
| Model Garden 404 | slug 帶日期 / 尚未上架 | 用不帶日期的 slug；確認上架狀態 |
| `PermissionDenied` on quota | 權限不足 | Kevin 需要 Owner 或 Quota Administrator |

### 權限前置

Kevin 對目標專案需要：
- **Owner**，或同時擁有 **Service Usage Admin** + **Quota Administrator**
- 本機 `gcloud auth application-default login` 完成

### 與 Kevin 的互動基調

- **不反問能不能做**——能做就做，只在參數層級確認（哪個專案、提多少）
- **誠實講不能做的**——Vertex AI 沒上架就直說
- **回覆簡短**——加了什麼、跑什麼指令、結果如何
- **chat 確認、`--yes` 執行**——不要讓 Kevin 在 terminal 再按一次 y
