# GCP Vertex AI Claude Model Manager

> CLI 工具，自動化管理 GCP Vertex AI（現稱 Agent Platform）上 Anthropic Claude 模型的 **環境開通（EULA）** 與 **配額提升**。
>
> 設計原則：**能用官方 API 就用 API**，僅在唯一沒有公開 API 的環節（EULA 接受）以瀏覽器自動化精準重現 Console 操作。支援單一 / 批次 / 多客戶專案，並可由 Claude Code 以自然語言驅動。

---

## 為什麼用「模擬控制台操作」來開通模型？

開通 Vertex AI 上的 Anthropic Claude 模型，核心動作是**接受該模型的 EULA**（部分新模型還多了一道 Advanced AI Safety Addendum）。這一步**沒有公開 API 可以呼叫**，原因如下：

- Claude 屬於 GCP 的 **Partner Model**，不走 Hugging Face / 開源模型那套 `modelGardenEula` 接受機制——實測對 Claude 呼叫 `modelGardenEula:check`，回傳的接受狀態欄位是空的，代表這套 API 對 partner model 不適用。
- EULA 接受需要填一張多欄位的企業資訊表單（公司名稱 / 網站 / 聯絡人 / 產業 / 使用情境……），這張表單目前只存在於 Console UI，沒有對應的 REST / SDK endpoint 接收這些結構化資料。
- `gcloud` 與 Terraform 目前也沒有「接受 Claude 模型 EULA」的指令或 resource。

換句話說，**這一步在官方層面就是只能在 Console 點**。因此本工具用 Playwright 驅動瀏覽器，精準重現人工在 Console 的操作流程（導航 → 接受 Addendum → Enable → 填表 → Agree），把這條唯一可行的手動路徑自動化。

因此本工具採「**API 優先、EULA 例外**」的混合設計：凡有官方 API 的環節都走 API，僅 EULA 接受改用瀏覽器自動化。這讓工具能同時達成 **批次開通、遠端執行、由 AI agent 一句話開好**。完整的處理管線與各階段技術見下節。

---

## 運作原理（技術架構）

「開通一個模型」是一條處理管線。除了唯一沒有公開 API 的 EULA 接受環節走瀏覽器自動化外，其餘皆使用官方 SDK / REST API：

```
身份驗證 → 啟用必要 API → Billing 檢查 → 偵測開通狀態
   → （未開通才）EULA 開通 → 配額查詢 / 提升 → 結果回報
        └─ 官方 API 路徑 ─────────┘  └ 瀏覽器 ┘  └─── API ───┘
```

### 各階段採用的技術

| 階段 | 做什麼 | 採用技術 |
|------|--------|---------|
| **身份驗證** | 取得呼叫 GCP 的憑證 | Application Default Credentials（ADC），透過 `google-auth`；與 `gcloud` CLI 登入分離 |
| **啟用必要 API** | 確保 `aiplatform`（Agent Platform）與 `cloudquotas` 已啟用 | Service Usage SDK，冪等啟用（已啟用則略過） |
| **Billing 檢查** | 確認專案已綁定帳單帳戶 | Cloud Billing REST API，未綁定時中止並提示 |
| **偵測開通狀態** | 判斷模型是否已接受 EULA | 對 publisher model 發 `:countTokens` 探測：`404` = 未開通、`400` = 已開通。此訊號直接反映 Partner Model 的真實可存取狀態，較「以配額預設值推測」更可靠 |
| **EULA 開通** | 接受模型條款並啟用 | Playwright 驅動瀏覽器重現 Console 流程（見下節） |
| **配額查詢 / 提升** | 讀取與調整 RPM / TPM | Cloud Quotas SDK；查詢走 REST（回應結構直觀）、送出走 SDK（型別安全、錯誤處理完整） |
| **Routing 分類** | 區分 Global / US / EU / Regional | 依 quota metric 名稱前綴分類（`global_*` / `us_multi_region_*` …），Global 無溢價 |
| **結果回報** | 逐項狀態與批次總表 | 統一的 `OpResult` 結果模型 + Rich 表格輸出；失敗清單寫入 `failed-projects.txt` 供重跑 |

### EULA 開通：以瀏覽器自動化重現 Console 操作

Anthropic Claude 屬於 Partner Model，其 EULA 與 Advanced AI Safety Addendum 的接受沒有公開 API（見上節）。此環節以 Playwright 精準重現人工在 Console 的操作，並以下列機制確保流程穩定、可預期、可稽核：

- **鎖定介面語言**：導航時附加 `hl=en`，使按鈕、表單欄位與條款文字固定為英文，讓後續的元素定位與欄位對照有一致、可預期的基準（Console 會依帳號語言在地化，同一顆按鈕在不同語言下文字不同）。
- **精準元素定位**：以完全文字比對（`:text-is`）定位操作元件，避免與頁面上文字相近的狀態標籤混淆。
- **前置同意流程**：部分新模型在啟用前需先接受 Advanced AI Safety Addendum；工具會自動偵測並完成（開啟條款連結 → 勾選 → Accept Terms → 解鎖 Enable），無此關卡的模型則自動略過偵測。
- **穩健填表**：企業資訊表單以鍵盤 Tab 循序填寫，降低對頁面 DOM 結構變動的敏感度；條款 checkbox 以多重策略重試確保勾選生效。
- **登入狀態持久化**：首次登入後保存於 `.browser_state/`，後續免重複登入；批次作業整段共用同一個瀏覽器 session。
- **可稽核性**：操作異常時自動截圖至 `debug_screenshots/`，便於事後診斷。

---

## 功能總覽

| 功能 | 說明 |
|------|------|
| **環境開通** | 自動啟用 Vertex AI API + Cloud Quotas API，透過 Playwright 自動填寫 Model Garden EULA 表單並完成同意 |
| **配額提升** | 查詢 RPM / Input TPM / Output TPM 配額現況，分別設定目標值並透過 Cloud Quotas API 送出提升申請 |
| **批次多專案**| 單次執行處理多個 GCP 專案：互動模式 checkbox 多選、CLI 支援 `--projects` / `--projects-file`；已開通 / 已達目標自動跳過 |
| **模型狀態 Matrix**| `list-models` 子指令可產出「專案 × 模型」開通狀態矩陣，一眼看出各環境哪些模型已啟用 |
| **Billing 檢查** | 操作前自動確認專案是否已綁定帳單帳戶，未綁定時給予明確提示與連結 |
| **瀏覽器狀態管理** | 自動儲存 / 載入 Google 登入狀態，首次登入後免重複驗證；批次模式整段共用一個 session |
| **返回上一步** | 所有互動式選單皆支援「返回上一步」，選錯不必從頭來過 |

### 支援模型

| 模型 | URL slug | 配額 base_model | 配額池 |
|------|----------|-----------------|--------|
| Claude Opus 5.5   | `claude-opus-5-5`   | `anthropic-claude-opus`       | Opus 家族共用 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | `anthropic-claude-sonnet`     | Sonnet 家族共用 |
| Claude Fable 5.1  | `claude-fable-5-1`  | `anthropic-claude-fable`      | Fable 家族共用 |
| Claude Opus 5     | `claude-opus-5`     | `anthropic-claude-opus`       | Opus 家族共用 |
| Claude Fable 5    | `claude-fable-5`    | `anthropic-claude-fable`      | Fable 家族共用 |
| Claude Sonnet 5   | `claude-sonnet-5`   | `anthropic-claude-sonnet`     | Sonnet 家族共用 |
| Claude 4.8 Opus   | `claude-opus-4-8`   | `anthropic-claude-opus`       | Opus 家族共用 |
| Claude 4.7 Opus   | `claude-opus-4-7`   | `anthropic-claude-opus-4-7`   | 版本獨立 |
| Claude 4.6 Opus   | `claude-opus-4-6`   | `anthropic-claude-opus-4-6`   | 版本獨立 |
| Claude 4.6 Sonnet | `claude-sonnet-4-6` | `anthropic-claude-sonnet-4-6` | 版本獨立 |
| Claude 4.5 Opus   | `claude-opus-4-5`   | `anthropic-claude-opus-4-5`   | 版本獨立 |
| Claude 4.5 Haiku  | `claude-haiku-4-5`  | `anthropic-claude-haiku-4-5`  | 版本獨立 |

> URL slug 用於 CLI 子指令的 `--models` / `--model` 參數。清單定義於 `main.py` 的 `CLAUDE_MODELS`；新模型發布時在此新增一列即可（`list-models` 與互動選單會自動同步）。
>
> **配額池分兩代**：Claude 4.7 以前每個版本各有獨立配額；**4.8 之後同家族共用一個配額池**（GCP 的設計，新版本上線自動沿用家族既有配額）。因此對 Opus 5.5 提升配額，Opus 4.8 / 5 也會一併受益；工具在提升家族共用配額時會顯示提示。

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

> **Windows 前置提醒**：`setup.bat` 會先檢查環境，缺少時會自動開啟對應下載頁並引導你安裝：
>
> 1. **Python 3.10+**：Windows 內建的 `python` 可能是舊版（如 3.8），版本太舊會被擋下。請至 [python.org](https://www.python.org/downloads/) 安裝 **3.12 / 3.13**，安裝時務必勾選 **「Add Python to PATH」**。
> 2. **Google Cloud SDK（gcloud）**：請使用 [官方安裝程式](https://cloud.google.com/sdk/docs/install)（`winget` 版本目前已停用，請勿使用）。
> 3. 安裝完 Python 或 gcloud 後，**請開一個全新的 PowerShell 視窗**再重新執行 `.\setup.bat`（舊視窗讀不到新的 PATH）。
>
> **若 PowerShell 出現「未經數位簽署，無法載入」**（執行 `gcloud` 時），執行一次以下指令放寬執行原則即可：
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

<details>
<summary>手動安裝（不使用腳本）</summary>

```bash
# 1. 用系統 Python 建立虛擬環境（只此一次）
python3 -m venv .venv

# 2. 進虛擬環境
#    Mac / Linux:
source .venv/bin/activate
#    Windows:
#    .venv\Scripts\activate

# 3. 此後 pip / python 都自動指向 venv（不會污染系統 Python）
pip install -r requirements.txt
playwright install chromium

# 4. 建立設定檔
cp config.json.example config.json
cp .env.example .env
```

> **重要區分**：`python3 -m venv` 是用**系統 Python** 建虛擬環境，只此一次。
> 之後執行 `main.py` 時，必須用 `.venv/bin/python` 或進 venv 後用 `python`，不能直接用系統 `python3`，否則找不到依賴。

</details>

### Step 2：GCP 授權（只需一次）

```bash
gcloud auth application-default login
```

瀏覽器會跳出 Google 登入頁面，登入後會在本機產生 Application Default Credentials（ADC），工具會自動使用。

> **注意**：這一步（`application-default login`）跟 `gcloud init` 是**不同的東西**。`gcloud init` 只設定 CLI 的預設專案，工具實際讀的是 ADC。即使你跑過 `gcloud init`，仍必須執行上面這行才能通過驗證。

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
.\run.bat
```

**或直接執行**（兩種寫法擇一）：

```bash
# 方法 A：先進虛擬環境，之後 python 自動指向 venv
source .venv/bin/activate
python main.py

# 方法 B：不進 venv，直接指定 venv 內的 python
.venv/bin/python main.py
```

> **為什麼一定要用 venv 內的 Python？** 專案依賴（rich、playwright、google-cloud-quotas 等）只裝在 `.venv/` 裡。直接打 `python3 main.py` 會 `ModuleNotFoundError`；macOS 預設沒 `python` 命令，也會 `command not found`。

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
→ 逐一導航 Model Garden：
     （部分新模型）接受 Advanced AI Safety Addendum → 點擊 Enable
     → 填寫 EULA → Next → 勾選 Terms → Agree
→ 最後顯示批次結果 table（Project / Model / Status / Note）
```

- 首次使用會開啟瀏覽器讓你手動登入 Google 帳號，之後登入狀態自動保存
- 若「Terms of service have not been accepted」彈窗出現，工具會自動關閉並重試（最多 3 次）
- 自動填寫使用 Tab 鍵循序導航，穩定度高於 CSS 選擇器
- **部分新模型有前置同意關卡**：頁面出現「Advanced AI Safety Addendum」時，工具會自動點開連結、勾選、Accept Terms，待 Enable 解鎖後再繼續（舊模型無此關卡，自動跳過偵測）
- **已開通的模型自動跳過**：對 publisher model 的 `:countTokens` endpoint 探測，404 = 未開通、400 = 已開通（Partner Model 真實 EULA 接受狀態）
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
.venv/bin/python main.py enable --project my-project-id --models claude-opus-4-7

# 單一專案 + 多個模型（逗號分隔）
.venv/bin/python main.py enable --project my-project-id \
                      --models claude-opus-4-7,claude-sonnet-4-6

# 多個專案（逗號分隔）× 多個模型 —— 批次模式
.venv/bin/python main.py enable --projects proj-a,proj-b,proj-c \
                      --models claude-opus-4-7,claude-sonnet-4-6

# 從檔案讀取專案清單（一行一個，`#` 開頭視為註解）
.venv/bin/python main.py enable --projects-file projects.txt \
                      --models claude-opus-4-7

# 遠端執行（headless 模式）+ 全自動跳過確認
.venv/bin/python main.py enable --projects-file projects.txt \
                      --models claude-opus-4-7 --headless --yes

# 失敗專案重跑：工具會自動產生 failed-projects.txt
.venv/bin/python main.py enable --projects-file failed-projects.txt \
                      --models claude-opus-4-7
```

**專案輸入（三擇一，互斥）：**

| 參數 | 格式 | 範例 |
|------|------|------|
| `--project` | 單一專案 ID | `--project my-project-id` |
| `--projects` | 逗號分隔多個專案 ID | `--projects proj-a,proj-b,proj-c` |
| `--projects-file` | 文字檔（一行一個 ID，`#` 為註解） | `--projects-file projects.txt` |

**其他參數：**

| 參數 | 必填 | 說明 |
|------|------|------|
| `--models`  | ✓ | 模型 URL slug（支援多個，逗號分隔） |
| `--headless` |   | 以 headless 模式跑瀏覽器（預設讀 `BROWSER_HEADLESS` 環境變數） |
| `-y`, `--yes` |   | 跳過確認提示 |

**批次行為：**

- 逐專案預檢：Billing / API 狀態 / 已開通模型（對 publisher model 發 `:countTokens` 探測 EULA 狀態）
- 已開通的 (專案 × 模型) 組合顯示 `⏭ SKIP (已開通)`，不會重跑
- 所有專案共用同一個 Playwright session，免重複登入
- 執行結束顯示結果 table；若有失敗，寫 `failed-projects.txt` 方便重跑

### `quota` — 提升配額

```bash
# 單一專案：提升 Global 策略下的 RPM / TPM
.venv/bin/python main.py quota --project my-project-id \
                     --model claude-opus-4-7 \
                     --routing global \
                     --rpm 100 --input-tpm 500000 --output-tpm 100000

# 只提升 RPM（其他不動）
.venv/bin/python main.py quota --project my-project-id \
                     --model claude-opus-4-7 \
                     --routing global --rpm 200

# 批次多專案：相同 model / routing / 目標值套用到所有專案
.venv/bin/python main.py quota --projects proj-a,proj-b,proj-c \
                     --model claude-opus-4-7 \
                     --routing global \
                     --rpm 100 --input-tpm 500000

# 從檔案讀取專案清單 + 全自動
.venv/bin/python main.py quota --projects-file projects.txt \
                     --model claude-opus-4-7 \
                     --routing global --rpm 200 --yes
```

**專案輸入（三擇一，互斥）：**

| 參數 | 格式 | 範例 |
|------|------|------|
| `--project` | 單一專案 ID | `--project my-project-id` |
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
.venv/bin/python main.py list-models

# 檢查單一專案各模型開通狀態
.venv/bin/python main.py list-models --project my-project-id

# 多專案 matrix：一眼看出哪些專案缺哪個模型
.venv/bin/python main.py list-models --projects proj-a,proj-b,proj-c

# 從檔案讀取
.venv/bin/python main.py list-models --projects-file projects.txt
```

輸出範例（matrix 模式）：

```
模型 \ 專案            proj-a  proj-b  proj-c
claude-opus-4-7         ✅      ✅      ❌
claude-opus-4-6         ✅      ❌      ❌
claude-sonnet-4-6       ✅      ✅      ✅
...
```

- ✅ 已開通（`:countTokens` 探測回 400，模型可存取 = EULA 已接受）
- ❌ 未開通（`:countTokens` 探測回 404，模型對該專案不可見）
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

## Claude Code 整合

本專案內建 [Claude Code Skill](https://docs.claude.com/en/docs/agents/skills)（位於 `.claude/skills/vertex-ai-claude-enabler/`），讓你**用自然語言**操作這個工具。

只要在專案目錄打開 Claude Code，Skill 會自動載入。你可以直接說：

- 「幫我在 `<project-id>` 開通 Claude 4.7 Opus」
- 「幫客戶 A 的所有專案開 Claude Sonnet 4.6」（搭配 `customers.json`）
- 「把 `<project-id>` 的 Claude 4.7 Opus Global RPM 拉到 200」
- 「Claude 5.0 發布了，幫我確認 Vertex AI 上架了沒」

Claude 會自動：

1. 比對 `CLAUDE_MODELS` 清單（必要時 WebFetch 驗證 Vertex AI 上架狀態）
2. 解析 `customers.json` 展開客戶 → 專案
3. chat 複誦目標讓你確認
4. 用 `--yes` + `--headless` 執行對應 CLI 子指令
5. 回報結果

> Skill 只在 cwd 為本專案目錄時載入，不會污染其他專案。詳見 [`SKILL.md`](.claude/skills/vertex-ai-claude-enabler/SKILL.md)。

---

## 常用任務 Cookbook

幾個典型場景的指令片段（替換 `<...>` 占位符）：

### 在新專案開通某個模型

```bash
.venv/bin/python main.py enable \
  --project <PROJECT_ID> \
  --models claude-opus-4-7 --yes
```

### 一次開通多個模型到多個專案

```bash
.venv/bin/python main.py enable \
  --projects <PROJ_A>,<PROJ_B>,<PROJ_C> \
  --models claude-opus-4-7,claude-sonnet-4-6 \
  --headless --yes
```

### 批次提升一群專案的 Global RPM 到 200

```bash
.venv/bin/python main.py quota \
  --projects-file projects.txt \
  --model claude-opus-4-7 \
  --routing global --rpm 200 --yes
```

### 看哪些專案還沒開通某個模型

```bash
.venv/bin/python main.py list-models --projects-file projects.txt
```

輸出 matrix 中該模型那一列裡的 ❌ 即為缺漏專案。

### 失敗專案重跑

任何 `enable` / `quota` 子指令失敗會自動產生 `failed-projects.txt`：

```bash
.venv/bin/python main.py enable \
  --projects-file failed-projects.txt \
  --models claude-opus-4-7 --yes
```

### 透過 Claude Code 一句話完成（推薦）

```
你（在 Claude Code 對話）：
  幫客戶 Acme 的所有專案開通 Claude 4.7 Opus

Claude 會：
  1. 讀 customers.json 找到 Acme 對應的 project IDs
  2. chat 列出所有專案讓你確認
  3. 你回 yes
  4. 自動跑 .venv/bin/python main.py enable ... --yes 對每個專案
  5. 回報結果總表
```

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
讓你在 Claude Code 對話中說「幫 **客戶 A** 的所有專案開 Claude 5.0」時，AI 能自動展開為多個 `enable` 指令批次執行。

**啟用方式：**

```bash
cp customers.example.json customers.json
# 編輯 customers.json 填入實際客戶與專案
```

**格式：**

```json
{
  "customers": {
    "Acme Corp": {
      "aliases": ["acme", "客戶代號"],
      "projects": ["project-id-1", "project-id-2"],
      "notes": "選填備註"
    }
  }
}
```

`aliases` 提供模糊比對（同一客戶可有多個慣稱）。`customers.json` 已在 `.gitignore`，
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
| `aiplatform.googleapis.com` | Vertex AI / Agent Platform — 模型開通與使用（2026 起顯示名稱為「Agent Platform API」，service id 不變） |
| `cloudquotas.googleapis.com` | Cloud Quotas — 配額查詢與提升申請 |

---

## 技術元件

| 套件 | 對應 pipeline 階段 | 用途 |
|------|------|------|
| [google-auth](https://pypi.org/project/google-auth/) | 身份驗證 | 取用 Application Default Credentials（ADC） |
| [google-cloud-service-usage](https://pypi.org/project/google-cloud-service-usage/) | 啟用必要 API | 啟用 `aiplatform` / `cloudquotas` |
| [google-cloud-resource-manager](https://pypi.org/project/google-cloud-resource-manager/) | 專案枚舉 | 列出可存取的 GCP 專案 |
| [google-cloud-quotas](https://pypi.org/project/google-cloud-quotas/) | 配額查詢 / 提升 | Cloud Quotas SDK 送出提升申請 |
| [Playwright](https://playwright.dev/python/) | EULA 開通 | 驅動瀏覽器重現 Console 開通流程 |
| [Rich](https://rich.readthedocs.io/) | 結果回報 | 終端機表格 / Panel / 顏色輸出 |
| [InquirerPy](https://inquirerpy.readthedocs.io/) | 互動模式 | select / checkbox / number 選單 |

> `:countTokens` 開通偵測、Cloud Billing 檢查與配額 **查詢** 直接以 REST 呼叫（`requests` + ADC token），未經上述 SDK 封裝。

---

## 常見問題

<details>
<summary><b>執行時出現「<code>zsh: command not found: python</code>」或「<code>ModuleNotFoundError: No module named 'rich'</code>」</b></summary>

代表你**沒進虛擬環境**，或用了系統 Python。專案依賴只裝在 `.venv/` 內。

兩種解法擇一：

```bash
# 方法 A：先進 venv（之後 python 自動指向 venv）
source .venv/bin/activate
python main.py list-models

# 方法 B：不進 venv，直接用 venv 的 python
.venv/bin/python main.py list-models
```

macOS 預設只有 `python3` 沒有 `python`，加上專案依賴隔離在 venv，所以**任何一個 `main.py` 指令都不能直接用系統 `python3`**。

</details>

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
<summary><b>自動填表時 Enable 按鈕找不到</b></summary>

工具會以 `hl=en` 鎖定英文介面並精準定位 Enable 按鈕。若仍找不到，通常代表該模型已在此專案開通，或 Console 頁面結構有變動。工具會將當下頁面截圖存至 `debug_screenshots/` 供診斷，並可手動至 [Model Garden](https://console.cloud.google.com/vertex-ai/model-garden) 確認。

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

