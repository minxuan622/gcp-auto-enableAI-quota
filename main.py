#!/usr/bin/env python3
"""
GCP Vertex AI Claude Model Manager
===================================
團隊用 CLI 工具，自動化管理 Claude 模型的開通與配額申請。

功能：
  1. 環境開通 — 啟用 API + Playwright 自動填寫 EULA 表單
  2. 配額提升 — 查詢現有配額並送出提升申請
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from InquirerPy import inquirer

# ──────────────────────────────────────────────
# 載入 .env 設定
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")

CONFIG_PATH = PROJECT_ROOT / os.getenv("CONFIG_PATH", "config.json")
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_SLOW_MO = int(os.getenv("BROWSER_SLOW_MO", "500"))
BROWSER_STATE_DIR = PROJECT_ROOT / os.getenv("BROWSER_STATE_DIR", ".browser_state")
BROWSER_STATE_FILE = BROWSER_STATE_DIR / "state.json"
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "us-east5")

# ──────────────────────────────────────────────
# 常數定義
# ──────────────────────────────────────────────

# Claude 模型清單：(顯示名稱, GCP base_model dimension 值, Model Garden URL slug)
# base_model 值必須與 GCP quota dimensions 完全一致（含 anthropic- 前綴）
CLAUDE_MODELS = [
    ("Claude Fable 5",    "anthropic-claude-fable-5",             "claude-fable-5"),
    ("Claude Sonnet 5",   "anthropic-claude-sonnet-5",            "claude-sonnet-5"),
    ("Claude 4.8 Opus",   "anthropic-claude-opus-4-8",            "claude-opus-4-8"),
    ("Claude 4.7 Opus",   "anthropic-claude-opus-4-7",            "claude-opus-4-7"),
    ("Claude 4.6 Opus",   "anthropic-claude-opus-4-6",            "claude-opus-4-6"),
    ("Claude 4.6 Sonnet", "anthropic-claude-sonnet-4-6",          "claude-sonnet-4-6"),
    ("Claude 4.5 Sonnet", "anthropic-claude-sonnet-4-5", "claude-sonnet-4-5"),
    ("Claude 4.5 Opus",   "anthropic-claude-opus-4-5",   "claude-opus-4-5"),
    ("Claude 4.5 Haiku",  "anthropic-claude-haiku-4-5",  "claude-haiku-4-5"),
]

# Routing 策略分類關鍵字（比對 Cloud Quotas metric 名稱前綴）
# 實際 metric 樣式：
#   Global:            aiplatform.googleapis.com/global_online_prediction_*
#   US Multi-region:   aiplatform.googleapis.com/us_multi_region_online_prediction_*
#   EU Multi-region:   aiplatform.googleapis.com/eu_multi_region_online_prediction_*
#   Regional:          aiplatform.googleapis.com/online_prediction_*（無前綴）
ROUTING_KEYWORDS = {
    "Global":           ["global_online_prediction", "global_generate_content"],
    "US Multi-region":  ["us_multi_region"],
    "EU Multi-region":  ["eu_multi_region"],
    "Regional":         [],                   # 不含上述關鍵字 = regional
}

# Routing 策略溢價提示（Claude Sonnet 4.5 以後）
ROUTING_PRICING = {
    "Global":           "無溢價 ✓",
    "US Multi-region":  "+10% 溢價",
    "EU Multi-region":  "+10% 溢價",
    "Regional":         "+10% 溢價",
}

# CLI --routing 短名 → 內部 routing key
ROUTING_CLI_MAP = {
    "global":   "Global",
    "us":       "US Multi-region",
    "eu":       "EU Multi-region",
    "regional": "Regional",
}

# 配額類型分類關鍵字（從 display name / metric 判斷是 RPM 還是 TPM）
QUOTA_TYPE_KEYWORDS = {
    "rpm":        ["requests"],
    "input_tpm":  ["input_tokens", "input tokens"],
    "output_tpm": ["output_tokens", "output tokens"],
}

# Vertex AI 支援 Claude 的區域
SUPPORTED_REGIONS = [
    "us-east5",
    "us-central1",
    "europe-west1",
    "europe-west4",
    "asia-southeast1",
]

# 正確的 Model Garden base URL（publishers/anthropic 路徑是必要的）
MODEL_GARDEN_BASE = "https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden"

console = Console()


# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────

def load_config() -> dict:
    """讀取 config.json，若不存在則提示使用者建立。"""
    if not CONFIG_PATH.exists():
        console.print(
            Panel(
                "[bold red]找不到 config.json[/]\n\n"
                "請先複製 config.json.example 並填入您的資料：\n"
                "  cp config.json.example config.json\n"
                "  然後編輯 config.json",
                title="⚠️ 設定檔缺失",
            )
        )
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # 檢查必填欄位是否存在
    required = ["business_name", "business_website", "contact_email", "use_cases"]
    form = data.get("eula_form", {})
    missing = [f for f in required if not form.get(f)]
    if missing:
        console.print(Panel(
            f"[bold red]config.json 缺少以下必填欄位：[/]\n"
            + "\n".join(f"  • {f}" for f in missing)
            + "\n\n請先編輯 config.json 填入資料。",
            title="⚠️ 設定不完整",
        ))
        sys.exit(1)

    return data


def check_gcloud_auth():
    """檢查 gcloud CLI 是否安裝、ADC 是否已登入。"""
    gcloud_path = shutil.which("gcloud")
    if not gcloud_path:
        console.print(Panel(
            "[bold red]未偵測到 gcloud CLI[/]\n\n"
            "請先安裝 Google Cloud SDK：\n"
            "  Mac:     brew install --cask google-cloud-sdk\n"
            "  Windows: https://cloud.google.com/sdk/docs/install",
            title="⚠️ 環境檢查失敗",
        ))
        sys.exit(1)

    result = subprocess.run(
        [gcloud_path, "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(Panel(
            "[bold red]Application Default Credentials 尚未設定[/]\n\n"
            "請先執行：\n"
            "  gcloud auth application-default login",
            title="⚠️ 環境檢查失敗",
        ))
        sys.exit(1)

    console.print("[green]✓[/] gcloud CLI 與 ADC 驗證通過")


def get_accessible_projects() -> list[dict]:
    """透過 Resource Manager API 列出使用者可存取的 GCP 專案。"""
    from google.cloud import resourcemanager_v3

    client = resourcemanager_v3.ProjectsClient()
    projects = []
    try:
        for project in client.search_projects():
            if project.state.name == "ACTIVE":
                projects.append({
                    "name": project.display_name,
                    "id": project.project_id,
                })
    except Exception as e:
        _handle_permission_error(e, "列出專案")
    return sorted(projects, key=lambda p: p["name"])


BACK_SENTINEL = "__BACK__"


def select_project(projects: list[dict]) -> str | None:
    """互動式選擇 GCP 專案，回傳 project_id；選擇「返回」時回傳 None。"""
    choices = [
        {"name": f"{p['name']}  ({p['id']})", "value": p["id"]}
        for p in projects
    ]
    choices.append({"name": "↩ 返回上一步", "value": BACK_SENTINEL})
    result = inquirer.select(
        message="請選擇目標 GCP 專案：",
        choices=choices,
    ).execute()
    return None if result == BACK_SENTINEL else result


def select_projects_multi(projects: list[dict]) -> list[str] | None:
    """
    互動式多選 GCP 專案（checkbox），回傳 project_id list；返回時回 None。
    先讓使用者選「繼續 / 返回」避免 UX 不佳。
    """
    proceed = inquirer.select(
        message="選擇專案或返回：",
        choices=[
            {"name": "📋 選擇目標 GCP 專案（可多選）", "value": "select"},
            {"name": "↩ 返回上一步", "value": BACK_SENTINEL},
        ],
    ).execute()
    if proceed == BACK_SENTINEL:
        return None

    choices = [
        {"name": f"{p['name']}  ({p['id']})", "value": p["id"]}
        for p in projects
    ]
    selected = inquirer.checkbox(
        message="請選擇目標 GCP 專案（空白鍵選取，Enter 確認）：",
        choices=choices,
        validate=lambda result: len(result) > 0,
        invalid_message="至少選擇一個專案",
    ).execute()
    return selected


def select_models() -> list[tuple] | None:
    """互動式多選 Claude 模型；選擇「返回」時回傳 None。"""
    # 先問要繼續還是返回，避免 checkbox 體驗不佳
    proceed = inquirer.select(
        message="選擇模型或返回：",
        choices=[
            {"name": "📋 選擇要開通的 Claude 模型", "value": "select"},
            {"name": "↩ 返回上一步", "value": BACK_SENTINEL},
        ],
    ).execute()
    if proceed == BACK_SENTINEL:
        return None

    choices = [
        {"name": m[0], "value": m}
        for m in CLAUDE_MODELS
    ]
    selected = inquirer.checkbox(
        message="請選擇欲開通的 Claude 模型（空白鍵選取，Enter 確認）：",
        choices=choices,
        validate=lambda result: len(result) > 0,
        invalid_message="至少選擇一個模型",
    ).execute()
    return selected


def select_region() -> str | None:
    """互動式選擇區域，預設值從 .env 讀取；選擇「返回」時回傳 None。"""
    regions = sorted(SUPPORTED_REGIONS, key=lambda r: r != DEFAULT_REGION)
    choices = [{"name": r, "value": r} for r in regions]
    choices.append({"name": "↩ 返回上一步", "value": BACK_SENTINEL})
    result = inquirer.select(
        message="請選擇 Region：",
        choices=choices,
        default=DEFAULT_REGION,
    ).execute()
    return None if result == BACK_SENTINEL else result


def _handle_permission_error(error, action: str):
    """統一處理權限不足錯誤。"""
    error_str = str(error)
    if "403" in error_str or "PERMISSION_DENIED" in error_str or "Forbidden" in error_str:
        console.print(Panel(
            f"[bold yellow]權限不足[/]：執行「{action}」時被拒絕。\n\n"
            "您似乎沒有該專案的 Owner 或 Quota Administrator 權限。\n"
            "請先向管理員申請對應權限後再試一次。",
            title="⚠️ 權限不足",
        ))
    else:
        console.print(f"[red]執行「{action}」時發生錯誤：{error}[/]")
    sys.exit(1)


def check_billing(project_id: str) -> bool:
    """
    檢查專案是否已綁定 Billing Account。
    使用 Cloud Billing REST API (cloudbilling.googleapis.com)。
    回傳 True = 已綁定，False = 未綁定或無法查詢。
    """
    import urllib.request
    import urllib.error

    try:
        token = _get_auth_token()
    except Exception:
        # 無法取得 token，跳過檢查讓後續流程自行處理
        return True

    url = f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        return data.get("billingEnabled", False)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # 沒有 billing 查詢權限，跳過檢查（不阻擋流程）
            return True
        return True
    except Exception:
        return True


def _warn_no_billing(project_id: str):
    """顯示 Billing 未綁定的警告面板。"""
    billing_url = f"https://console.cloud.google.com/billing/linkedaccount?project={project_id}"
    console.print(Panel(
        f"[bold red]專案 {project_id} 尚未綁定 Billing Account[/]\n\n"
        f"Vertex AI Claude 模型需要啟用計費才能使用。\n"
        f"請先前往以下頁面綁定帳單帳戶：\n"
        f"  [cyan]{billing_url}[/]\n\n"
        f"綁定完成後再重新執行操作。",
        title="💳 需要綁定 Billing",
        border_style="red",
    ))


def _check_all_quotas_na(route_quotas: dict) -> bool:
    """檢查是否所有配額的 limit 都是 N/A（代表模型尚未開通）。"""
    for qtype in ["rpm", "input_tpm", "output_tpm"]:
        q = route_quotas.get(qtype, {})
        limit = q.get("limit", "N/A")
        if isinstance(limit, (int, float)) and limit > 0:
            return False
    return True


# ──────────────────────────────────────────────
# 批次操作：共用資料結構與 helper
# ──────────────────────────────────────────────

@dataclass
class OpResult:
    """批次操作結果單筆記錄。"""
    project: str
    model: str = "-"
    status: str = "DONE"   # DONE | SKIP | FAIL
    note: str = ""


def parse_projects_input(
    project: str | None,
    projects: str | None,
    projects_file: str | None,
) -> list[str]:
    """
    解析 --project / --projects / --projects-file 三選一，回傳 project_id list。
    projects_file 為純文字檔：一行一個 project id，# 開頭視為註解。
    """
    specified = [v for v in (project, projects, projects_file) if v]
    if len(specified) > 1:
        console.print("[red]✗ --project, --projects, --projects-file 只能擇一[/]")
        sys.exit(1)

    if projects_file:
        p = Path(projects_file)
        if not p.exists():
            console.print(f"[red]✗ 找不到檔案: {projects_file}[/]")
            sys.exit(1)
        ids: list[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line)
        if not ids:
            console.print(f"[red]✗ 檔案 {projects_file} 沒有有效的 project id[/]")
            sys.exit(1)
        # 去重、保留順序
        seen: set[str] = set()
        uniq: list[str] = []
        for pid in ids:
            if pid not in seen:
                seen.add(pid)
                uniq.append(pid)
        return uniq

    if projects:
        ids = [s.strip() for s in projects.split(",") if s.strip()]
        if not ids:
            console.print("[red]✗ --projects 不可為空[/]")
            sys.exit(1)
        return ids

    if project:
        return [project]

    console.print("[red]✗ 請指定 --project / --projects / --projects-file 其中之一[/]")
    sys.exit(1)


def is_model_enabled(project_id: str, slug: str, region: str = "us-east5") -> bool:
    """
    透過呼叫 Vertex AI publisher model 的 :countTokens endpoint 探測模型是否已開通。

    判斷邏輯：
        404 → 未開通（Publisher Model 對該專案不可見，代表 EULA 未接受）
        400 → 已開通（模型可存取，countTokens 對 Anthropic Claude 本身不支援，
                     但能存取就代表 EULA 已過）
        200 → 已開通（如未來 Google 開放 countTokens 對 Claude 可用）
        其他（403 / 5xx / 網路錯誤）→ 保守視為未開通，寧可重跑流程也不要誤判跳過

    為什麼用 :countTokens 而不是 modelGardenEula:check：
        Anthropic Claude 是 Partner Model，不走 modelGardenEula 系統，
        該 API 對 Claude 永遠回空 acked 欄位。countTokens 探測是實證可靠的訊號。

    為什麼用 us-east5 而不是 locations/global：
        Anthropic Claude 不部署在 locations/global API endpoint，
        global endpoint 對所有專案都會 404；us-east5 是 Claude 最常見部署區。
        EULA 是 per-project，從任一可用區探測結果都一致。
    """
    import requests
    from google.auth import default
    from google.auth.transport.requests import Request

    try:
        creds, _ = default()
        creds.refresh(Request())
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}"
            f"/locations/{region}/publishers/anthropic/models/{slug}:countTokens"
        )
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "X-Goog-User-Project": project_id,
                "Content-Type": "application/json",
            },
            json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            timeout=15,
        )
        if r.status_code == 404:
            return False
        if r.status_code in (200, 400):
            return True
        return False
    except Exception:
        return False


def print_batch_summary(results: list[OpResult], title: str, write_failed_file: bool = True):
    """印出批次操作結果 table；若有失敗，同時寫入 failed-projects.txt 方便重跑。"""
    if not results:
        return

    table = Table(title=title)
    table.add_column("Project", style="cyan")
    table.add_column("Model")
    table.add_column("Status")
    table.add_column("Note", style="dim", max_width=50)

    done = skip = fail = 0
    for r in results:
        if r.status == "DONE":
            done += 1
            s = "[green]✅ DONE[/]"
        elif r.status == "SKIP":
            skip += 1
            s = "[yellow]⏭  SKIP[/]"
        else:
            fail += 1
            s = "[red]❌ FAIL[/]"
        table.add_row(r.project, r.model, s, r.note)

    console.print()
    console.print(table)
    console.print(
        f"[bold]Summary:[/] "
        f"[green]{done} done[/] · "
        f"[yellow]{skip} skipped[/] · "
        f"[red]{fail} failed[/]"
    )

    if write_failed_file and fail > 0:
        failed_projects = sorted({r.project for r in results if r.status == "FAIL"})
        out = PROJECT_ROOT / "failed-projects.txt"
        out.write_text("\n".join(failed_projects) + "\n", encoding="utf-8")
        console.print(
            f"[dim]失敗專案清單已儲存至 [bold]{out.name}[/bold]，"
            f"可用 [bold]--projects-file {out.name}[/bold] 重跑[/]"
        )


# ──────────────────────────────────────────────
# 瀏覽器登入狀態管理
# ──────────────────────────────────────────────

def _load_browser_state() -> str | None:
    """若存在已儲存的瀏覽器登入狀態，回傳檔案路徑。"""
    if BROWSER_STATE_FILE.exists():
        console.print("[green]✓[/] 偵測到已儲存的瀏覽器登入狀態，將自動套用")
        return str(BROWSER_STATE_FILE)
    return None


def _save_browser_state(context):
    """將目前瀏覽器的 cookie/session 儲存下來，下次免重新登入。"""
    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(BROWSER_STATE_FILE))
    console.print(f"[green]✓[/] 瀏覽器登入狀態已儲存至 {BROWSER_STATE_DIR}/")


def _debug_screenshot(page, label: str) -> str | None:
    """自動化失敗時截圖存檔，方便事後診斷頁面實際狀態。回傳存檔路徑（失敗回 None）。"""
    try:
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in label)[:60]
        debug_dir = PROJECT_ROOT / "debug_screenshots"
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = str(debug_dir / f"fail_{safe}.png")
        page.screenshot(path=path, full_page=True)
        console.print(f"  [dim]🖼  已截圖存證：{path}[/]")
        return path
    except Exception:
        return None


# ──────────────────────────────────────────────
# 功能一：環境開通
# ──────────────────────────────────────────────

def _enable_single_api(project_id: str, service_id: str, label: str):
    """
    啟用單一 GCP API（若已啟用則靜默跳過）。
    """
    from google.cloud import service_usage_v1
    from google.api_core.exceptions import PermissionDenied, GoogleAPICallError

    client = service_usage_v1.ServiceUsageClient()

    # 先查詢現有狀態，避免不必要的 enable 呼叫
    try:
        svc = client.get_service(
            name=f"projects/{project_id}/services/{service_id}"
        )
        if svc.state.name == "ENABLED":
            console.print(f"[green]✓[/] {label} ({service_id}) 已啟用")
            return
    except Exception:
        pass  # 查詢失敗也繼續嘗試啟用

    console.print(f"  啟用 {label} ({service_id}) ...")
    request = service_usage_v1.EnableServiceRequest(
        name=f"projects/{project_id}/services/{service_id}",
    )
    try:
        operation = client.enable_service(request=request)
        operation.result()
        console.print(f"[green]✓[/] {label} ({service_id}) 已啟用")
    except PermissionDenied as e:
        _handle_permission_error(e, f"啟用 {label}")
    except GoogleAPICallError as e:
        _handle_permission_error(e, f"啟用 {label}")


def enable_api(project_id: str):
    """
    確保環境所需的 GCP API 均已啟用：
      1. aiplatform.googleapis.com  — Vertex AI / Agent Platform（模型開通必要；
         2026 起 GCP 將此 service 的顯示名稱改為 "Agent Platform API"，service id 不變）
      2. cloudquotas.googleapis.com — Cloud Quotas（配額查詢與提升必要）
    """
    console.print(f"\n[bold]確認必要 API 狀態[/] (專案: {project_id}) ...")
    _enable_single_api(project_id, "aiplatform.googleapis.com",  "Vertex AI / Agent Platform API")
    _enable_single_api(project_id, "cloudquotas.googleapis.com", "Cloud Quotas API")


def _make_browser_and_page(pw, saved_state: str | None):
    """建立 browser + context + page，共用此函式以方便重建。"""
    browser = pw.chromium.launch(
        headless=BROWSER_HEADLESS,
        slow_mo=BROWSER_SLOW_MO,
    )
    ctx_kwargs = {"viewport": {"width": 1280, "height": 900}}
    if saved_state:
        ctx_kwargs["storage_state"] = saved_state
    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()
    return browser, context, page


def run_enable_session(plan: list[tuple[str, list[tuple]]], config: dict) -> list[OpResult]:
    """
    使用 Playwright 自動開啟 Model Garden 並填寫 EULA。
    plan: [(project_id, [model_tuple, ...]), ...]
    整個 plan 共用同一個 browser context，首次 Google 登入只需一次。

    回傳每個 (project, model) 組合的 OpResult。
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    from playwright._impl._errors import TargetClosedError

    form = config["eula_form"]
    saved_state = _load_browser_state()
    results: list[OpResult] = []

    console.print("\n[bold]啟動瀏覽器進行 EULA 自動填表...[/]")
    if not saved_state:
        console.print(
            "[bold yellow]首次使用：[/]瀏覽器開啟後請先手動登入 Google 帳號，\n"
            "登入完成後回到終端機按 [bold]Enter[/] 繼續。\n"
            "[dim]⚠ 請勿關閉瀏覽器視窗，讓腳本自動操作。[/]\n"
        )
    else:
        console.print("[dim]⚠ 請勿關閉瀏覽器視窗，讓腳本自動操作。[/]\n")

    total_models = sum(len(ms) for _, ms in plan)
    processed = 0

    with sync_playwright() as pw:
        browser, context, page = _make_browser_and_page(pw, saved_state)

        # ── 首次登入流程 ──
        if not saved_state:
            page.goto("https://console.cloud.google.com/", wait_until="domcontentloaded", timeout=60000)
            console.print("[bold cyan]瀏覽器已開啟 GCP Console。[/]")
            console.print("請在瀏覽器中完成 Google 帳號登入...")
            input("\n✋ 登入完成後，請按 Enter 繼續（不要關瀏覽器）→ ")
            _save_browser_state(context)
            saved_state = str(BROWSER_STATE_FILE)

        # ── 逐一處理 (project, models) ──
        for pidx, (project_id, models) in enumerate(plan, 1):
            if len(plan) > 1:
                console.print(f"\n[bold cyan]═══ [{pidx}/{len(plan)}] 專案 {project_id} ═══[/]")

            for display_name, _model_id, garden_slug in models:
                processed += 1
                # hl=en 強制英文介面：按鈕/狀態/表單文字語言固定，避免中文介面下
                # 按鈕是「啟用」而選擇器（找英文 "Enable"）撲空、誤中英文狀態標籤
                url = f"{MODEL_GARDEN_BASE}/{garden_slug}?project={project_id}&hl=en"
                console.print(
                    f"\n[cyan]→ [{processed}/{total_models}][/] "
                    f"開通 [bold]{display_name}[/] @ [cyan]{project_id}[/]"
                )
                console.print(f"  導航至: {url}")

                try:
                    # 如果 page 已被關閉，重新建立 browser/context/page
                    try:
                        page.title()  # 簡單測試 page 是否還活著
                    except TargetClosedError:
                        console.print("  [yellow]偵測到瀏覽器視窗已關閉，正在重新開啟...[/]")
                        browser, context, page = _make_browser_and_page(pw, saved_state)

                    # domcontentloaded 即可，GCP Console 是 SPA，networkidle 會卡住
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)  # 讓 SPA 完整渲染（含 vertex-ai→agent-platform 導向）

                    # 等待 Enable 按鈕出現（最多 30 秒，讓 GCP Console SPA 完整載入）
                    console.print("  等待頁面載入...")
                    enable_btn = page.locator(
                        # 精準比對「Enable」：用 :text-is 完全比對，避免子字串誤中
                        # 「Vertex AI API enabled」等狀態標籤（含 "enable" 子字串）。
                        # 已用 hl=en 強制英文，故只需比對 "Enable"；另備中文「啟用」防呆。
                        'button:text-is("Enable"), '
                        'span:text-is("Enable"), '
                        'a:text-is("Enable"), '
                        '[role="button"]:text-is("Enable"), '
                        'button:text-is("啟用"), '
                        'span:text-is("啟用")'
                    ).first
                    try:
                        enable_btn.wait_for(state="visible", timeout=30000)
                    except Exception:
                        console.print("  [yellow]未找到 Enable 按鈕，可能已開通或頁面結構有變[/]")
                        # 診斷：找所有含 "Enable" 的元素，印 tag + 確切文字 + 是否可見
                        try:
                            cands = page.locator(':text("Enable")').all()
                            console.print(f"  [dim]— 含 'Enable' 的元素（共 {len(cands)}）—[/]")
                            for c in cands[:15]:
                                try:
                                    tag = c.evaluate("e => e.tagName")
                                    txt = (c.inner_text(timeout=500) or "").strip().replace("\n"," ")
                                    vis = c.is_visible()
                                    console.print(f"  [dim]  · <{tag}> vis={vis} 「{txt[:45]}」[/]")
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        _debug_screenshot(page, f"{project_id}_{display_name}_noenable")
                        results.append(OpResult(project_id, display_name, "SKIP", "未找到 Enable 按鈕（可能已開通）"))
                        continue

                    # ── Advanced AI Safety Addendum 前置同意關卡（Fable 5 等新模型）──
                    # 頁面渲染後若出現「Accept Terms」按鈕，代表 Enable 被前置同意鎖住，
                    # 需先接受 Addendum，Enable 才會從 disabled 變可點。舊模型無此關卡。
                    page.wait_for_timeout(1000)
                    accept_btn = page.locator(
                        'button:has-text("Accept Terms"), '
                        '[role="button"]:has-text("Accept Terms")'
                    ).first
                    if accept_btn.is_visible(timeout=2000):
                        ok, note = _handle_safety_addendum(page, context, accept_btn)
                        if not ok:
                            console.print(f"  [red]✗ Advanced AI Safety Addendum 處理失敗：{note}[/]")
                            results.append(OpResult(project_id, display_name, "FAIL", note))
                            continue

                    # 確認命中的是真正的 Enable 按鈕（而非「Vertex AI API enabled」狀態標籤）
                    try:
                        btn_text = (enable_btn.inner_text(timeout=1500) or "").strip().replace("\n", " ")
                    except Exception:
                        btn_text = "?"
                    console.print(f"  [dim]即將點擊按鈕：「{btn_text}」[/]")

                    enable_btn.click()
                    console.print("  [green]✓[/] 已點擊 Enable")

                    # 等待 EULA 表單出現
                    page.wait_for_timeout(4000)

                    # 使用「循序 Tab 填表法」：
                    # 表單欄位順序固定，從第一個欄位開始，用 Tab 逐一跳到下一欄。
                    # 不依賴 CSS 選擇器，最穩定。
                    status, note = _fill_form_sequential(page, form, display_name)
                    results.append(OpResult(project_id, display_name, status, note))

                except PwTimeout:
                    console.print(f"  [yellow]頁面載入或操作逾時，請手動檢查 {display_name}[/]")
                    _debug_screenshot(page, f"{project_id}_{display_name}_timeout")
                    results.append(OpResult(project_id, display_name, "FAIL", "頁面載入/操作逾時"))
                except TargetClosedError:
                    console.print(f"  [yellow]瀏覽器視窗意外關閉，跳過 {display_name}，請手動完成[/]")
                    results.append(OpResult(project_id, display_name, "FAIL", "瀏覽器意外關閉"))
                except Exception as e:
                    console.print(f"  [red]自動填表時發生錯誤：{e}[/]")
                    _debug_screenshot(page, f"{project_id}_{display_name}_error")
                    results.append(OpResult(project_id, display_name, "FAIL", str(e)[:80]))

        # 流程結束，更新登入狀態，安全關閉
        try:
            _save_browser_state(context)
        except Exception:
            pass
        console.print("\n[dim]自動填表流程結束，瀏覽器將在 3 秒後關閉...[/]")
        try:
            page.wait_for_timeout(3000)
        except Exception:
            pass  # 瀏覽器已被手動關閉，不影響結果
        try:
            browser.close()
        except Exception:
            pass

    return results


def auto_fill_eula(project_id: str, models: list[tuple], config: dict) -> list[OpResult]:
    """單專案開通（保持向下相容的介面）。內部轉呼叫 run_enable_session。"""
    return run_enable_session([(project_id, models)], config)


def _fill_form_sequential(page, form: dict, display_name: str) -> tuple[str, str]:
    """
    用 Tab 鍵循序填寫 EULA 表單。
    回傳 (status, note)：
      ("DONE", "EULA 已送出")  — 整個流程走完、Agree 沒觸發錯誤彈窗
      ("FAIL", reason)         — 找不到 Next/Agree 按鈕、或 Terms 重試失敗
    不依賴任何 CSS 選擇器找個別欄位，只需要：
      1. 點進第一個欄位（Business name）
      2. 填值 → Tab → 填值 → Tab → ...
    表單欄位固定順序（根據截圖）：
      1. Business name          (text)
      2. Business website       (text)
      3. Contact email address  (text)
      4. Where is your Business headquartered (dropdown)
      5. Industry               (dropdown)
      6. Who are your intended users          (dropdown)
      7. What are your intended use cases     (text/textarea)
      8. Additional requirements radio        (Yes/No)
      9. Additional requirements detail       (text, conditional)
    """
    kbd = page.keyboard

    # ── 點進第一個欄位 ──
    first_field = page.get_by_label("Business name", exact=False).first
    try:
        first_field.click(timeout=5000)
    except Exception:
        # fallback: 找文字再點
        page.locator('text="Business name"').first.click()
    page.wait_for_timeout(300)

    # ── 1. Business name (text) ──
    kbd.type(form["business_name"], delay=20)
    console.print(f"  [green]✓[/] 已填寫 Business name")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 2. Business website (text) ──
    kbd.type(form["business_website"], delay=20)
    console.print(f"  [green]✓[/] 已填寫 Business website")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 3. Contact email address (text) ──
    kbd.type(form["contact_email"], delay=20)
    console.print(f"  [green]✓[/] 已填寫 Contact email address")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 4. Where is your Business headquartered (dropdown) ──
    _tab_select_dropdown(page, form["business_hq"], "Where is your Business headquartered")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 5. Industry (dropdown) ──
    _tab_select_dropdown(page, form["industry"], "Industry")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 6. Who are your intended users (dropdown) ──
    _tab_select_dropdown(page, form["intended_users"], "Who are your intended users")
    kbd.press("Tab")
    page.wait_for_timeout(200)

    # ── 7. What are your intended use cases (text/textarea) ──
    kbd.type(form["use_cases"], delay=20)
    console.print(f"  [green]✓[/] 已填寫 What are your intended use cases")
    page.wait_for_timeout(200)

    # ── 8. Additional requirements (radio: Yes/No) ──
    aup = form.get("has_additional_requirements", "No")
    _click_radio(page, aup)

    # ── 9. 若選 Yes，填寫補充說明 ──
    if aup == "Yes" and form.get("additional_requirements_detail"):
        detail_field = page.get_by_label("please describe", exact=False).first
        try:
            detail_field.click(timeout=2000)
            kbd.type(form["additional_requirements_detail"], delay=20)
            console.print(f"  [green]✓[/] 已填寫 Additional requirements detail")
        except Exception:
            console.print(f"  [yellow]⚠ 無法填寫 Additional requirements detail，請手動填入[/]")

    # ── 點擊 Next（進入第二頁 Agreements）──
    page.wait_for_timeout(500)
    next_btn = page.locator('button:has-text("Next")').first
    if next_btn.is_visible(timeout=3000):
        next_btn.click()
        console.print(f"  [green]✓[/] {display_name} 表單第一頁已送出")
    else:
        console.print("  [yellow]未找到 Next 按鈕，請手動確認[/]")
        return "FAIL", "未找到 Next 按鈕"

    # ═══════════════════════════════════════════
    # 第二頁：Agreements（定價 + 條款同意）
    # ═══════════════════════════════════════════
    console.print(f"  等待 Agreements 頁面載入...")
    page.wait_for_timeout(5000)

    # GCP 使用 Angular Material <mat-checkbox>，內部 <input> 是隱藏的，
    # 必須點擊外層元件才有效。此處用重試迴圈確保勾選成功。
    MAX_AGREE_ATTEMPTS = 3

    for attempt in range(1, MAX_AGREE_ATTEMPTS + 1):
        console.print(f"  嘗試勾選 Terms checkbox（第 {attempt} 次）...")

        # ── 勾選 checkbox ──
        _try_check_terms(page)
        page.wait_for_timeout(800)

        # ── 驗證 checkbox 狀態 ──
        if not _is_checkbox_checked(page):
            console.print(f"  [yellow]checkbox 似乎未勾選，再嘗試一次...[/]")
            # 滾動 + 強制點擊
            _force_click_all_checkboxes(page)
            page.wait_for_timeout(800)

        # ── 點擊 Agree ──
        try:
            agree_btn = page.locator(
                'button:has-text("Agree"), '
                '[role="button"]:has-text("Agree"), '
                'a:has-text("Agree")'
            ).first
            agree_btn.wait_for(state="visible", timeout=5000)
            agree_btn.click()
            page.wait_for_timeout(3000)
        except Exception:
            console.print(f"  [yellow]⚠ 未找到 Agree 按鈕，請手動點擊完成開通[/]")
            return "FAIL", "未找到 Agree 按鈕"

        # ── 檢查是否彈出「Terms not accepted」錯誤 ──
        error_dialog = page.locator('text="Terms of service have not been accepted"')
        try:
            if error_dialog.is_visible(timeout=2000):
                console.print(f"  [yellow]偵測到「Terms not accepted」彈窗[/]")
                # 關閉彈窗
                ok_btn = page.locator(
                    'button:has-text("OK"), [role="button"]:has-text("OK")'
                ).first
                if ok_btn.is_visible(timeout=2000):
                    ok_btn.click()
                    page.wait_for_timeout(1000)

                if attempt < MAX_AGREE_ATTEMPTS:
                    console.print(f"  [cyan]將重新嘗試勾選 checkbox...[/]")
                    continue
                else:
                    console.print(f"  [red]已重試 {MAX_AGREE_ATTEMPTS} 次仍失敗，請手動勾選 checkbox 再點 Agree[/]")
                    return "FAIL", f"Terms checkbox 重試 {MAX_AGREE_ATTEMPTS} 次失敗"
        except Exception:
            pass  # 沒有錯誤彈窗 = 勾選成功

        console.print(f"  [green]✓[/] [bold]{display_name} 開通完成！已點擊 Agree[/]")
        return "DONE", "EULA 已送出"

    # 理論上不會到這，但為了 type-safety 加 fallback
    return "FAIL", "未完成 Agree 流程"


def _handle_safety_addendum(page, context, accept_btn) -> tuple[bool, str]:
    """
    接受「Advanced AI Safety Addendum」前置同意關卡（Claude Fable 5 等新模型）。

    新版 Model Garden 對部分模型加了一道前置法律同意：頁面頂端出現警告橫幅 +
    checkbox + 「Accept Terms」按鈕，且 Enable 按鈕在接受前是 disabled 的。
    流程（經實測確認）：
      1. 必須先點開「Advanced AI Safety Addendum」連結（target=_blank 開新分頁），
         checkbox 才會解鎖可勾。
      2. 勾選 checkbox → 「Accept Terms」按鈕啟用。
      3. 點 Accept Terms → Enable 按鈕才從 disabled 變可點。
      4. 接受後仍會進入舊的商業資訊 EULA 表單（_fill_form_sequential），不是取代。

    偵測由呼叫端負責（頁面渲染後若出現 Accept Terms 按鈕即代表有此關卡）；
    舊模型無此關卡，呼叫端不會進到這個函數。

    回傳 (proceed_ok, note)：
      (True,  "...")  已成功接受 → 呼叫端可繼續點 Enable
      (False, reason) 處理失敗 → 呼叫端記 FAIL
    """
    console.print("  [cyan]偵測到 Advanced AI Safety Addendum 前置同意，處理中...[/]")

    # 1) 點開 Addendum 連結（會開新分頁），checkbox 才解鎖
    link = page.locator('a:has-text("Advanced AI Safety Addendum")').first
    try:
        if link.is_visible(timeout=2000):
            try:
                with context.expect_page(timeout=8000) as new_info:
                    link.click()
                new_tab = new_info.value
                page.wait_for_timeout(800)
                try:
                    new_tab.close()
                except Exception:
                    pass
                console.print("  [green]✓[/] 已點開 Addendum 連結（解鎖 checkbox）")
            except Exception:
                # 沒有偵測到新分頁也沒關係，可能在同頁開啟，繼續嘗試勾選
                console.print("  [dim]未偵測到新分頁，直接嘗試勾選 checkbox[/]")
    except Exception:
        pass

    try:
        page.bring_to_front()
    except Exception:
        pass
    page.wait_for_timeout(400)

    # 2) 勾選 Addendum checkbox
    cb = page.locator(
        'mat-checkbox:has-text("By checking this box"), '
        'mat-checkbox:has-text("Advanced AI Safety Addendum"), '
        'label:has-text("By checking this box")'
    ).first
    try:
        cb.scroll_into_view_if_needed(timeout=2000)
        cb.click()
        page.wait_for_timeout(400)
        console.print("  [green]✓[/] 已勾選 Addendum checkbox")
    except Exception:
        # 退而求其次：暴力點 banner 區域的第一個 checkbox
        try:
            page.locator('[role="checkbox"], input[type="checkbox"]').first.click()
            page.wait_for_timeout(400)
            console.print("  [green]✓[/] 已勾選 checkbox（通用選擇器）")
        except Exception as e:
            return False, f"無法勾選 Addendum checkbox: {str(e)[:50]}"

    # 3) 點 Accept Terms（勾選後應已啟用）
    try:
        accept_btn.click(timeout=8000)
        console.print("  [green]✓[/] 已點擊 Accept Terms")
    except Exception as e:
        return False, f"無法點擊 Accept Terms: {str(e)[:50]}"

    # 4) 等待關卡消失（Accept Terms 隱藏 = 接受完成、Enable 解鎖）
    try:
        accept_btn.wait_for(state="hidden", timeout=15000)
    except Exception:
        pass  # 即使沒立刻消失，後續 Enable click 的 auto-wait 仍會驗證
    page.wait_for_timeout(1200)
    console.print("  [green]✓[/] Advanced AI Safety Addendum 已接受")
    return True, "已接受 Addendum"


def _try_check_terms(page):
    """嘗試多種策略勾選 Terms checkbox。"""
    # 策略 1: 找包含條款相關文字的 mat-checkbox
    for keyword in ["acknowledge", "agree", "By purchasing", "Terms"]:
        try:
            el = page.locator(f'mat-checkbox:has-text("{keyword}")').first
            if el.is_visible(timeout=1500):
                el.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                el.click()
                page.wait_for_timeout(500)
                console.print(f"  [green]✓[/] 已點擊 checkbox（關鍵字: {keyword}）")
                return
        except Exception:
            continue

    # 策略 2: 找包含條款文字的 label
    for keyword in ["acknowledge", "By purchasing"]:
        try:
            el = page.locator(f'label:has-text("{keyword}")').first
            if el.is_visible(timeout=1500):
                el.click()
                page.wait_for_timeout(500)
                console.print(f"  [green]✓[/] 已點擊 label（關鍵字: {keyword}）")
                return
        except Exception:
            continue

    # 策略 3: 通用 checkbox role / class
    try:
        cb = page.locator('[role="checkbox"], .mat-checkbox, mat-checkbox').first
        if cb.is_visible(timeout=1500):
            cb.click()
            page.wait_for_timeout(500)
            console.print(f"  [green]✓[/] 已點擊通用 checkbox")
            return
    except Exception:
        pass

    console.print(f"  [yellow]⚠ 無法定位 checkbox[/]")


def _is_checkbox_checked(page) -> bool:
    """檢查頁面上的 Terms checkbox 是否已呈現勾選狀態。"""
    try:
        cb = page.locator(
            'mat-checkbox, [role="checkbox"]'
        ).first
        if not cb.is_visible(timeout=1000):
            return False
        aria = cb.get_attribute("aria-checked") or ""
        classes = cb.get_attribute("class") or ""
        return aria == "true" or "mat-checkbox-checked" in classes or "checked" in classes
    except Exception:
        return False


def _force_click_all_checkboxes(page):
    """暴力找所有 checkbox 元素，逐一嘗試點擊。"""
    try:
        page.locator('text="Terms and agreements"').first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception:
        pass

    all_cb = page.locator(
        'mat-checkbox, [role="checkbox"], '
        'input[type="checkbox"], .mat-checkbox-inner-container'
    ).all()
    for cb in all_cb:
        try:
            if cb.is_visible():
                cb.click()
                page.wait_for_timeout(300)
        except Exception:
            continue
    console.print(f"  [dim]已強制點擊 {len(all_cb)} 個 checkbox 元素[/]")


def _tab_select_dropdown(page, value: str, label: str):
    """
    當焦點已在下拉選單上時，用鍵盤操作選擇：
      1. 按 Space/Enter 展開下拉
      2. 輸入文字過濾選項
      3. 按 Enter 選擇第一個匹配結果
    """
    if not value:
        page.keyboard.press("Tab")
        return

    kbd = page.keyboard

    # 嘗試展開下拉選單
    kbd.press("Space")
    page.wait_for_timeout(800)

    # 檢查是否有選項浮層出現
    option = page.locator(
        f'mat-option:has-text("{value}"), '
        f'[role="option"]:has-text("{value}"), '
        f'li:has-text("{value}")'
    ).first

    try:
        if option.is_visible(timeout=2000):
            option.click()
            page.wait_for_timeout(500)
            console.print(f"  [green]✓[/] 已選擇 {label}: {value}")
            return
    except Exception:
        pass

    # 浮層沒出現或找不到選項 → 用鍵盤輸入搜尋
    kbd.type(value, delay=50)
    page.wait_for_timeout(1000)

    try:
        filtered = page.locator(
            f'mat-option:has-text("{value}"), '
            f'[role="option"]:has-text("{value}"), '
            f'li:has-text("{value}")'
        ).first
        if filtered.is_visible(timeout=2000):
            filtered.click()
            page.wait_for_timeout(500)
            console.print(f"  [green]✓[/] 已選擇 {label}: {value}")
            return
    except Exception:
        pass

    # 最後手段：按 Enter 選第一個
    kbd.press("Enter")
    page.wait_for_timeout(500)
    console.print(f"  [yellow]⚠ {label}: 已嘗試選擇「{value}」，請確認是否正確[/]")


def _fill_input(page, placeholder_text: str, value: str):
    """
    填寫文字輸入欄位。
    GCP Console 使用 Angular Material 元件，欄位標籤是 <mat-label> / <label>
    浮動在輸入框上方，而非 <input placeholder="...">。
    因此需要多重策略定位：
      1. Playwright 高階 get_by_label（最可靠）
      2. placeholder 屬性
      3. aria-label 屬性
      4. 找到 label 文字 → 點擊使 input 獲得焦點 → 鍵盤輸入
    """
    if not value:
        return

    short_text = placeholder_text.split("*")[0].strip()

    # 策略 1: Playwright get_by_label（自動匹配 <label>、aria-label、aria-labelledby）
    try:
        el = page.get_by_label(short_text, exact=False).first
        if el.is_visible(timeout=2000):
            el.fill(value)
            console.print(f"  [green]✓[/] 已填寫 {short_text}")
            return
    except Exception:
        pass

    # 策略 2: Playwright get_by_placeholder
    try:
        el = page.get_by_placeholder(short_text, exact=False).first
        if el.is_visible(timeout=1500):
            el.fill(value)
            console.print(f"  [green]✓[/] 已填寫 {short_text}")
            return
    except Exception:
        pass

    # 策略 3: CSS 選擇器 — placeholder / aria-label 屬性
    for tag in ["input", "textarea"]:
        for attr in ["placeholder", "aria-label"]:
            try:
                el = page.locator(f'{tag}[{attr}*="{short_text}" i]').first
                if el.is_visible(timeout=1000):
                    el.fill(value)
                    console.print(f"  [green]✓[/] 已填寫 {short_text}")
                    return
            except Exception:
                continue

    # 策略 4: 找到包含該文字的 label/mat-label → 點擊 → 鍵盤輸入
    try:
        label_el = page.locator(
            f'label:has-text("{short_text}"), '
            f'mat-label:has-text("{short_text}"), '
            f'span:has-text("{short_text}")'
        ).first
        if label_el.is_visible(timeout=1500):
            label_el.click()
            page.wait_for_timeout(300)
            # 點擊後 focus 應在 input 上，直接鍵盤輸入
            page.keyboard.type(value, delay=30)
            console.print(f"  [green]✓[/] 已填寫 {short_text} (透過 label 點擊)")
            return
    except Exception:
        pass

    console.print(f"  [yellow]⚠ 無法自動填寫「{short_text}」，請手動填入[/]")


def _select_dropdown(page, placeholder_text: str, value: str):
    """
    處理 GCP Console 的下拉選單（Material Design 風格）。
    策略：不猜元素類型，直接用多種方式「點開」下拉 → 再從浮層選選項。
    """
    if not value:
        return

    short_text = placeholder_text.split("*")[0].strip()
    opened = False

    # ── 步驟 1：點開下拉選單 ──
    # 策略 A: get_by_label（最可靠，Playwright 自動關聯 label ↔ control）
    if not opened:
        try:
            el = page.get_by_label(short_text, exact=False).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(800)
                opened = True
        except Exception:
            pass

    # 策略 B: 找含有此文字的可點擊元素（含下拉箭頭的整個區塊）
    if not opened:
        try:
            el = page.locator(f'text="{short_text}"').first
            if el.is_visible(timeout=1500):
                el.click()
                page.wait_for_timeout(800)
                opened = True
        except Exception:
            pass

    if not opened:
        console.print(f"  [yellow]⚠ 無法找到下拉選單「{short_text}」，請手動選擇[/]")
        return

    # ── 步驟 2：從浮層中選擇目標值 ──
    try:
        # Angular Material overlay 的選項可能是 mat-option、role=option、li 等
        option = page.locator(
            f'mat-option:has-text("{value}"), '
            f'[role="option"]:has-text("{value}"), '
            f'li:has-text("{value}"), '
            f'.cdk-overlay-pane :has-text("{value}")'
        ).first
        if option.is_visible(timeout=3000):
            option.click()
            page.wait_for_timeout(500)
            console.print(f"  [green]✓[/] 已選擇 {short_text}: {value}")
            return
    except Exception:
        pass

    # 策略 C: 如果上面選不到，可能是搜尋式下拉（先輸入再選）
    try:
        page.keyboard.type(value, delay=50)
        page.wait_for_timeout(1000)
        # 輸入後應出現過濾結果，點第一個匹配項
        filtered = page.locator(
            f'mat-option:has-text("{value}"), '
            f'[role="option"]:has-text("{value}")'
        ).first
        if filtered.is_visible(timeout=2000):
            filtered.click()
            page.wait_for_timeout(500)
            console.print(f"  [green]✓[/] 已選擇 {short_text}: {value} (透過搜尋)")
            return
    except Exception:
        pass

    console.print(f"  [yellow]⚠ 找不到選項「{value}」，請手動選擇 {short_text}[/]")


def _click_radio(page, label_text: str):
    """
    點擊 radio button（Yes / No）。
    """
    try:
        radio = page.locator(f'text="{label_text}"').first
        if radio.is_visible(timeout=2000):
            radio.click()
            page.wait_for_timeout(300)
            console.print(f"  [green]✓[/] 已選擇: {label_text}")
        else:
            console.print(f"  [yellow]⚠ 找不到 radio 選項「{label_text}」，請手動選擇[/]")
    except Exception:
        console.print(f"  [yellow]⚠ 無法點擊「{label_text}」，請手動選擇[/]")


# ──────────────────────────────────────────────
# 功能二：配額提升
# ──────────────────────────────────────────────

def _get_auth_token() -> str:
    """取得 ADC token，供 REST API 使用。"""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token


def _rest_get(url: str, token: str) -> dict:
    """發送 GET 請求到 GCP REST API。"""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def get_quota_info(project_id: str, base_model: str, strict: bool = True) -> list[dict]:
    """
    透過 Cloud Quotas SDK 查詢指定模型的配額。
    Cloud Quotas API 規範：
      - parent 格式：projects/{project}/locations/global/services/{service}
        location 固定為 "global"，傳入區域名稱會導致 400 Malformed name。
      - SDK 呼叫 list_quota_infos(parent=...) 時會自動補上 /quotaInfos，
        因此 parent 絕對不要自行加 /quotaInfos。

    strict=True  (預設): 權限錯誤會呼叫 _handle_permission_error 終止程式。
    strict=False         : 批次模式用，所有錯誤都靜默吞掉回傳 []，由呼叫端決定如何記錄。
    """
    from google.cloud import cloudquotas_v1
    from google.api_core.exceptions import PermissionDenied, GoogleAPICallError

    # Cloud Quotas API location 固定為 global
    parent = (
        f"projects/{project_id}/locations/global"
        f"/services/aiplatform.googleapis.com"
    )

    try:
        client = cloudquotas_v1.CloudQuotasClient()
        quota_infos = list(client.list_quota_infos(parent=parent))
    except PermissionDenied as e:
        if strict:
            _handle_permission_error(e, "查詢配額")
        return []
    except GoogleAPICallError as e:
        if strict:
            console.print(f"[red]查詢配額失敗：{e}[/]")
        return []
    except Exception as e:
        if strict:
            console.print(f"[red]查詢配額失敗：{e}[/]")
        return []

    quotas = []
    for qi in quota_infos:
        metric_name  = qi.metric        # e.g. "aiplatform.googleapis.com/..."
        display_name = qi.quota_display_name
        quota_id     = qi.quota_id      # e.g. "generate-content-requests-per-minute-per-base-model-global"

        # 每個 QuotaInfo 下有多個 DimensionsInfo（對應不同 base_model / region 組合）
        for dim_info in qi.dimensions_infos:
            dims = dict(dim_info.dimensions)   # e.g. {"base_model": "anthropic-claude-opus-4-6"}

            # 精確比對目標模型的 base_model dimension
            if dims.get("base_model") != base_model:
                continue

            # 取得目前配額上限（details.value 是 QuotaValue 物件）
            effective = "N/A"
            if dim_info.details and hasattr(dim_info.details, "value"):
                effective = dim_info.details.value

            # 組成 quota_limit_name 供後續 consumerOverrides 使用
            # 格式：projects/{project}/locations/global/services/{service}/quotaInfos/{quota_id}
            quota_limit_name = f"{parent}/quotaInfos/{quota_id}"

            quotas.append({
                "name":             display_name or quota_id,
                "metric":           metric_name,
                "quota_id":         quota_id,
                "quota_limit_name": quota_limit_name,
                "limit":            effective,
                "unit":             getattr(qi, "quota_units", ""),
                "dimensions":       dims,
                "region":           dims.get("region", "global"),
            })

    return quotas


def _classify_quota(name: str, metric: str) -> tuple[str, str]:
    """
    根據 display name / metric 分類配額的 routing 策略和類型。
    回傳 (routing, quota_type)
    routing:    "Global" | "US Multi-region" | "EU Multi-region" | "Regional"
    quota_type: "rpm" | "input_tpm" | "output_tpm" | "unknown"
    """
    combined = (name + " " + metric).lower()

    # 判斷 routing 策略（Global / US / EU 有明確前綴，其餘歸 Regional）
    # 先比對較具體的關鍵字，避免誤判
    if any(kw in combined for kw in ROUTING_KEYWORDS["EU Multi-region"]):
        routing = "EU Multi-region"
    elif any(kw in combined for kw in ROUTING_KEYWORDS["US Multi-region"]):
        routing = "US Multi-region"
    elif any(kw in combined for kw in ROUTING_KEYWORDS["Global"]):
        routing = "Global"
    else:
        routing = "Regional"

    # 判斷配額類型
    if "output" in combined and "token" in combined:
        qtype = "output_tpm"
    elif "input" in combined and "token" in combined:
        qtype = "input_tpm"
    elif "request" in combined:
        qtype = "rpm"
    else:
        qtype = "unknown"

    return routing, qtype


def _fmt_limit(val) -> str:
    """格式化配額數值，加千分位。"""
    if isinstance(val, (int, float)) and val >= 0:
        return f"{int(val):,}"
    return str(val)


def display_quota_summary(grouped: dict, model_name: str, routing: str):
    """顯示特定 routing 策略下的 RPM / Input TPM / Output TPM 現況。"""
    quotas = grouped.get(routing, {})

    table = Table(title=f"{model_name} — {routing} 配額現況")
    table.add_column("配額類型", style="cyan")
    table.add_column("目前上限", style="green", justify="right")
    table.add_column("配額名稱", style="dim", max_width=55)

    type_labels = {
        "rpm": "⚡ RPM (Requests/min)",
        "input_tpm": "📥 Input TPM (Tokens/min)",
        "output_tpm": "📤 Output TPM (Tokens/min)",
    }

    for qtype in ["rpm", "input_tpm", "output_tpm"]:
        q = quotas.get(qtype)
        if q:
            table.add_row(
                type_labels[qtype],
                _fmt_limit(q["limit"]),
                q["name"],
            )
        else:
            table.add_row(
                type_labels[qtype],
                "[red]未找到[/]",
                "",
            )

    console.print(table)


def submit_single_quota(project_id: str, quota_info: dict, new_limit: int) -> dict:
    """
    使用 Cloud Quotas SDK 送出單一配額提升申請（create_quota_preference）。

    API 規範：
      - parent 只到 location，格式：projects/{project}/locations/global
        （不含 /services/...，否則會 400）
      - quota_preference_id 需唯一，用 uuid 避免重複送出衝突
      - reconciling=True  → 申請已送出，進入審核
      - reconciling=False → 已立即核准生效

    回傳 {"status": "APPROVED"|"PENDING"|"DENIED"|"ERROR", "message": str}
    """
    import uuid
    from google.cloud import cloudquotas_v1
    from google.api_core.exceptions import PermissionDenied, InvalidArgument, GoogleAPICallError

    quota_id  = quota_info.get("quota_id", "")
    dimensions = quota_info.get("dimensions", {})

    if not quota_id:
        return {"status": "ERROR", "message": "缺少 quota_id，請先執行 Debug Raw Dump 確認配額結構"}

    # parent 只到 location，不含 service
    parent = f"projects/{project_id}/locations/global"

    quota_preference = cloudquotas_v1.QuotaPreference(
        service="aiplatform.googleapis.com",
        quota_id=quota_id,
        dimensions=dimensions,
        quota_config=cloudquotas_v1.QuotaConfig(
            preferred_value=new_limit,
        ),
    )

    # quota_preference_id 加上隨機後綴，避免重複提交時衝突
    pref_id = f"increase-{quota_id[:40].lower()}-{uuid.uuid4().hex[:6]}"

    request = cloudquotas_v1.CreateQuotaPreferenceRequest(
        parent=parent,
        quota_preference_id=pref_id,
        quota_preference=quota_preference,
    )

    try:
        client = cloudquotas_v1.CloudQuotasClient()
        response = client.create_quota_preference(request=request)

        # reconciling=False → 立即核准生效
        # reconciling=True  → 進入人工審核
        if response.reconciling:
            return {"status": "PENDING", "message": response.name}
        else:
            return {"status": "APPROVED", "message": response.name}

    except PermissionDenied as e:
        return {"status": "ERROR", "message": f"權限不足: {e}"}
    except InvalidArgument as e:
        return {"status": "DENIED", "message": str(e)}
    except GoogleAPICallError as e:
        return {"status": "ERROR", "message": str(e)}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def _open_quota_console(project_id: str):
    """開啟 GCP Console 配額頁面。"""
    import webbrowser
    url = f"https://console.cloud.google.com/apis/api/aiplatform.googleapis.com/quotas?project={project_id}"
    console.print(f"\n[bold]開啟配額頁面：[/] {url}")
    webbrowser.open(url)


def quota_flow(projects: list[dict]):
    """
    配額管理主流程（支援多專案 checkbox）：
      Step 1: 多選專案 → Step 2: 選模型 → Step 3: 選 Routing
      Step 4: 以第一個可用專案的 quotas 作為 UI 參考 → 輸入目標 → run_batch_quota
    """
    step = 1
    selected_pids: list[str] | None = None
    model: tuple | None = None
    display_name = base_model = ""
    grouped: dict = {}            # ref_grouped：第一個可用專案的 quota 分組
    ref_project: str | None = None
    selected_routing: str | None = None

    while True:
        # ── Step 1: 多選專案 ──
        if step == 1:
            selected_pids = select_projects_multi(projects)
            if selected_pids is None:
                return  # 返回主選單
            step = 2
            continue

        # ── Step 2: 選模型 + 查第一個可用專案的配額作為 UI 參考 ──
        if step == 2:
            choices = [{"name": m[0], "value": m} for m in CLAUDE_MODELS]
            choices.append({"name": "↩ 返回上一步（重新選擇專案）", "value": BACK_SENTINEL})
            model = inquirer.select(
                message="請選擇模型：",
                choices=choices,
            ).execute()
            if model == BACK_SENTINEL:
                step = 1
                continue
            display_name, base_model, _garden_slug = model

            console.print(f"\n[bold]查詢第一個可用專案的 {display_name} 配額作為參考值...[/]")
            grouped = {}
            ref_project = None
            for pid in selected_pids:
                quotas = get_quota_info(pid, base_model, strict=False)
                if not quotas:
                    continue
                g: dict[str, dict[str, dict]] = {}
                for q in quotas:
                    routing, qtype = _classify_quota(q["name"], q["metric"])
                    if qtype == "unknown":
                        continue
                    g.setdefault(routing, {})[qtype] = q
                if g:
                    grouped = g
                    ref_project = pid
                    console.print(f"[dim]參考專案：{pid}[/]")
                    break

            if not grouped:
                console.print(
                    "[yellow]⚠ 所有選取的專案都查不到 quotas（均未開通或權限不足）。[/]\n"
                    "[dim]仍可繼續選 Routing 與輸入目標值，批次執行時會逐個專案記錄 SKIP / FAIL。[/]"
                )

            step = 3
            continue

        # ── Step 3: 選 Routing 策略（無論參考資料有無皆提供 4 選項）──
        if step == 3:
            routing_choices = []
            for r in ["Global", "US Multi-region", "EU Multi-region", "Regional"]:
                pricing = ROUTING_PRICING.get(r, "")
                if grouped and r in grouped:
                    q = grouped[r]
                    rpm = _fmt_limit(q["rpm"]["limit"]) if "rpm" in q else "?"
                    tpm = _fmt_limit(q["input_tpm"]["limit"]) if "input_tpm" in q else "?"
                    name = f"{r}  [{pricing}]  ({ref_project} 現況 RPM: {rpm}, Input TPM: {tpm})"
                else:
                    name = f"{r}  [{pricing}]"
                routing_choices.append({"name": name, "value": r})
            routing_choices.append({"name": "↩ 返回上一步（重新選擇模型）", "value": BACK_SENTINEL})

            selected_routing = inquirer.select(
                message="請選擇 Routing 策略（將套用到所有選取的專案）：",
                choices=routing_choices,
            ).execute()
            if selected_routing == BACK_SENTINEL:
                step = 2
                continue

            step = 4
            continue

        # ── Step 4: 離開迴圈進入輸入與送出 ──
        if step == 4:
            break

    # ── 顯示參考專案的該 routing 配額現況（若有）──
    if grouped and selected_routing in grouped:
        console.print()
        display_quota_summary(grouped, display_name, selected_routing)
        route_quotas = grouped[selected_routing]
        current_rpm = route_quotas.get("rpm", {}).get("limit", 0)
        current_input_tpm = route_quotas.get("input_tpm", {}).get("limit", 0)
        current_output_tpm = route_quotas.get("output_tpm", {}).get("limit", 0)
    else:
        current_rpm = current_input_tpm = current_output_tpm = 0

    def _to_int_or(val, fallback: int) -> int:
        return int(val) if isinstance(val, (int, float)) and val > 0 else fallback

    ref_note = f"（參考專案：{ref_project}）" if ref_project else "（無參考資料）"
    scope_hint = (
        f"[dim]此目標值會套用到 {len(selected_pids)} 個專案；"
        f"若某專案當前值 ≥ 目標，自動跳過（不降級）。[/]"
    )

    # ── 輸入 RPM ──
    safe_rpm = int(current_rpm * 5) if isinstance(current_rpm, (int, float)) and current_rpm > 0 else 0
    console.print()
    console.print(Panel(
        f"[bold cyan]💡 系統提示 {ref_note}[/]：目前 RPM 配額 [bold]{_fmt_limit(current_rpm)}[/]。\n"
        f"根據經驗，申請幅度在 5 倍以內（小於 [bold]{_fmt_limit(safe_rpm)}[/]）較高機率會由系統自動核准立即生效。\n"
        f"若申請數值過高，會進入人工審核（24-48 小時）或被拒絕。請根據實際業務需求填寫。\n"
        f"{scope_hint}",
        title="RPM 配額提升",
        border_style="cyan",
    ))
    new_rpm = int(inquirer.number(
        message=f"請輸入期望的 RPM (參考值: {_fmt_limit(current_rpm)}, 建議 ≤ {_fmt_limit(safe_rpm)})：",
        min_allowed=1,
        default=_to_int_or(current_rpm, 1200),
        validate=lambda val: int(val) > 0,
        invalid_message="請輸入正整數",
    ).execute())

    # ── 輸入 Input TPM ──
    safe_input_tpm = int(current_input_tpm * 5) if isinstance(current_input_tpm, (int, float)) and current_input_tpm > 0 else 0
    console.print()
    console.print(Panel(
        f"[bold cyan]💡 系統提示 {ref_note}[/]：目前 Input TPM 配額 [bold]{_fmt_limit(current_input_tpm)}[/]。\n"
        f"申請幅度在 5 倍以內（小於 [bold]{_fmt_limit(safe_input_tpm)}[/]）較高機率自動核准立即生效。\n"
        f"{scope_hint}",
        title="Input TPM 配額提升",
        border_style="cyan",
    ))
    new_input_tpm = int(inquirer.number(
        message=f"請輸入期望的 Input TPM (參考值: {_fmt_limit(current_input_tpm)}, 建議 ≤ {_fmt_limit(safe_input_tpm)})：",
        min_allowed=1,
        default=_to_int_or(current_input_tpm, 12_000_000),
        validate=lambda val: int(val) > 0,
        invalid_message="請輸入正整數",
    ).execute())

    # ── 輸入 Output TPM ──
    safe_output_tpm = int(current_output_tpm * 5) if isinstance(current_output_tpm, (int, float)) and current_output_tpm > 0 else 0
    console.print()
    console.print(Panel(
        f"[bold cyan]💡 系統提示 {ref_note}[/]：目前 Output TPM 配額 [bold]{_fmt_limit(current_output_tpm)}[/]。\n"
        f"申請幅度在 5 倍以內（小於 [bold]{_fmt_limit(safe_output_tpm)}[/]）較高機率自動核准立即生效。\n"
        f"{scope_hint}",
        title="Output TPM 配額提升",
        border_style="cyan",
    ))
    new_output_tpm = int(inquirer.number(
        message=f"請輸入期望的 Output TPM (參考值: {_fmt_limit(current_output_tpm)}, 建議 ≤ {_fmt_limit(safe_output_tpm)})：",
        min_allowed=1,
        default=_to_int_or(current_output_tpm, 1_200_000),
        validate=lambda val: int(val) > 0,
        invalid_message="請輸入正整數",
    ).execute())

    # ── 執行批次（run_batch_quota 內部會再次確認並逐專案處理）──
    targets = {
        "rpm":        new_rpm,
        "input_tpm":  new_input_tpm,
        "output_tpm": new_output_tpm,
    }
    results = run_batch_quota(
        selected_pids, model, selected_routing, targets,
        yes=False,
    )

    print_batch_summary(results, title=f"配額提升結果 — {display_name} / {selected_routing}")


# ──────────────────────────────────────────────
# 🔍 Debug：配額 API Raw Dump
# ──────────────────────────────────────────────

def debug_quota_raw_dump(project_id: str):
    """
    無過濾裸測：嘗試多種 API 路徑，印出前 10 筆配額的完整 metric name 與 dimensions。
    用途：診斷 consumerQuotaMetrics 回傳空白的根本原因。
    """
    console.print(Panel(
        f"[bold cyan]🔍 配額 API Raw Dump[/]\n"
        f"專案: [bold]{project_id}[/]\n"
        f"將嘗試多種 API 路徑，無任何過濾，直接印出原始資料。",
        title="Debug 模式",
        border_style="cyan",
    ))

    try:
        token = _get_auth_token()
    except Exception as e:
        console.print(f"[red]無法取得認證 token：{e}[/]")
        return

    import urllib.request
    import urllib.error

    # ── 方式 A：Service Usage v1beta1 consumerQuotaMetrics（多種 pageSize 與過濾）──
    su_variants = [
        # (說明, URL)
        (
            "Service Usage v1beta1 (無額外參數)",
            f"https://serviceusage.googleapis.com/v1beta1/projects/{project_id}"
            f"/services/aiplatform.googleapis.com/consumerQuotaMetrics"
        ),
        (
            "Service Usage v1beta1 (pageSize=200)",
            f"https://serviceusage.googleapis.com/v1beta1/projects/{project_id}"
            f"/services/aiplatform.googleapis.com/consumerQuotaMetrics?pageSize=200"
        ),
        (
            "Service Usage v1beta1 (view=FULL)",
            f"https://serviceusage.googleapis.com/v1beta1/projects/{project_id}"
            f"/services/aiplatform.googleapis.com/consumerQuotaMetrics?view=FULL"
        ),
        (
            "Service Usage v1beta1 (pageSize=200&view=FULL)",
            f"https://serviceusage.googleapis.com/v1beta1/projects/{project_id}"
            f"/services/aiplatform.googleapis.com/consumerQuotaMetrics?pageSize=200&view=FULL"
        ),
    ]

    found_any = False

    for desc, url in su_variants:
        console.print(f"\n[bold]── {desc} ──[/]")
        console.print(f"[dim]URL: {url}[/]")
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())

            metrics = data.get("metrics", [])
            console.print(f"[green]✓ 回傳 {len(metrics)} 個 metrics[/]")

            if metrics:
                found_any = True
                count = 0
                for metric in metrics:
                    metric_name = metric.get("metric", "(no metric)")
                    display_name = metric.get("displayName", "")
                    for limit in metric.get("consumerQuotaLimits", []):
                        for bucket in limit.get("quotaBuckets", []):
                            dims = bucket.get("dimensions", {})
                            effective = bucket.get("effectiveLimit", "?")
                            console.print(
                                f"  [{count+1:02d}] metric=[cyan]{metric_name}[/]\n"
                                f"       display=[dim]{display_name}[/]\n"
                                f"       dims={dims}\n"
                                f"       effectiveLimit={effective}"
                            )
                            count += 1
                            if count >= 10:
                                break
                        if count >= 10:
                            break
                    if count >= 10:
                        break
                if count == 0:
                    console.print("  [yellow](metrics 存在但 quotaBuckets 均為空)[/]")
                    # 印出 metric 名稱列表
                    for m in metrics[:10]:
                        console.print(f"  metric: {m.get('metric')}  limits: {len(m.get('consumerQuotaLimits', []))}")
            else:
                # 印出原始 JSON 前 500 字元
                raw = json.dumps(data)
                console.print(f"[dim]原始回應（前 500 字元）: {raw[:500]}[/]")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()
            except Exception:
                pass
            console.print(f"[red]HTTP {e.code} {e.reason}[/]")
            console.print(f"[dim]{body[:300]}[/]")
        except Exception as e:
            console.print(f"[red]錯誤：{e}[/]")

    # ── 方式 B：Cloud Quotas API（google-cloud-quotas 套件）──
    # Cloud Quotas API 的 location 固定只接受 "global"，
    # 傳入 us-central1 等區域會導致 400 Malformed name。
    console.print(f"\n[bold]── Cloud Quotas API (google-cloud-quotas 套件, location=global) ──[/]")
    try:
        from google.cloud import cloudquotas_v1
        client = cloudquotas_v1.CloudQuotasClient()
        # 正確格式：projects/{project}/locations/global/services/{service}
        # SDK 會自動在 parent 後補上 /quotaInfos，不要手動加。
        parent = f"projects/{project_id}/locations/global/services/aiplatform.googleapis.com"
        console.print(f"[dim]parent: {parent}[/]")
        count = 0
        for qi in client.list_quota_infos(parent=parent):
            dims_info = ""
            if hasattr(qi, "dimensions_infos") and qi.dimensions_infos:
                dims_info = str([
                    {d.dimensions: d.details} for d in list(qi.dimensions_infos)[:3]
                ])
            console.print(
                f"  [{count+1:02d}] quota_id=[cyan]{qi.quota_id}[/]\n"
                f"       metric={qi.metric}\n"
                f"       is_fixed={getattr(qi, 'is_fixed', '?')}\n"
                f"       dimensions_infos={dims_info or '(空)'}"
            )
            count += 1
            found_any = True
            if count >= 10:
                break
        if count == 0:
            console.print("[yellow](location=global 回傳 0 筆)[/]")
        else:
            console.print(f"[green]✓ 共找到 {count} 筆（最多顯示 10）[/]")
    except ImportError:
        console.print("[yellow]google-cloud-quotas 套件未安裝，跳過此方式[/]")
    except Exception as e:
        console.print(f"[red]錯誤：{e}[/]")

    # ── 方式 C：直接列出 aiplatform 所有服務的 quota metric（不加 service filter）──
    console.print(f"\n[bold]── Service Usage v1 (一般 quota 端點) ──[/]")
    v1_url = (
        f"https://serviceusage.googleapis.com/v1/projects/{project_id}"
        f"/services/aiplatform.googleapis.com"
    )
    console.print(f"[dim]URL: {v1_url}[/]")
    try:
        req = urllib.request.Request(v1_url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        raw = json.dumps(data)
        console.print(f"[green]✓ 回傳[/]（前 800 字元）：\n[dim]{raw[:800]}[/]")
    except Exception as e:
        console.print(f"[red]錯誤：{e}[/]")

    console.print()
    if found_any:
        console.print("[green bold]✅ 成功找到配額資料！請根據上方輸出確認正確的 metric 名稱與 dimensions。[/]")
    else:
        console.print("[yellow]⚠ 所有方式均未找到配額資料。可能原因：[/]")
        console.print("  1. 帳號沒有 serviceusage.quotas.get 權限（需要 Quota Viewer 或 Owner 角色）")
        console.print("  2. 模型尚未在此專案開通（需先執行「環境開通」）")
        console.print("  3. 專案 ID 不正確")


# ──────────────────────────────────────────────
# 主選單
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# 非互動式（CLI 子指令）處理
# ──────────────────────────────────────────────

def _find_model_by_slug(slug: str) -> tuple | None:
    """根據 URL slug 查找 CLAUDE_MODELS 中的 tuple。"""
    for m in CLAUDE_MODELS:
        if m[2] == slug:
            return m
    return None


def _available_slugs() -> str:
    return ", ".join(m[2] for m in CLAUDE_MODELS)


def run_batch_enable(
    project_ids: list[str],
    models: list[tuple],
    config: dict,
    *,
    yes: bool = False,
    headless: bool = False,
) -> list[OpResult]:
    """
    批次開通主流程：
      1. 先對每個 project 檢查 Billing、啟用必要 API、查詢哪些 model 已開通
      2. 組出實際需要跑 EULA 的計畫 (plan)，已開通的直接記 SKIP
      3. 顯示計畫、請使用者確認
      4. 呼叫 run_enable_session 用單一 browser context 跑完整個 plan
    回傳所有 (project, model) 的 OpResult。
    """
    results: list[OpResult] = []
    plan: list[tuple[str, list[tuple]]] = []

    console.print()
    for pid in project_ids:
        if len(project_ids) > 1:
            console.print(f"[bold]── 預檢 {pid} ──[/]")

        # Billing 檢查
        if not check_billing(pid):
            _warn_no_billing(pid)
            for m in models:
                results.append(OpResult(pid, m[0], "FAIL", "Billing 未綁定"))
            continue

        # 啟用必要 API（已啟用則靜默跳過）
        try:
            enable_api(pid)
        except SystemExit:
            # _handle_permission_error 會 sys.exit；批次模式改為記錄失敗繼續
            for m in models:
                results.append(OpResult(pid, m[0], "FAIL", "啟用 API 權限不足"))
            continue
        except Exception as e:
            for m in models:
                results.append(OpResult(pid, m[0], "FAIL", f"啟用 API 失敗: {str(e)[:60]}"))
            continue

        # 檢查哪些 model 已開通
        to_enable: list[tuple] = []
        for m in models:
            display_name, _base_model, slug = m
            if is_model_enabled(pid, slug):
                console.print(f"  [dim]⏭  {display_name} 已開通，跳過[/]")
                results.append(OpResult(pid, display_name, "SKIP", "已開通"))
            else:
                to_enable.append(m)

        if to_enable:
            plan.append((pid, to_enable))

    # 全部已開通
    if not plan:
        console.print("\n[green bold]✅ 所有 (專案 × 模型) 組合均已開通，無需執行瀏覽器流程。[/]")
        return results

    # 顯示計畫
    console.print(f"\n[bold]即將開通以下組合（共 {sum(len(ms) for _, ms in plan)} 個）：[/]")
    for pid, mods in plan:
        console.print(f"  [cyan]{pid}[/]")
        for m in mods:
            console.print(f"    • {m[0]} [dim]({m[2]})[/]")
    if headless:
        console.print("  模式: [yellow]headless（不顯示瀏覽器視窗）[/]")

    # 確認
    if not yes:
        if not inquirer.confirm(message="\n確認執行？", default=True).execute():
            console.print("[dim]已取消（但已完成 API 啟用與已開通專案的略過判定）。[/]")
            return results

    # Headless override
    if headless:
        globals()["BROWSER_HEADLESS"] = True

    # 實際執行瀏覽器流程
    session_results = run_enable_session(plan, config)
    results.extend(session_results)

    return results


def cmd_enable(args):
    """非互動式開通：支援單/多專案。

    用法：
      python main.py enable --project  X --models slug1,slug2
      python main.py enable --projects p1,p2 --models slug
      python main.py enable --projects-file projects.txt --models slug
    """
    check_gcloud_auth()
    config = load_config()

    # 解析專案
    project_ids = parse_projects_input(
        getattr(args, "project", None),
        getattr(args, "projects", None),
        getattr(args, "projects_file", None),
    )

    # 解析模型 slug
    requested = [s.strip() for s in args.models.split(",") if s.strip()]
    if not requested:
        console.print("[red]✗ --models 不可為空[/]")
        sys.exit(1)

    models = []
    for slug in requested:
        m = _find_model_by_slug(slug)
        if m is None:
            console.print(f"[red]✗ 找不到模型 slug '{slug}'[/]")
            console.print(f"  可用：{_available_slugs()}")
            sys.exit(1)
        models.append(m)

    console.print(f"\n[bold]即將處理 {len(project_ids)} 個專案 × {len(models)} 個模型[/]")
    for pid in project_ids:
        console.print(f"  • [cyan]{pid}[/]")

    results = run_batch_enable(
        project_ids, models, config,
        yes=args.yes, headless=args.headless,
    )

    # 只在多專案/多模型時印 batch summary table；單一組合沿用原本的 inline 訊息
    if len(results) > 1:
        print_batch_summary(results, title="環境開通結果")


QTYPE_LABELS = {
    "rpm":        "⚡ RPM",
    "input_tpm":  "📥 Input TPM",
    "output_tpm": "📤 Output TPM",
}


def _quota_one_project(
    project_id: str,
    model: tuple,
    routing: str,
    targets: dict[str, int | None],
) -> list[OpResult]:
    """
    單一專案 × 單一模型 × 單一 routing 的配額提升流程。
    targets: {"rpm": int|None, "input_tpm": int|None, "output_tpm": int|None}
    回傳每個 quota type 一筆 OpResult（含 SKIP / DONE / FAIL）。
    """
    display_name, base_model, _slug = model
    results: list[OpResult] = []

    # 用 quota type 作為 model 欄位標示
    def _label(qtype: str, target: int | None) -> str:
        if target is None:
            return QTYPE_LABELS.get(qtype, qtype)
        return f"{QTYPE_LABELS.get(qtype, qtype)} → {_fmt_limit(target)}"

    # Billing
    if not check_billing(project_id):
        _warn_no_billing(project_id)
        for qtype, t in targets.items():
            if t is not None:
                results.append(OpResult(project_id, _label(qtype, t), "FAIL", "Billing 未綁定"))
        return results

    # 查配額（非嚴格模式，錯誤回空 list）
    quotas = get_quota_info(project_id, base_model, strict=False)
    if not quotas:
        for qtype, t in targets.items():
            if t is not None:
                results.append(OpResult(project_id, _label(qtype, t), "FAIL", "查詢配額失敗 / 權限不足"))
        return results

    # 分組
    grouped: dict[str, dict[str, dict]] = {}
    for q in quotas:
        r, qt = _classify_quota(q["name"], q["metric"])
        if qt == "unknown":
            continue
        grouped.setdefault(r, {})[qt] = q

    if routing not in grouped:
        console.print(f"  [red]✗ 找不到 {routing} 配額[/]")
        for qtype, t in targets.items():
            if t is not None:
                results.append(OpResult(project_id, _label(qtype, t), "FAIL", f"找不到 {routing} 配額"))
        return results

    route_quotas = grouped[routing]
    if _check_all_quotas_na(route_quotas):
        console.print(f"  [yellow]⊘ 模型尚未開通 EULA，所有配額略過[/]")
        for qtype, t in targets.items():
            if t is not None:
                results.append(OpResult(project_id, _label(qtype, t), "SKIP", "模型尚未開通 EULA"))
        return results

    # 逐一比對目標值並送出
    for qtype, new_limit in targets.items():
        if new_limit is None:
            continue
        if qtype not in route_quotas:
            console.print(f"  [yellow]⊘ {QTYPE_LABELS.get(qtype, qtype)}: {routing} 無此 quota 類型，略過[/]")
            results.append(OpResult(project_id, _label(qtype, new_limit), "SKIP", f"{routing} 無此 quota 類型"))
            continue

        q = route_quotas[qtype]
        current = q.get("limit", "N/A")

        # 目標已達成 → 跳過（不降級）
        if isinstance(current, (int, float)) and current >= new_limit:
            console.print(
                f"  [yellow]⊘ {QTYPE_LABELS.get(qtype, qtype)}: 目前 {_fmt_limit(current)} ≥ 目標 {_fmt_limit(new_limit)}，略過[/]"
            )
            results.append(OpResult(
                project_id,
                _label(qtype, new_limit),
                "SKIP",
                f"目前 {_fmt_limit(current)} ≥ 目標 {_fmt_limit(new_limit)}",
            ))
            continue

        # 送出
        label = _label(qtype, new_limit)
        console.print(f"  {QTYPE_LABELS.get(qtype, qtype)}: {_fmt_limit(current)} → [green]{_fmt_limit(new_limit)}[/] ...")
        result = submit_single_quota(project_id, q, new_limit)
        status = result["status"]
        msg = result["message"]

        if status == "APPROVED":
            console.print(f"    [green]✓ 已核准並立即生效[/]")
            results.append(OpResult(project_id, label, "DONE", "APPROVED（立即生效）"))
        elif status == "PENDING":
            console.print(f"    [yellow]⏳ 已送出，進入人工審核（24-48h）[/]")
            results.append(OpResult(project_id, label, "DONE", "PENDING（審核中）"))
        elif status == "DENIED":
            console.print(f"    [red]✗ 申請被拒絕（可能超過區域硬性上限）[/]")
            results.append(OpResult(project_id, label, "FAIL", f"DENIED: {msg[:60]}"))
        else:  # ERROR
            console.print(f"    [red]✗ 發生錯誤：{msg}[/]")
            results.append(OpResult(project_id, label, "FAIL", msg[:80]))

    return results


def run_batch_quota(
    project_ids: list[str],
    model: tuple,
    routing: str,
    targets: dict[str, int | None],
    *,
    yes: bool = False,
) -> list[OpResult]:
    """
    批次配額提升：逐專案呼叫 _quota_one_project。
    先顯示計畫（專案清單 + 目標值）→ 確認 → 執行。
    """
    display_name, _bm, _slug = model

    # 計畫摘要
    console.print(f"\n[bold]即將對 {len(project_ids)} 個專案提升 {display_name} / {routing} 配額：[/]")
    for pid in project_ids:
        console.print(f"  • [cyan]{pid}[/]")
    console.print(f"\n[bold]目標值：[/]")
    for qtype, t in targets.items():
        if t is not None:
            console.print(f"  {QTYPE_LABELS.get(qtype, qtype)}: [green]{_fmt_limit(t)}[/]")

    if not any(v is not None for v in targets.values()):
        console.print("[yellow]未指定任何要提升的配額（--rpm / --input-tpm / --output-tpm），結束。[/]")
        return []

    # 確認
    if not yes:
        if not inquirer.confirm(message="\n確認送出？", default=True).execute():
            console.print("[dim]已取消。[/]")
            return []

    # 逐一執行
    all_results: list[OpResult] = []
    for pidx, pid in enumerate(project_ids, 1):
        if len(project_ids) > 1:
            console.print(f"\n[bold cyan]══ [{pidx}/{len(project_ids)}] {pid} ══[/]")
        else:
            console.print()
        all_results.extend(_quota_one_project(pid, model, routing, targets))

    return all_results


def cmd_quota(args):
    """非互動式提升配額：支援單/多專案。

    用法：
      python main.py quota --project  X     --model slug --routing global --rpm N
      python main.py quota --projects p1,p2 --model slug --routing global --rpm N
      python main.py quota --projects-file projects.txt --model slug --routing global --rpm N
    """
    check_gcloud_auth()

    # 解析專案
    project_ids = parse_projects_input(
        getattr(args, "project", None),
        getattr(args, "projects", None),
        getattr(args, "projects_file", None),
    )

    # 解析模型
    model = _find_model_by_slug(args.model)
    if model is None:
        console.print(f"[red]✗ 找不到模型 slug '{args.model}'[/]")
        console.print(f"  可用：{_available_slugs()}")
        sys.exit(1)

    routing = ROUTING_CLI_MAP[args.routing]

    targets = {
        "rpm":        args.rpm,
        "input_tpm":  args.input_tpm,
        "output_tpm": args.output_tpm,
    }

    if not any(v is not None for v in targets.values()):
        console.print("[yellow]請至少指定一項目標：--rpm / --input-tpm / --output-tpm[/]")
        sys.exit(0)

    results = run_batch_quota(project_ids, model, routing, targets, yes=args.yes)

    print_batch_summary(results, title=f"配額提升結果 — {model[0]} / {routing}")


def cmd_list_models(args):
    """列出所有支援的 Claude 模型；若指定專案則額外顯示開通狀態。

    用法：
      python main.py list-models
      python main.py list-models --project X
      python main.py list-models --projects p1,p2
      python main.py list-models --projects-file projects.txt
    """
    # 沒帶任何 project 參數：純列出清單
    has_project_arg = any([
        getattr(args, "project", None),
        getattr(args, "projects", None),
        getattr(args, "projects_file", None),
    ])

    if not has_project_arg:
        table = Table(title="支援的 Claude 模型")
        table.add_column("顯示名稱", style="bold")
        table.add_column("CLI slug", style="cyan")
        table.add_column("base_model dimension", style="dim")
        for display_name, base_model, slug in CLAUDE_MODELS:
            table.add_row(display_name, slug, base_model)
        console.print(table)
        console.print("\n[dim]提示：加上 --project / --projects / --projects-file 可檢查各專案開通狀態。[/]")
        return

    # 有帶 project 參數：查詢開通狀態 matrix
    check_gcloud_auth()
    project_ids = parse_projects_input(
        getattr(args, "project", None),
        getattr(args, "projects", None),
        getattr(args, "projects_file", None),
    )

    console.print(f"\n[bold]查詢 {len(project_ids)} 個專案 × {len(CLAUDE_MODELS)} 個模型的開通狀態...[/]")
    console.print("[dim]（✅ = 已開通、❌ = 未開通、⚠ = 查詢失敗）[/]\n")

    # 先查每個專案的 Billing + 逐模型 enablement
    matrix: dict[str, dict[str, str]] = {}  # project_id -> {slug: "✅" | "❌" | "⚠"}
    for pid in project_ids:
        console.print(f"  [cyan]{pid}[/] ", end="")
        row: dict[str, str] = {}
        # Billing 未綁定就直接全 ⚠
        if not check_billing(pid):
            for _, _bm, slug in CLAUDE_MODELS:
                row[slug] = "⚠"
            matrix[pid] = row
            console.print("[yellow]⚠ Billing 未綁定[/]")
            continue

        for display_name, _base_model, slug in CLAUDE_MODELS:
            try:
                enabled = is_model_enabled(pid, slug)
                row[slug] = "✅" if enabled else "❌"
            except Exception:
                row[slug] = "⚠"
            console.print(".", end="")
        matrix[pid] = row
        console.print("")

    # 輸出 matrix table
    table = Table(title="模型開通狀態")
    table.add_column("Model", style="bold")
    for pid in project_ids:
        # 長 project id 可能擠，截短顯示
        header = pid if len(pid) <= 20 else pid[:17] + "..."
        table.add_column(header, justify="center")

    for display_name, _base_model, slug in CLAUDE_MODELS:
        row_cells = [f"{display_name}\n[dim]{slug}[/]"]
        for pid in project_ids:
            cell = matrix.get(pid, {}).get(slug, "?")
            row_cells.append(cell)
        table.add_row(*row_cells)

    console.print()
    console.print(table)


def _add_projects_args(p: argparse.ArgumentParser, required: bool):
    """共用：--project / --projects / --projects-file 三選一參數組。"""
    group = p.add_argument_group("目標專案（三選一）")
    group.add_argument("--project", help="單一 GCP 專案 ID")
    group.add_argument("--projects", help="多個 GCP 專案 ID（逗號分隔）")
    group.add_argument(
        "--projects-file", dest="projects_file",
        help="從檔案讀取 project id（一行一個，# 開頭視為註解）",
    )


def parse_args() -> argparse.Namespace:
    """解析 CLI 參數；不帶子指令時回傳 command=None（執行互動選單）。"""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="GCP Vertex AI Claude Model Manager — 互動選單 + 非互動 CLI 子指令",
    )
    sub = parser.add_subparsers(dest="command")

    # enable
    p_enable = sub.add_parser("enable", help="開通模型（支援單/多專案）")
    _add_projects_args(p_enable, required=True)
    p_enable.add_argument("--models",  required=True,
                          help=f"模型 URL slug，逗號分隔。可用：{_available_slugs()}")
    p_enable.add_argument("--headless", action="store_true",
                          help="以 headless 模式跑瀏覽器（適合遠端執行）")
    p_enable.add_argument("-y", "--yes", action="store_true", help="跳過確認提示")

    # quota
    p_quota = sub.add_parser("quota", help="提升配額（支援單/多專案）")
    _add_projects_args(p_quota, required=True)
    p_quota.add_argument("--model",   required=True,
                         help=f"模型 URL slug。可用：{_available_slugs()}")
    p_quota.add_argument("--routing", required=True, choices=list(ROUTING_CLI_MAP.keys()),
                         help="Routing 策略：global / us / eu / regional")
    p_quota.add_argument("--rpm",        type=int, help="目標 RPM 上限")
    p_quota.add_argument("--input-tpm",  type=int, dest="input_tpm",  help="目標 Input TPM 上限")
    p_quota.add_argument("--output-tpm", type=int, dest="output_tpm", help="目標 Output TPM 上限")
    p_quota.add_argument("-y", "--yes", action="store_true", help="跳過確認提示")

    # list-models
    p_list = sub.add_parser("list-models", help="列出支援的模型；加 --project 可檢查開通狀態 matrix")
    _add_projects_args(p_list, required=False)

    return parser.parse_args()


# ──────────────────────────────────────────────
# 互動選單（預設模式，不帶子指令時執行）
# ──────────────────────────────────────────────

def interactive_menu():
    console.print(Panel(
        "[bold cyan]GCP Vertex AI Claude Model Manager[/]\n"
        "自動化開通 Claude 模型與管理配額",
        subtitle="v1.0",
    ))

    # Step 1: 環境檢查
    check_gcloud_auth()

    # Step 2: 載入設定檔
    config = load_config()

    # Step 3: 取得專案清單
    console.print("\n[bold]載入 GCP 專案清單...[/]")
    projects = get_accessible_projects()
    if not projects:
        console.print("[red]找不到任何可存取的 GCP 專案。請確認您的帳號權限。[/]")
        sys.exit(1)
    console.print(f"[green]✓[/] 找到 {len(projects)} 個專案\n")

    # Step 4: 主選單迴圈
    while True:
        action = inquirer.select(
            message="請選擇操作：",
            choices=[
                {"name": "🚀 環境開通（啟用 API + EULA 自動填表）", "value": "enable"},
                {"name": "📊 配額管理（查詢與提升配額）",            "value": "quota"},
                {"name": "🗑️  清除瀏覽器登入狀態",                   "value": "clear_state"},
                {"name": "❌ 離開",                                  "value": "exit"},
            ],
        ).execute()

        if action == "enable":
            # 環境開通流程（支援返回上一步，支援多專案 checkbox）
            enable_step = 1
            selected_pids: list[str] | None = None
            models: list[tuple] | None = None

            while True:
                if enable_step == 1:
                    selected_pids = select_projects_multi(projects)
                    if selected_pids is None:
                        break  # 返回主選單
                    enable_step = 2
                    continue

                if enable_step == 2:
                    models = select_models()
                    if models is None:
                        enable_step = 1  # 返回選專案
                        continue

                    # 直接進入 run_batch_enable（內含 billing/API/已開通檢查 + 確認 + 執行）
                    results = run_batch_enable(
                        selected_pids, models, config,
                        yes=False, headless=False,
                    )
                    if len(results) > 1:
                        print_batch_summary(results, title="環境開通結果")
                    break

        elif action == "quota":
            quota_flow(projects)

        elif action == "clear_state":
            if BROWSER_STATE_FILE.exists():
                BROWSER_STATE_FILE.unlink()
                console.print("[green]✓[/] 瀏覽器登入狀態已清除，下次開通時需重新登入。")
            else:
                console.print("[dim]沒有儲存的登入狀態。[/]")

        elif action == "exit":
            console.print("[dim]再見！[/]")
            break

        console.print()


def main():
    """入口：根據 CLI 子指令分派，沒帶子指令就跑互動選單。"""
    args = parse_args()
    if args.command == "enable":
        cmd_enable(args)
    elif args.command == "quota":
        cmd_quota(args)
    elif args.command == "list-models":
        cmd_list_models(args)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
