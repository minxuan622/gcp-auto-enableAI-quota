---
name: vertex-ai-claude-enabler
description: 在 GCP Vertex AI（Agent Platform）上開通 Anthropic Claude 模型（Model Garden EULA 同意）與提升 RPM / TPM 配額，並維護 gcp-claude-manager 工具本身。以下情境必須觸發：要在一個或多個 GCP 專案開通 Claude 模型或提升配額；以客戶名稱為單位批次處理（名稱與別名對應 customers.json 裡的專案）；新 Claude 模型發布後要加進工具或確認 Vertex AI 是否已上架；提及 Model Garden、anthropic-claude base_model、Cloud Quotas；修改本工具程式碼（CLAUDE_MODELS、Routing 分類、CLI 子指令、EULA 自動填表）。此 Skill 限於 gcp-claude-manager 專案目錄下載入。
---

# Vertex AI Claude Model Enabler

協助 Kevin 在 GCP Vertex AI 上**全自動**開通 Claude 模型 + 提升配額，並且在需要改 `gcp-claude-manager` 程式碼時當作參考手冊。本 Skill 只在 cwd 為本專案底下時才會載入，不會汙染全域。

---

## Part A：執行（使用這個工具）

當 Kevin 說「幫我在 X 專案開 Claude Y」或「提升 Z 配額」時適用。

### 核心原則

1. **先驗證模型在 Vertex AI 上是否已上架，再動手**——Anthropic 發布 ≠ Vertex AI 上架
2. **不要猜模型 ID**——slug 用 publisher models API 確認（Step 1），base_model 用 Cloud Quotas 實查（Part B「新增模型完整步驟」）
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
.venv/bin/python main.py quota --project <PROJECT_ID> \
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

```bash
.venv/bin/python main.py list-models
```

（不需要 GCP 驗證，會完整列出工具目前所有模型的顯示名稱、slug 與 base_model。）

**如果已在清單中** → 跳 Step 3。

**如果不在清單中** → 用 publisher models API 列出 Vertex 上實際存在的 anthropic 模型（**最可靠，slug 直接來自 API，不用猜**）：

```bash
TOKEN=$(gcloud auth application-default print-access-token)
curl -s "https://aiplatform.googleapis.com/v1beta1/publishers/anthropic/models?pageSize=100" \
  -H "Authorization: Bearer $TOKEN" -H "X-Goog-User-Project: <任一專案>"
# name 欄位 = publishers/anthropic/models/<slug>
```

注意要打 **global** endpoint（`aiplatform.googleapis.com`，不帶區域前綴），區域 endpoint 的清單不完整。

- 上架了 → Step 2
- 沒上架 → 誠實告訴 Kevin「還沒上架，Vertex AI 通常晚幾天」，**不要**硬塞進清單

#### Step 2：加入 `CLAUDE_MODELS`（base_model 要實查，見下）

Edit `main.py`，在 `CLAUDE_MODELS` 最頂端加一列（新的在前）：

```python
("Claude Opus 5.5", "anthropic-claude-opus", "claude-opus-5-5"),   # 4.8 之後：家族共用
("Claude 4.7 Opus", "anthropic-claude-opus-4-7", "claude-opus-4-7"),  # 4.7 以前：版本獨立
```

格式：`(display_name, base_model, url_slug)`
- `url_slug` = publisher API 回傳的 slug（不帶 `anthropic-`、不帶日期）
- `base_model` = **Cloud Quotas 裡實際存在的 dimension**，4.8 之後是家族名（`anthropic-claude-opus` / `-sonnet` / `-fable`），**不是** `anthropic-<slug>`。規則詳見 Part B「CLAUDE_MODELS 格式」。

#### Step 3：chat 確認目標

複誦要做的事給 Kevin 確認：

> 我要在 `kevin-480608` 開通 **Claude 4.7 Opus**，確定嗎？

等 Kevin 回 yes / 確定 / 對 / 嗯。

#### Step 4：執行 enable 子指令

```bash
.venv/bin/python main.py enable --project kevin-480608 --models claude-opus-4-7 --yes
```

- 預設顯示瀏覽器，Kevin 能看 Playwright 操作進度
- 遠端/手機情境加 `--headless`（需 `.browser_state/` 已存在）

#### Step 5：提升配額（如 Kevin 有要求）

```bash
.venv/bin/python main.py quota --project kevin-480608 \
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

（示意；專案與模型名稱依實際情況替換）

**範例 1：清單中沒有、已上架**

> Kevin：「Claude Opus 5.5 發布了，幫我在 <PROJECT_ID> 開通」

1. `list-models` → 清單裡沒有
2. publisher models API → 有 `claude-opus-5-5`
3. Cloud Quotas 實查 → 沒有版本層級 dimension，只有家族 `anthropic-claude-opus`
4. Edit 加進 CLAUDE_MODELS，確認 `get_quota_info` 查得到配額
5. chat 確認：「已加入 Claude Opus 5.5。我要在 `<PROJECT_ID>` 執行 EULA 開通，確定嗎？」
6. Kevin 回 yes → `.venv/bin/python main.py enable --project <PROJECT_ID> --models claude-opus-5-5 --yes`

**範例 2：已在清單中**

> Kevin：「幫我在 prod-gcp 也開 Claude 4.7 Opus」

1. `list-models` → 有 `claude-opus-4-7`
2. chat 確認 → Kevin yes → Bash 執行

**範例 3：未上架**

> Kevin：「Claude Opus 6 幫我開」（假設性的未來模型）

1. publisher models API → 沒有對應的 slug
2. 告訴 Kevin：「Anthropic 有公告，但 Vertex AI 還沒上架。等一兩天再試，需要我追蹤嗎？」

**範例 4：提升配額**

> Kevin：「幫我把 <PROJECT_ID> 的 Claude 4.7 Opus Global RPM 拉到 200」

1. chat 確認：「要把 `<PROJECT_ID>` / Claude 4.7 Opus / Global RPM 提升到 200，其他不動，確定嗎？」
2. Bash: `.venv/bin/python main.py quota --project <PROJECT_ID> --model claude-opus-4-7 --routing global --rpm 200 --yes`

### 客戶 → 專案映射（批次開通）

當 Kevin 提到**客戶名稱**（而非 project ID）時觸發。

**觸發詞範例：**

- 「幫 **<客戶>** 的所有專案開 Claude Opus 5.5」
- 「**<客戶別名>** 客戶把 RPM 都拉到 100」

**資料來源：** `customers.json`（位於專案根目錄，已 gitignored）

格式：

```json
{
  "customers": {
    "客戶 A": {
      "aliases": ["別名"],
      "projects": ["project-id-1", "project-id-2", ...],
      "notes": ""
    }
  }
}
```

**標準流程：**

1. **Read `customers.json`**
   - 不存在 → 提示：「請先 `cp customers.example.json customers.json` 並填入客戶資料」，停止
2. **匹配客戶**
   - 比對 `customers.<key>` 的 key
   - 也比對 `aliases` 陣列（fuzzy）
   - 找不到 → 列出現有客戶清單問 Kevin 選哪個
3. **chat 複誦確認**（**必做**，不要省略）：
   > 我要在 **<客戶>** 的 **N 個專案**：
   > - <project-id-1>
   > - <project-id-2>
   > - …
   >
   > 開通 **<模型>**，確定嗎？
4. **Kevin 回 yes** → 一次執行（`--projects` 逗號分隔；整批共用一個瀏覽器 session，登入只需一次）：
   ```bash
   .venv/bin/python main.py enable --projects <pid1>,<pid2>,<pid3> --models <slug> --headless --yes
   ```
   - 預設 `--headless`（批次場景通常不需要看瀏覽器）
   - 專案很多時改用 `--projects-file`；失敗的專案會寫入 `failed-projects.txt`，可直接拿它重跑
   - 執行結果直接顯示在 chat
5. **總結回報**：成功幾個 / 已開通幾個 / 失敗幾個（含原因）

**配額批次也適用同模式**——`quota` 子指令同樣支援 `--projects` / `--projects-file`。

**設計原則：**

- **不在 main.py 裡解析 customers.json**——customers.json 是 Claude（我）的資料來源，main.py 只認 `--project` 單一 ID。Claude 在 chat 層做 customer→project 展開，再呼叫 CLI。這樣 main.py 對 clone 下來的人保持簡單，customers.json 純粹是 Kevin 的個人 / 公司資料。
- **多專案用 `--projects`（或 `--projects-file`）一次跑完**，不要逐專案迴圈呼叫——迴圈會讓每個專案各開一次瀏覽器；`--project` 只接單一 ID。
- **--yes 是關鍵**——已經在 chat step 3 確認過，不要讓每個專案再彈確認。
- **失敗繼續**——某個專案失敗（例如 billing 沒綁）不要中斷後面的，最後總結回報。

**新增客戶 / 維護 customers.json：**

當 Kevin 說「**新增客戶 X，專案有 a/b/c**」或「**<客戶> 多了一個專案 <project-id>**」時：

1. Read 現有 `customers.json`
2. Edit 加入新客戶 / append 新專案
3. chat 回報變更摘要
4. 不需要 commit 到 git（檔案已 gitignored）

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

大致由上到下（行號會隨修改漂移，用 Grep 函式名定位）：

| 區塊 | 主要內容 |
|------|---------|
| Imports + .env 設定 | `argparse`, `dotenv`；`BROWSER_*`、`SUBMIT_RETRY_WAITS` |
| 常數 | `CLAUDE_MODELS`, `ROUTING_KEYWORDS`, `ROUTING_PRICING`, `ROUTING_CLI_MAP`, `QUOTA_TYPE_KEYWORDS` |
| 設定與驗證 | `load_config()`, `check_gcloud_auth()`, `get_accessible_projects()`, `select_project()`, `select_models()` |
| Billing / N/A 警示 | `check_billing()`, `_warn_no_billing()`, `_check_all_quotas_na()` |
| 結果與開通偵測 | `OpResult`, `is_model_enabled()`（countTokens 探測）, `print_batch_summary()` |
| 瀏覽器狀態 / 除錯 | `_load_browser_state()`, `_save_browser_state()`, `_debug_screenshot()` |
| API 啟用 | `_enable_single_api()`, `enable_api()` |
| Playwright EULA | `_make_browser_and_page()`, `run_enable_session()`（`auto_fill_eula()` 是單專案包裝）, `_retry_on_submit_error()`, `_fill_form_sequential()`, `_handle_safety_addendum()`, `_terms_checkbox_input()` / `_try_check_terms()`, `_tab_select_dropdown()` |
| 配額查詢/提交 | `get_quota_info()`, `_classify_quota()`, `submit_single_quota()` |
| 互動配額流程 | `quota_flow()`（狀態機 Step 1–4） |
| 批次 | `_find_model_by_slug()`, `run_batch_enable()`, `_quota_one_project()`, `run_batch_quota()` |
| CLI 非互動 | `cmd_enable()`, `cmd_quota()`, `cmd_list_models()`, `parse_args()` |
| 互動選單 / 入口 | `interactive_menu()`, `main()`（`if/elif` 分派） |

### `CLAUDE_MODELS` 格式

Tuple 三元素，**順序不可顛倒**：

```python
(display_name, base_model_dimension, url_slug)
```

| 欄位 | 命名規則 | 範例 |
|------|---------|------|
| `display_name` | 5 世代起 `Claude <家族> <版本>`；4.x 沿用 `Claude <版本> <家族>` | `"Claude Opus 5.5"` / `"Claude 4.7 Opus"` |
| `base_model_dimension` | **4.7 以前**：`anthropic-claude-<家族>-<版本>`（版本獨立配額）<br>**4.8 之後**：`anthropic-claude-<家族>`（家族共用配額） | `"anthropic-claude-opus-4-7"` / `"anthropic-claude-opus"` |
| `url_slug` | publisher API 的 slug（不含前綴、不含日期） | `"claude-opus-5-5"` |

**⚠ 家族共用配額**（GCP 官方文件載明）：Opus 4.8 之後的所有 Opus 版本扣同一個 `anthropic-claude-opus` 配額池，Sonnet / Fable 同理；新版本上線自動沿用家族配額，Cloud Quotas 裡**不會**出現帶版本號的 dimension。base_model 寫錯時配額查詢回 0 筆，配額功能會**靜默失效**（開通不受影響，因為開通用 slug）。

**影響**：多個模型可以指向同一個 base_model；`run_batch_quota` 會自動顯示「此配額為家族共用池，同時適用於…」提示，避免 Kevin 誤以為只改到單一版本。
### 新增模型完整步驟

1. **publisher API 確認上架 + 取得 slug**（見 Part A Step 1 的 curl）
2. **實查 base_model dimension**——列出專案裡所有 Claude 相關 dimension，找新模型對應的是版本層級還是家族層級：
   ```python
   from google.cloud import cloudquotas_v1
   c = cloudquotas_v1.CloudQuotasClient()
   parent = "projects/<proj>/locations/global/services/aiplatform.googleapis.com"
   {dict(d.dimensions).get("base_model") for q in c.list_quota_infos(parent=parent)
    for d in q.dimensions_infos if "claude" in dict(d.dimensions).get("base_model","")}
   ```
   有 `anthropic-<slug>` → 用它（版本獨立）；沒有 → 用家族名 `anthropic-claude-<家族>`。
3. **Edit `CLAUDE_MODELS`** 在最頂端加一列
4. **驗證配額查得到**：`main.get_quota_info(<proj>, <base_model>, strict=False)` 回傳 > 0 筆
5. **驗證 CLI help 自動更新**：
   ```bash
   .venv/bin/python main.py enable --help | grep <new_slug>
   ```
6. **sandbox 端對端測試**：
   ```bash
   .venv/bin/python main.py enable --project <sandbox> --models <new_slug> --yes
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

1. `check_gcloud_auth()` + `load_config()`；`parse_projects_input()` 解析 `--project` / `--projects` / `--projects-file`
2. 解析 `--models`（逗號分隔）→ `_find_model_by_slug()`
3. `run_batch_enable()`：逐專案 `check_billing()`（未綁定記 FAIL、繼續下一個）→ `enable_api()` → `is_model_enabled()`（已開通記 SKIP）
4. 顯示實際要跑的計畫 + `inquirer.confirm()`（除非 `--yes`）；`--headless` → `globals()["BROWSER_HEADLESS"] = True`
5. `run_enable_session()` 整批共用一個瀏覽器 session 執行 EULA → `print_batch_summary()`

#### `cmd_quota` 流程

1. `check_gcloud_auth()`；`parse_projects_input()`；`_find_model_by_slug()` + `ROUTING_CLI_MAP[...]`
2. `run_batch_quota()`：顯示計畫（家族共用配額會列出同池模型）+ 確認
3. 逐專案 `_quota_one_project()`：`check_billing()` → `get_quota_info()` → `_classify_quota()` 分組 → `_check_all_quotas_na()` 為 True 記 SKIP → 依 `--rpm`/`--input-tpm`/`--output-tpm` 比對現值，需要才 `submit_single_quota()`

#### 加新子指令模板

在 `parse_args()` 加 subparser、實作 `cmd_xxx()`、在 `main()` 的 `if/elif` 分派加一個分支。

### Playwright EULA 穩定化

`auto_fill_eula()` 是最脆弱部分——依賴 GCP Console SPA DOM 結構。

**已實作的防護：**

1. `.browser_state/state.json` 持久化 cookies + localStorage
2. **URL 強制 `&hl=en`**（英文介面）+ **精準選擇器 `:text-is("Enable")`（含 `span:text-is`）**（見下「語言與選擇器陷阱」）
3. **30 秒 timeout**（15 秒不夠，4.7 頁面實測 20+ 秒才渲染完）
4. **Tab 鍵循序填表**（`_fill_form_sequential`）比 CSS selector 穩
5. **條款 checkbox 只操作原生 input**（`_terms_checkbox_input` / `_try_check_terms`，見下「Agreements 條款 checkbox」）；Agree 後若跳「Terms not accepted」彈窗，重新勾選再送出，最多 3 次
6. **Advanced AI Safety Addendum 前置關卡**（見下）
7. **失敗自動截圖** `_debug_screenshot()` → `debug_screenshots/`（gitignore）

**⚠ 語言與選擇器陷阱：**

症狀：點「Enable」後被導到 `/marketplace/product/google/aiplatform.googleapis.com`（Agent Platform API 產品頁），逾時失敗。這不是 onboarding 或權限問題，是點錯了元素：

真正根因（兩者疊加）：
1. **Console 介面語言**：Kevin 帳號是繁中，真正的按鈕文字是 **「啟用」**，不是英文 "Enable"。
2. **`:has-text("Enable")` 是子字串比對**：撲空「啟用」後，反而誤中頁面上的英文狀態連結 **「Vertex AI API enabl*ed*」**（一個 `<a>`，點了會導到 marketplace 產品頁）。

修法：
- **URL 加 `&hl=en`** → 強制英文介面，按鈕穩定為 "Enable"、表單/Accept Terms 也全英文（`_fill_form_sequential` 的欄位對照才穩）。
- **選擇器改精準比對**：`button/span/a:text-is("Enable")`（真正的按鈕標籤是 `<span>Enable</span>`，所以**一定要含 `span:text-is`**），保留 `啟用` 當防呆。`:text-is` 完全比對不會誤中「...enabled」。

**教訓**：診斷這類「點了跑去奇怪頁面」時，先在 click 前 log `page.url` + 「即將點擊的按鈕 `inner_text`」，一眼就看出點錯元素。不要急著假設是後端/權限/onboarding 問題。

**`/vertex-ai/` → `/agent-platform/` 導向**：導航後 URL 會自動從 `/vertex-ai/publishers/...` 變 `/agent-platform/publishers/...`（Vertex AI 改名 Agent Platform 的路由），這是正常的、不影響流程。

**EULA 完整流程（兩種變體）：**

```
導航到 model 頁
  → 等 Enable 按鈕 visible（30s）
  → 偵測「Accept Terms」按鈕是否出現：
      ├─ 出現 = 有 Advanced AI Safety Addendum 前置關卡（Fable 5 等新模型）
      │    → _handle_safety_addendum()：
      │        1. 點開「Advanced AI Safety Addendum」連結（開新分頁）→ checkbox 解鎖
      │        2. 勾 checkbox → Accept Terms 啟用
      │        3. 點 Accept Terms → Enable 從 disabled 變可點
      │    （接受後「仍會」進入下面的商業資訊表單，不是取代）
      └─ 不出現 = 舊模型，無前置關卡
  → 點 Enable
  → _fill_form_sequential()：商業資訊表單 → Next → 勾 Terms → Agree
```

**Advanced AI Safety Addendum 關鍵點：**

- **偵測訊號用「Accept Terms 按鈕是否 visible」**，不要解析 Enable 的 disabled 狀態（Material 按鈕的 disabled 可能是 `disabled` 屬性／`aria-disabled`／CSS class，不可靠）。
- **連結必須先點開**（target=`_blank` 開新分頁）checkbox 才解鎖——用 `context.expect_page()` 捕捉新分頁再 close。這是實測確認的硬性順序，不是可跳過的閱讀步驟。
- **法律份量較重**：勾選文字寫明「代表組織同意、有權約束 Customer」。Kevin 已授權工具「自動接受」（2026-06）。若未來換人／換組織使用，這個自動接受的預設值要重新確認。
- **detect-and-branch 設計**：同一段 code 同時相容「有關卡的新模型」與「無關卡的舊模型」，靠 runtime 偵測，不 hardcode 哪個 slug 需要。新模型若也加這道關卡，自動就支援。

**如果 EULA 頁面結構變動：**

| 症狀 | 調查方向 |
|------|---------|
| 點 Enable 後跑到 marketplace 產品頁 | **選擇器誤中「Vertex AI API enabled」狀態連結**——確認 `hl=en` 有生效、選擇器用 `:text-is` 精準比對（見上「語言與選擇器陷阱」） |
| Enable 按鈕找不到 | `page.screenshot()` 看實際頁面；確認 `hl=en` 生效（中文介面按鈕是「啟用」）；用 `:text("Enable")` dump 所有含字元素看真正 tag（可能是 `<span>`） |
| 表單欄位順序變動 | Tab 循序會錯亂——重新確認順序調 `_fill_form_sequential` |
| 下拉選單不展開 | 調 `_tab_select_dropdown` 的 key 序列（ArrowDown/Enter） |
| Terms checkbox 點不到 / 勾選時跳出條款分頁 | 見下方「Agreements 條款 checkbox」；確認 `_terms_checkbox_input` 仍抓得到 `mat-checkbox … input[type=checkbox]` |
| Accept Terms 點了沒反應 | 確認連結有先點開（checkbox 才解鎖）；檢查 `_handle_safety_addendum` 的 `context.expect_page` 有無捕捉到新分頁 |
| 連續開通時跳「An error occurred while submitting the request」 | Marketplace 拒絕訂單，見下方「Marketplace 送出失敗」；已由 `_retry_on_submit_error` 自動等待重試 |
| 新模型 Enable 一直 disabled | 多半是 Addendum 沒接受成功——non-headless 觀察 `_handle_safety_addendum` 卡在哪步 |

Debug 時先 non-headless + `BROWSER_SLOW_MO=1500` 慢速觀察。

**Marketplace 送出失敗（2026-09）**

- 開通 partner model = 在 Marketplace 下一筆訂單（questionnaire URL 帶 `mp=anthropic/...cloudpartnerservices.goog`）。錯誤訊息明講「Marketplace & Agent Platform API」。
- 現象：手動連開到第 2 個就失敗；同仁用自己的 Chrome 開 3 專案 × 5 模型後，第 4 個專案只成功 1 個。**換 session 仍發生 → 伺服器端限制，不是瀏覽器 session 問題。**
- **成因未完全確認**。查到 Cloud Commerce Consumer Procurement API 有 `WriteRequestsPerMinutePerProjectPerUser = 10`，但工具約 1 模型 / 分鐘、手動更慢，單靠這個配額解釋不了。另一個可能是前一筆訂單仍在處理中就送下一筆被拒。**不要跟 Kevin 講得像已確定。**
- 目標專案上該 API 是 DISABLED 但開通照樣成功 → Console 下單不扣目標專案的配額，限制可能跟著使用者走、跨專案累計。
- 實作：Next 與 Agree 兩個送出點之後都呼叫 `_retry_on_submit_error()`：偵測提示 → 關閉 → 等 `SUBMIT_RETRY_WAITS`（預設 30/60/120 秒）→ 先 `is_model_enabled` 確認是否已生效（避免重複下單）→ 重按同一顆按鈕。以本機模擬頁驗證過四種情境（無錯 / 重試成功 / 用盡 / 等待中已生效），**尚未在真實觸發的情況下驗證**。

**Agreements 條款 checkbox（2026-09 修正）**

- 實際 DOM（跑到 Agreements 頁停下 dump 得知）：外層 `<mat-checkbox>` 是 1152×124 的大區塊，包含整段條款文字與兩個連結（Google Cloud Marketplace ToS、Anthropic ToS）；真正的勾選框是裡面 28×28、**可見**的 `<input type="checkbox" class="mdc-checkbox__native-control">`。
- 舊邏輯點外層 mat-checkbox 的中心 → 點到條款連結開新分頁、沒勾到 → 判定「似乎未勾選」→ 強制點擊全部元素（又點一次外層 → 第二個條款分頁，再點到 input 才勾起來）。這就是每次都出現「checkbox 似乎未勾選」與兩個 `terms/marketplace/launcher` 分頁的原因。
- 新邏輯：`_terms_checkbox_input()` 取原生 input → `check()`；失敗時用 `dispatch_event("click")` 對 input 本身派送事件。**不可用 `click(force=True)`**，那是座標點擊，會點到蓋在上面的元素（離線測試時就被頂端工具列蓋住過）。勾選狀態用 `is_checked()` 讀原生值，不猜 CSS class。
- Addendum 前置關卡的 checkbox（`_handle_safety_addendum`）是另一段邏輯，仍點 `mat-checkbox:has-text("By checking this box")`；Fable 5 實測可用，未改。

**已試過並移除：attach 瀏覽器模式（2026-09）**

曾加入 `BROWSER_MODE=attach`（CDP 接管 Chrome），Kevin 試用後要求移除：「多此一舉還沒有幫助」。原因是 Chrome 136+ 禁止對預設設定檔開 remote debugging，Chrome 150+ 連 `chrome://inspect/#remote-debugging` 對預設設定檔也接不上，所以 attach 只能接「另外啟動的獨立 Chrome」，無法在使用者日常的 Chrome 上操作，跟預設 Chromium 差別不大。**不要再提議 CDP / attach 類方案**；若真要在日常 Chrome 操作，只剩做成 Chrome 擴充功能，屬重新設計。

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

1. **Syntax / argparse**：`.venv/bin/python main.py --help`, `enable --help`, `quota --help`
2. **Error path**：`.venv/bin/python main.py enable --project x --models nonexistent --yes`
3. **Dry-run 等級**：手動呼叫 `_classify_quota()` 測分類
4. **端對端**：sandbox 專案實測

### 修改檢查清單

改動前問自己：

- [ ] 是否需要改 `CLAUDE_MODELS`？
- [ ] 是否影響 CLI help 輸出？（`.venv/bin/python main.py --help` 檢查）
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
| Enable 按鈕找不到 | 已開通 / 頁面結構變動 / slug 錯 | 見 Part B「如果 EULA 頁面結構變動」表 |
| 「Terms of service not accepted」彈窗 | 條款 checkbox 沒勾到 | 工具會重新勾選再送出（最多 3 次）；持續發生見「Agreements 條款 checkbox」 |
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
