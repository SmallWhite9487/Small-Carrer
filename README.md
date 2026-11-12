# Small Career

把招聘網站上的職缺收集起來，再讓 AI 按照你的需求，分成「適合」「可能符合」和「不適合」。首頁和評估頁都能看卡片、切換分類，不用一筆一筆自己整理。

## 怎麼使用

1. 到「設定」點選 OpenAI、Gemini 或自訂服務的分頁標籤，填入金鑰、模型，以及你想找什麼樣的工作。各服務會保留各自的設定。需求用自己的話寫就好，也能請 AI 幫忙整理，確認後再套用。
2. 到「職位評估」貼上公開的職缺搜尋網址。網站可以儲存，下次直接選。
3. 按「開始爬取」。預設會開啟瀏覽器讀取網頁；若同意 AI 協助，它也會幫忙辨識職缺和下一頁。
4. 收集完成或停止爬取後，按「開始 AI 處理」。結果會出現在卡片裡，也會自動產生三類 CSV。

左下角署名上方的 **A/文** 可以切換繁體中文和英文。職缺評估理由固定使用繁體中文。

## 先知道這幾件事

- **API 金鑰以明文存在本機設定檔。** 畫面上的星號只是遮住顯示；複製時仍是真實金鑰。不要分享設定檔。
- AI 分析網頁、整理需求和評估職缺都可能收費，傳送前會詢問。請不要提供含私人資料的頁面。
- 不是每個網站都能抓。程式會遵守 robots.txt，不會繞過登入、驗證碼或封鎖。HTTP 403 代表網站拒絕存取，錯誤訊息會標示發生階段；可以先用一般瀏覽器確認網址是否公開可用。
- 瀏覽器使用獨立的臨時環境，不會讀取你的個人 Chrome 資料。爬取期間請不要操作或關閉它。
- 分頁、捲動和「載入更多」有次數限制；AI 也可能漏看或看錯。Levtech 首頁會轉到完整職缺列表，想縮小範圍時請貼篩選後的網址。
- 重複爬取會檢查內容是否更新。沒變的職缺不會重複評估；失敗的職缺可再次處理。停止時可能要等目前的請求結束。
- AI 理由超過 60 字等不合規結果不會寫入。請再次處理或換模型，不會直接截掉文字。

## 資料存在哪裡

所有工作資料都放在 `data` 資料夾：開發時位於專案內，EXE 版則位於 EXE 旁邊，請選擇可以寫入的位置。分發時只需要 EXE，不用附帶自己的 `data`。

| 檔案／資料夾 | 用途 |
|---|---|
| `config.json` | 金鑰、求職需求和網站設定 |
| `jobs.sqlite3` | 職缺原文、評估結果和待處理狀態 |
| `csv` | 可用 Excel 開啟的分類結果 |
| `log` | 操作和失敗原因，只保留最近五次紀錄 |
| `browser` | 瀏覽器的臨時工作資料，正常關閉後清理 |

首次使用新版會將舊位置的設定、SQLite、CSV 和日誌複製到 `data`，不覆寫已有資料，舊檔也不會刪除。完成後不再自動匯入；確認資料齊全後可自行移除舊檔。整個 `data` 已排除於 Git 之外。

開發時日誌會同步顯示在 IDE 終端；分發的 EXE 不會開啟命令列視窗，只將日誌寫入 `data\log`。日誌會遮住網址和已知金鑰，但仍請先檢查內容再分享。以上資料都已加入 Git 排除規則。

這裡保留 SQLite，是因為它能記住哪些職缺已處理、哪些需要重試，也比較不怕寫到一半中斷。它是 Python 內建功能，不用另外安裝資料庫。CSV 則留給你查看和使用結果。

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

## 打包成 Windows EXE

```powershell
.\packing\build.cmd
```

輸出為 **`packing\dist\SmallCareer.exe`**，是包含瀏覽器的 onefile 版本，使用者不用再安裝 Python 或瀏覽器。打包過程需要網路；工具、快取及輸出都放在 `packing`。

也可以直接雙擊 `packing\build.cmd`，完成或失敗後視窗會保留，按任意鍵關閉。自動執行時可加上 `--no-pause`。

圖示使用 `packing\icon.ico`，檔案版本資訊使用 `packing\version_info.txt`；修改後重新打包即可。`packing\SmallCareer.spec` 是打包設定，請保留在版本控制中。

打包後會通知 Windows 更新 EXE 的檔案圖示。若檔案總管仍顯示舊圖示或空白，先重新整理，或將 EXE 複製到另一個資料夾確認；Windows 可能仍保留同一路徑的舊快取。檔案圖示與開啟後的視窗圖示是分別設定的。

分發產物只有一個 EXE。因為連瀏覽器一起裝進去，EXE 會很大，每次啟動解壓可能比較慢，也需要足夠的系統暫存空間。使用後會建立 `data`；PyInstaller 啟動所需的解壓檔仍由系統暫存目錄管理，不是使用者工作資料。

## 第一次上傳 GitHub

先在 GitHub 建立一個空的 repository，不要先勾選 README。然後在專案目錄執行，把最後的網址換成你自己的：

```powershell
git init
git branch -M main
git add .
git status --short
git diff --cached --stat
# 確認沒有 config、log、CSV、資料庫或打包產物後，再繼續
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_NAME/YOUR_REPOSITORY.git
git push -u origin main
```

Git 可能會請你登入 GitHub。如果資料之前已被 Git 追蹤，光加排除規則不會移除它；先檢查再提交。大型 EXE 請放到 GitHub Releases，不要加入原始碼提交。
