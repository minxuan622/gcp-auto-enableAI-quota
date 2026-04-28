# GCP Vertex AI Claude Model Manager

> 團隊用 CLI 工具，自動化管理 GCP Vertex AI 上 Claude 模型的 **環境開通** 與 **配額提升**。
>
> 一個指令搞定：啟用 API、填寫 EULA、查詢配額、送出提升申請。

---

## 功能總覽

| 功能 | 說明 |
|------|------|
| **環境開通** | 自動啟用 Vertex AI API + Cloud Quotas API，透過 Playwright 自動填寫 Model Garden EULA 表單並完成同意 |
| **配額提升** | 查詢 RPM / Input TPM / Output TPM 配額現況，分別設定目標值並透過 Cloud Quotas API 送出提升申請 |
| **批次多專案**（v1.1）| 單次執行處理多個 GCP 專案：互動模式 checkbox 多選、CLI 支援 `--projects` / `--projects-file`；已開通 / 已達目標自動跳過 |
| **模型狀態 Matrix**（v1.1）| `list-models` 子指令可產出「專案 × 模型」開通狀態矩陣，一眼看出各環境哪些模型已啟用 |
| **Billing 檢查** | 操作前自動確認專案是否已綁定帳單帳戶，未綁定時給予明確提示與連結 |
| **瀏覽器狀態管理** | 自動儲存 / 載入 Google 登入狀態，首次登入後免重複驗證；批次模式整段共用一個 session |
| **返回上一步** | 所有互動式選單皆支援「返回上一步」，選錯不必從頭來過 |

### 支援模型

| 模型 | URL slug | GCP base_model ID |
|------|----------|-------------------|
| Claude 4.7 Opus   | `claude-opus-4-7`   | `anthropic-claude-opus-4-7` |
| Claude 4.6 Opus   | `claude-opus-4-6`   | `anthropic-claude-opus-4-6` |
| Claude 4.6 Sonnet | `claude-sonnet-4-6` | `anthropic-claude-sonnet-4-6` |
| Claude 4.5 Sonnet | `claude-sonnet-4-5` | `anthropic-claude-sonnet-4-5` |
| Claude 4.5 Opus   | `claude-opus-4-5`   | `anthropic-claude-opus-4-5` |
| Claude 4.5 Haiku  | `claude-haiku-4-5`  | `anthropic-claude-haiku-4-5` |

> URL slug 用於 CLI 子指令的 `--models` / `--model` 參數。

### 支援 Routing 策略

| 策略 | `--routing` 值 | 溢價 | 說明 |
|------|---------------|------|------|
| **Global**          | `global`   | **無** | 全球動態路由，最高可用性（推薦） |
| **US Multi-region** | `us`       | +10% | 美國區域內動態路由 |
| **EU Multi-region** | `eu`       | +10% | 歐盟區域內動態路由 |
| **Regional**        | `regional` | +10% | 綁定單一特定區域 |

---

## 前置需求

| 項目 | 說明 |
|------|------|
| **Python** | 3.10 以上 |
| **Google Cloud SDK** | 需安裝 `gcloud` CLI（[安裝說明](https://cloud.google.com/sdk/docs/install)） |
| **GCP 權限** | 對目標專案需具備 **Owner** 或同時擁有 **Service Usage Admin** + **Quota Administrator** 角色 |
| **Billing** | 目標專案必須已綁定帳單帳戶（工具會自動檢查並提示） |

---

## 快速開始

### Step 1：安裝

腳本會自動建立 Python 虛擬環境（`.venv`）、安裝相依套件與 Playwright Chromium，並建立設定檔。

**Mac / Linux：**

```bash
chmod +x setup.sh
./setup.sh
```

**Windows：**

```powershell
.\setup.bat
```

<details>
<summary>手動安裝（不使用腳本）</summary>

```bash
# 建立並啟用虛擬環境
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 安裝 Python 套件
pip install -r requirements.txt

# 安裝 Playwright Chromium
playwright install chromium

# 建立設定檔
cp config.json.example config.json
cp .env.example .env
```

</details>

### Step 2：GCP 授權（只需一次）

```bash
gcloud auth application-default login
```

瀏覽器會跳出 Google 登入頁面，登入後會在本機產生 Application Default Credentials（ADC），工具會自動使用。

> 如果出現 quota project 警告，執行：
> ```bash
> gcloud auth application-default set-quota-project <YOUR_PROJECT_ID>
> ```

### Step 3：填寫設定檔

編輯 `config.json`，填入 EULA 表單所需的企業資訊：

```jsonc
{
  "eula_form": {
    "business_name": "你的公司名稱",        // 必填
    "business_website": "https://...",       // 必填
    "contact_email": "you@company.com",      // 必填
    "business_hq": "Taiwan",                 // 下拉選單：公司總部所在地
    "industry": "Customer Service",          // 下拉選單：產業別
    "intended_users": "Internal employees and external users",  // 下拉選單
    "use_cases": "描述你的使用情境",          // 必填
    "has_additional_requirements": "No",     // Yes 或 No
    "additional_requirements_detail": ""     // 若上方選 Yes，填寫補充說明
  },
  "defaults": {
    "region": "us-east5"
  }
}
```

> 啟動時工具會驗證 `business_name`、`business_website`、`contact_email`、`use_cases` 四個必填欄位，缺少時會提示補齊。

### Step 4：執行

```bash
# Mac / Linux
./run.sh

# Windows
run.bat

# 或直接執行
source .venv/bin/activate && python main.py
```

---

## 使用流程

### 主選單

```
? 請選擇操作：
> 🚀 環境開通（啟用 API + EULA 自動填表）
  📊 配額管理（查詢與提升配額）
  🗑️  清除瀏覽器登入狀態
  ❌ 離開
```

### 環境開通（支援多專案 checkbox 多選）

```
多選專案（空白鍵選取）→ 選擇模型（可多選）
→ 逐專案預檢：Billing / API 狀態 / 已開通模型（自動標記 SKIP）
→ 顯示實際要跑的 (專案 × 模型) 組合並確認
→ Playwright 開啟瀏覽器（整段共用一個 session）
→ 逐一導航 Model Garden：點擊 Enable → 填寫 EULA → Next → 勾選 Terms → Agree
→ 最後顯示批次結果 table（Project / Model / Status / Note）
```

- 首次使用會開啟瀏覽器讓你手動登入 Google 帳號，之後登入狀態自動保存
- 若「Terms of service have not been accepted」彈窗出現，工具會自動關閉並重試（最多 3 次）
- 自動填寫使用 Tab 鍵循序導航，穩定度高於 CSS 選擇器
- **已開通的模型自動跳過**：透過查 Cloud Quotas 判斷，若已有配額 = 已同意 EULA
- 批次執行若有失敗，自動寫 `failed-projects.txt`，可直接 `--projects-file failed-projects.txt` 重跑

### 配額提升（支援多專案 checkbox 多選）

```
多選專案 → 選擇模型 → 查第一個可用專案 quotas 作為 UI 參考值
→ 選擇 Routing（Global / US / EU / Regional）— 套用到所有選取專案
→ 輸入 RPM / Input TPM / Output TPM 目標（一次套用所有專案）
→ 逐專案送出：Billing 未綁定 / 未開通 / 當前 ≥ 目標 → 自動 SKIP
→ 批次結果 table（含每筆 APPROVED / PENDING / DENIED 狀態）
```

> **Global vs US Multi-region**：兩者是不同的 quota metric——Global 無溢價、US Multi-region 有 10% 溢價。工具會依 metric 名稱前綴（`global_*` vs `us_multi_region_*`）正確分類。

**配額申請結果說明：**

| 狀態 | 說明 |
|------|------|
| **APPROVED** | 已核准，立即生效 |
| **PENDING** | 已送出，超出自動核准額度，需等待 Google 人工審核（24-48 小時） |
| **DENIED** | 被拒絕，可能超過區域硬性上限，請嘗試較小數值 |

**安全機制：**

- 若配額全部顯示 N/A，代表模型尚未開通，工具會提示先執行「環境開通」
- 若專案未綁定 Billing，會顯示紅色警告面板與 Console 連結
- 每次輸入前顯示 5 倍安全閾值，超過會以黃/紅色警示

---

## 非互動模式（CLI 子指令）

工具支援 **non-interactive** 模式，直接用子指令一次完成操作——適合腳本化、遠端執行，或搭配 AI agent 自動化。

### `enable` — 開通模型

```bash
# 單一專案 + 單一模型
python main.py enable --project kevin-480608 --models claude-opus-4-7

# 單一專案 + 多個模型（逗號分隔）
python main.py enable --project kevin-480608 \
                      --models claude-opus-4-7,claude-sonnet-4-6

# 多個專案（逗號分隔）× 多個模型 —— 批次模式
python main.py enable --projects proj-a,proj-b,proj-c \
                      --models claude-opus-4-7,claude-sonnet-4-6

# 從檔案讀取專案清單（一行一個，`#` 開頭視為註解）
python main.py enable --projects-file projects.txt \
                      --models claude-opus-4-7

# 遠端執行（headless 模式）+ 全自動跳過確認
python main.py enable --projects-file projects.txt \
                      --models claude-opus-4-7 --headless --yes

# 失敗專案重跑：工具會自動產生 failed-projects.txt
python main.py enable --projects-file failed-projects.txt \
                      --models claude-opus-4-7
```

**專案輸入（三擇一，互斥）：**

| 參數 | 格式 | 範例 |
|------|------|------|
| `--project` | 單一專案 ID | `--project kevin-480608` |
| `--projects` | 逗號分隔多個專案 ID | `--projects proj-a,proj-b,proj-c` |
| `--projects-file` | 文字檔（一行一個 ID，`#` 為註解） | `--projects-file projects.txt` |

**其他參數：**

| 參數 | 必填 | 說明 |
|------|------|------|
| `--models`  | ✓ | 模型 URL slug（支援多個，逗號分隔） |
| `--headless` |   | 以 headless 模式跑瀏覽器（預設讀 `BROWSER_HEADLESS` 環境變數） |
| `-y`, `--yes` |   | 跳過確認提示 |

**批次行為：**

- 逐專案預檢：Billing / API 狀態 / 已開通模型（透過查 Cloud Quotas 判斷）
- 已開通的 (專案 × 模型) 組合顯示 `⏭ SKIP (已開通)`，不會重跑
- 所有專案共用同一個 Playwright session，免重複登入
- 執行結束顯示結果 table；若有失敗，寫 `failed-projects.txt` 方便重跑

### `quota` — 提升配額

```bash
# 單一專案：提升 Global 策略下的 RPM / TPM
python main.py quota --project kevin-480608 \
                     --model claude-opus-4-7 \
                     --routing global \
                     --rpm 100 --input-tpm 500000 --output-tpm 100000

# 只提升 RPM（其他不動）
python main.py quota --project kevin-480608 \
                     --model claude-opus-4-7 \
                     --routing global --rpm 200

# 批次多專案：相同 model / routing / 目標值套用到所有專案
python main.py quota --projects proj-a,proj-b,proj-c \
                     --model claude-opus-4-7 \
                     --routing global \
                     --rpm 100 --input-tpm 500000

# 從檔案讀取專案清單 + 全自動
python main.py quota --projects-file projects.txt \
                     --model claude-opus-4-7 \
                     --routing global --rpm 200 --yes
```

**專案輸入（三擇一，互斥）：**

| 參數 | 格式 | 範例 |
|------|------|------|
| `--project` | 單一專案 ID | `--project kevin-480608` |
| `--projects` | 逗號分隔多個專案 ID | `--projects proj-a,proj-b` |
| `--projects-file` | 文字檔（一行一個 ID，`#` 為註解） | `--projects-file projects.txt` |

**其他參數：**

| 參數 | 必填 | 說明 |
|------|------|------|
| `--model`   | ✓ | 模型 URL slug（只能一個） |
| `--routing` | ✓ | `global` / `us` / `eu` / `regional` |
| `--rpm` |    | 目標 RPM 上限（可省略，代表不動此項） |
| `--input-tpm` |    | 目標 Input TPM 上限 |
| `--output-tpm` |    | 目標 Output TPM 上限 |
| `-y`, `--yes` |    | 跳過確認提示 |

> 至少要指定 `--rpm` / `--input-tpm` / `--output-tpm` 其中一項。

**批次行為：**

- 逐專案送出；以第一個可用專案的 quotas 作為 UI 參考值與 5x 安全閾值提示
- 專案未綁 Billing / 模型未開通 / 當前值 ≥ 目標值 → 自動 `⏭ SKIP`
- 每筆申請顯示 `APPROVED` / `PENDING` / `DENIED` 結果
- 失敗的專案同樣寫入 `failed-projects.txt`

### `list-models` — 列出支援模型 / 開通狀態 Matrix

```bash
# 列出所有支援的模型（URL slug、base_model ID）
python main.py list-models

# 檢查單一專案各模型開通狀態
python main.py list-models --project kevin-480608

# 多專案 matrix：一眼看出哪些專案缺哪個模型
python main.py list-models --projects proj-a,proj-b,proj-c

# 從檔案讀取
python main.py list-models --projects-file projects.txt
```

輸出範例（matrix 模式）：

```
模型 \ 專案            proj-a  proj-b  proj-c
claude-opus-4-7         ✅      ✅      ❌
claude-opus-4-6         ✅      ❌      ❌
claude-sonnet-4-6       ✅      ✅      ✅
...
```

- ✅ 已開通（任一 routing 有配額）
- ❌ 未開通
- ⚠  無法查詢（權限不足 / Billing 未綁）

**專案參數與 `enable` / `quota` 一致**：`--project` / `--projects` / `--projects-file` 三擇一，皆可省略（省略則只列模型清單，不查狀態）。

### 互動 vs 非互動

| 情境 | 建議模式 |
|------|---------|
| 初次使用、想看選單 | 互動模式（不帶子指令） |
| 已知要開哪個專案 / 模型 | 非互動 `enable` |
| 已知目標配額數值 | 非互動 `quota` |
| 想一覽多專案開通狀態 | 非互動 `list-models --projects-file ...` |
| 一次批次處理多專案 | `--projects` 或 `--projects-file` |
| 遠端 / 腳本 / AI agent | 非互動 + `--headless --yes` |

**首次使用需先以互動模式登入 Google**（建立 `.browser_state/`），之後 headless 模式才能運作。

---

## 設定檔

### `config.json`（必填）

EULA 表單欄位設定。`config.json.example` 已提供範本，複製後修改即可。

### `.env`（選填）

瀏覽器行為與預設值，一般不需修改：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `CONFIG_PATH` | `config.json` | 設定檔路徑 |
| `BROWSER_HEADLESS` | `false` | `true` = 無頭模式（不顯示瀏覽器視窗） |
| `BROWSER_SLOW_MO` | `500` | 自動化操作間隔（毫秒），方便觀察流程 |
| `BROWSER_STATE_DIR` | `.browser_state` | 瀏覽器登入狀態儲存目錄 |
| `DEFAULT_REGION` | `us-east5` | 預設區域（可在選單中覆蓋） |

### `customers.json`（選填，搭配 Claude Code Skill）

把「客戶名稱」對應到一組 GCP project IDs，搭配 `.claude/skills/vertex-ai-claude-enabler/SKILL.md`，
讓你在 Claude Code 對話中說「幫 **RK** 的所有專案開 Claude 5.0」時，AI 能自動展開為多個 `enable` 指令批次執行。

**啟用方式：**

```bash
cp customers.example.json customers.json
# 編輯 customers.json 填入實際客戶與專案
```

**格式：**

```json
{
  "customers": {
    "RK": {
      "aliases": ["rk"],
      "projects": ["project-id-1", "project-id-2"],
      "notes": "選填備註"
    }
  }
}
```

`aliases` 提供模糊比對（例如「ghyy」「光環」都能匹配同一客戶）。`customers.json` 已在 `.gitignore`，
含商業資料不會推上 GitHub；`customers.example.json` 為公開範本。

> **注意**：本檔案的解析發生在 Claude Code 對話層（由 SKILL.md 引導），不是在 `main.py` 內。
> CLI 子指令本身仍然只接受單一 `--project`，由 Claude 在 chat 展開為迴圈呼叫。

---

## 專案結構

```
gcp-claude-manager/
├── main.py                         # 主程式（CLI 互動介面 + CLI 子指令）
├── config.json.example             # EULA 表單範本
├── customers.example.json          # 客戶 → 專案映射範本（搭配 Claude Code Skill）
├── .env.example                    # 環境變數範本
├── requirements.txt                # Python 相依套件
├── setup.sh / setup.bat            # 一鍵安裝腳本（Mac / Windows）
├── run.sh / run.bat                # 啟動腳本（Mac / Windows）
├── .claude/skills/                 # Claude Code Skill（cwd 在本專案時自動載入）
│   └── vertex-ai-claude-enabler/
│       └── SKILL.md
└── .gitignore
```

---

## 需要啟用的 GCP API

工具會自動啟用以下 API（需要 Service Usage Admin 權限）：

| API | 用途 |
|-----|------|
| `aiplatform.googleapis.com` | Vertex AI — 模型開通與使用 |
| `cloudquotas.googleapis.com` | Cloud Quotas — 配額查詢與提升申請 |

---

## 技術元件

| 套件 | 用途 |
|------|------|
| [google-auth](https://pypi.org/project/google-auth/) | Application Default Credentials 驗證 |
| [google-cloud-service-usage](https://pypi.org/project/google-cloud-service-usage/) | 啟用 GCP API |
| [google-cloud-resource-manager](https://pypi.org/project/google-cloud-resource-manager/) | 列出可存取的 GCP 專案 |
| [google-cloud-quotas](https://pypi.org/project/google-cloud-quotas/) | 查詢與提升配額（Cloud Quotas SDK） |
| [Playwright](https://playwright.dev/python/) | 瀏覽器自動化（EULA 表單填寫） |
| [Rich](https://rich.readthedocs.io/) | 終端機美化輸出（表格、Panel、顏色） |
| [InquirerPy](https://inquirerpy.readthedocs.io/) | 互動式 CLI 選單（select、checkbox、number） |

---

## 常見問題

<details>
<summary><b>執行時出現「Application Default Credentials 尚未設定」</b></summary>

請先執行 GCP 授權：

```bash
gcloud auth application-default login
```

如果出現 quota project 警告：

```bash
gcloud auth application-default set-quota-project <YOUR_PROJECT_ID>
```

</details>

<details>
<summary><b>啟動時報錯「config.json 缺少必填欄位」</b></summary>

編輯 `config.json`，確認 `business_name`、`business_website`、`contact_email`、`use_cases` 四個欄位皆已填入值。

</details>

<details>
<summary><b>出現「專案尚未綁定 Billing Account」</b></summary>

Vertex AI Claude 模型需要計費才能使用。前往工具提示的 Console 連結綁定帳單帳戶，或請專案管理員協助設定。

</details>

<details>
<summary><b>配額查詢顯示全部 N/A</b></summary>

代表該模型尚未在此專案開通。請先回到主選單執行「環境開通」完成 EULA 同意，之後配額才會出現具體數值。

</details>

<details>
<summary><b>自動填表時 Enable 按鈕找不到</b></summary>

可能該模型已經在此專案中開通，或 GCP Console 頁面結構有變動。工具會顯示提示，可手動至 [Model Garden](https://console.cloud.google.com/vertex-ai/model-garden) 確認。

</details>

<details>
<summary><b>出現「Terms of service have not been accepted」彈窗</b></summary>

Angular Material 的 checkbox 元件有時點擊未生效。工具會自動偵測此彈窗、關閉、重新勾選 checkbox 並重試（最多 3 次）。若仍失敗，請在瀏覽器中手動勾選 checkbox 再點 Agree。

</details>

<details>
<summary><b>想重新登入 Google 帳號</b></summary>

在主選單選擇「清除瀏覽器登入狀態」，下次開通時會要求重新登入。或手動刪除 `.browser_state/` 目錄。

</details>

<details>
<summary><b>配額提升申請顯示 PENDING</b></summary>

申請的數值超出 5 倍自動核准閾值，已進入 Google 人工審核流程，通常需等待 24-48 小時。可至 [GCP Console 配額頁面](https://console.cloud.google.com/apis/api/aiplatform.googleapis.com/quotas) 查看審核狀態。

</details>

<details>
<summary><b>選錯專案或模型怎麼辦</b></summary>

所有選單都支援「返回上一步」。選擇專案、模型、Routing 策略時，清單最後一項都有「↩ 返回上一步」選項。確認送出前選 N 也可以重新操作。

</details>

---

## License

Private — Internal use only.
