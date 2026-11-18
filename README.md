# Small Career

把招聘網站上的職缺收集起來，再讓 AI 按照你的需求，分成「適合」「可能符合」和「不適合」。首頁和評估頁都能看卡片、切換分類，不用一筆一筆自己整理。

## 怎麼使用

1. 到「設定」選擇 OpenAI、Gemini 或自訂服務並填入金鑰。用「選擇模型」或手動輸入加入模型，點標籤即可移除。第一個模型優先，遇到逾時、429 或其他可重試錯誤會依序換模型。也可以勾選「將不同職缺分配給不同模型」，由同一服務內的模型分攤工作。
2. 到「職位評估」選擇允許程式讀取的公開職缺網址。新設定預填 `https://www.linkedin.com/`；美國遠端 Business Analyst／Analyst 仍是預設的 AI 評估條件，不會自動套用成 LinkedIn 搜尋篩選。舊設定不會被覆蓋。LinkedIn 首頁不是職缺搜尋結果，且 LinkedIn 不允許未經明確許可的自動存取。
3. 按「一鍵收集並評估」，確認後自動收集並評估待處理職缺。也能保留兩段式操作，先「開始爬取」，之後再按「開始 AI 處理」。
4. 結果會出現在卡片與資料庫中，不再自動產生 CSV。想清空全部職缺，可到「設定」點「初始化資料庫」並完成兩次確認。

左下角署名上方的 **A/文** 可以切換繁體中文和英文。職缺評估理由固定使用繁體中文。

## 先知道這幾件事

- **API 金鑰以明文存在本機設定檔。** 畫面上的星號只是遮住顯示；複製時仍是真實金鑰。不要分享設定檔。
- AI 分析網頁、整理需求和評估職缺都可能收費，傳送前會詢問。請不要提供含私人資料的頁面。
- 不是每個網站都能抓。程式會遵守 robots.txt，不會繞過登入、驗證碼或封鎖。HTTP 403 代表網站拒絕存取，錯誤訊息會標示發生階段；可以先用一般瀏覽器確認網址是否公開可用。
- 「職位評估」的「在瀏覽器開啟 LinkedIn 職缺」會用系統預設瀏覽器開啟 LinkedIn Jobs。如果該瀏覽器仍保有有效的登入狀態，不必重新登入；若 LinkedIn 要求登入或驗證，請在瀏覽器內完成。App 不會讀取密碼或 Cookie，也不會把登入狀態交給自動收集視窗。
- 手動找到職缺後，可用「職位評估 → 貼上 LinkedIn 職缺」貼上單筆職缺的網址與說明，再按「加入待評估」。此步驟只存本機，不會讀取網站或呼叫 AI；按「開始 AI 處理」並確認後才會送出評估。同一職缺的相同文字不會重複入列。
- LinkedIn 搜尋與分類連結不會當作單筆職缺讀取。遇到網站限流（HTTP 429）時，本次收集會停止，不會自動重試，已收集的職缺仍保留。
- 若提示「AI 服務」回傳 HTTP 429，請查看 AI 服務商的用量與額度。暫時限流可稍後再試；同一帳戶共用的額度用完時，換備用模型也未必有效。
- AI 輔助辨識網頁遇到逾時、HTTP 429 或服務端 5xx，會依設定順序嘗試備用模型。如果 AI 無法辨識列表，但一般規則已找到本頁的職缺，會記錄失敗並繼續收集這些職缺；網站本身的存取限制不受影響。
- 若網頁分析完成後仍找不到職缺，日誌會區分「AI 未選出連結」與「選出的連結不符合單筆職缺網址規則」。請先確認該頁確實顯示職缺，且網站允許自動讀取。
- 瀏覽器使用獨立的臨時環境，不會讀取你的個人 Chrome 資料。爬取期間請不要操作或關閉它。
- 分頁、捲動和「載入更多」有次數限制；AI 也可能漏看或看錯。Levtech 首頁會轉到完整職缺列表，想縮小範圍時請貼篩選後的網址。
- 重複爬取會檢查內容是否更新。沒變的職缺不會重複評估；失敗的職缺可再次處理。停止時可能要等目前的請求結束。
- AI 理由可寫完整的繁體中文分析；卡片仍顯示摘要，點「查看詳情」可看全文。
- 填入 API 金鑰後，打開「選擇模型」會在背景向 OpenAI 或 Gemini 的官方 API 查詢金鑰可見的模型；同一設定最多每五分鐘自動查一次。「更新可用模型」可立即重查。如果選單已開啟，關閉再打開即可查看更新結果。未連線時可用內建清單，查詢不會更動已選標籤或備援順序。API 列出的模型不一定支援職缺評估需要的結構化輸出。

## 資料存在哪裡

所有工作資料都放在 `data` 資料夾：開發時位於專案內；Windows 版位於 EXE 旁；macOS 版位於 `~/Library/Application Support/SmallCareer/data`，不會寫入 `.app` 裡。分發時不用附帶自己的 `data`。

| 檔案／資料夾 | 用途 |
|---|---|
| `config.json` | 金鑰、求職需求、網站及模型順序 |
| `jobs.sqlite3` | 職缺原文、評估結果和待處理狀態 |
| `csv` | 舊版曾匯出的分類結果；新版不再自動更新或刪除 |
| `log` | 操作和失敗原因，只保留最近五次紀錄 |
| `browser` | 瀏覽器的臨時工作資料，正常關閉後清理 |

首次使用新版會將舊位置的設定、SQLite、CSV 和日誌複製到 `data`，不覆寫已有資料，舊檔也不會刪除。完成後不再自動匯入；確認資料齊全後可自行移除舊檔。整個 `data` 已排除於 Git 之外。

開發時日誌會同步顯示在 IDE 終端；分發的 EXE 不會開啟命令列視窗，只將日誌寫入 `data\log`。日誌會遮住網址和已知金鑰，但仍請先檢查內容再分享。以上資料都已加入 Git 排除規則。

這裡保留 SQLite，是因為它能記住哪些職缺已處理、哪些需要重試，也比較不怕寫到一半中斷。舊版的評估理由長度限制會自動遷移，既有職缺不會被刪除。「初始化資料庫」只清空職缺資料表，不會清除設定、舊 CSV 或日誌。

### 模型與工作流程

- `modules/settings_page.py`：各服務的模型選單、標籤與設定。主要模型仍用原有的 `model`（以及各服務的 `profiles`），新增 `backup_models`（依服務分組的有序備用陣列）和 `distribute_models`（預設關閉）。舊設定不需手動補欄位。
- `modules/core.py`：模型清單查詢、失敗切換、SQLite 遷移與重置。最多四個 API 工作執行緒，SQLite 由單一協調執行緒寫入；`jobs` 和 `pending_jobs` 欄位不變。
- `modules/app.py` 與 `modules/evaluation_page.py`：收集與評估串接、二次確認、主執行緒更新卡片。網站拒絕存取時停止收集，保留已寫入的待處理項目。

## 開發與測試

需要 Python 3.10 以上，並包含 Tkinter：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

```powershell
python -W error -m unittest discover -s tests -v
```

測試不使用真實 AI 金鑰；瀏覽器測試需要已安裝 Chromium。

## 打包 Windows 與 macOS

先將原始碼與打包設定推送到 GitHub（首次使用要把工作流程放到預設分支），安裝 [GitHub CLI](https://cli.github.com/) 並執行 `gh auth login`。然後在 Windows 雙擊 `packing\build.cmd`，或在終端執行：

```powershell
.\packing\build.cmd
```

腳本會讓 GitHub Actions 分別在 Windows、Apple Silicon Mac 和 Intel Mac 上打包，完成後下載至 `packing\dist\<執行編號>`。也可在 GitHub 的 **Actions → Package Small Career → Run workflow** 啟動，再從該次執行頁下載成品。PyInstaller 需要在目標作業系統上打包，不能在 Windows 直接編出 Mac 程式。

- **Windows x64**：分發 `SmallCareer.exe`，只需要這一個檔案。
- **macOS 15+**：Apple Silicon 選 `SmallCareer-macOS-arm64.zip`，Intel 選 `SmallCareer-macOS-x86_64.zip`。解壓後開啟 `SmallCareer.app`。目前未使用 Apple Developer ID 簽署、也未公證，從網路下載後可能被 Gatekeeper 攔下；正式公開分發前應完成簽署與公證。

兩個平台都隨程式附帶 Chromium，不需另外安裝 Python 或瀏覽器。打包只使用 GitHub 上的已提交原始碼，不會上傳本機 `data`。

### 只打包目前的電腦

```powershell
.\packing\build.cmd --windows-only
```

Windows 輸出為 `packing\dist\SmallCareer.exe`。若在 Mac 上要本機打包（需要含 Tkinter 的 Python 3 和 Xcode Command Line Tools），在專案目錄執行 `bash packing/build-macos.sh`，會產生當前 CPU 架構的 `.app` 與 ZIP。

也可以直接雙擊 `packing\build.cmd`，完成或失敗後視窗會保留，按任意鍵關閉。自動執行時可加上 `--no-pause`。

圖示使用 `packing\icon.ico`，檔案版本資訊使用 `packing\version_info.txt`；修改後重新打包即可。`packing\SmallCareer.spec` 是打包設定，請保留在版本控制中。

打包後會通知 Windows 更新 EXE 的檔案圖示。若檔案總管仍顯示舊圖示或空白，先重新整理，或將 EXE 複製到另一個資料夾確認；Windows 可能仍保留同一路徑的舊快取。檔案圖示與開啟後的視窗圖示是分別設定的。

Windows EXE 內含瀏覽器，啟動解壓可能比較慢，也需要足夠的系統暫存空間。PyInstaller 啟動所需的解壓檔由系統暫存目錄管理，不是使用者工作資料。
