# PRD — Threads 帳號貼文爬取與數據分析工具

## 1. 產品目標與問題定義

**要解決的使用者問題**：內容/行銷團隊想評估一個 Threads 帳號的發文表現（哪些內容互動好、發文時間規律、內容類型分布、為什麼某些貼文成功或失敗），但目前只能手動一篇篇看，沒有自動化工具整理成可讀的報告。

**目標使用者**：公司內容團隊、行銷企劃，需要定期檢視自家或競品帳號表現的人。

**使用情境**：使用者登入系統 → 輸入想分析的 Threads 帳號 → 系統自動蒐集該帳號近期貼文 → 產出含指標、圖表、分群成因分析、內容策略觀察的報告 → 視需要匯出或與其他帳號比較。

**本次功能不處理的範圍**：
- 私人帳號（無公開資料可爬取）
- 即時監控或排程自動更新（僅支援使用者手動觸發/重跑）
- 歷史超過近期貼文範圍的完整發文記錄（只抓近期至少 30 篇）
- 留言內容本身的情緒分析（僅分析貼文本身）
- 多語系介面（僅繁中/英文介面）

---

## 2. 功能描述

### 2.1 使用者註冊/登入
- **目的**：確保只有授權使用者能建立與查看分析任務
- **觸發條件**：使用者訪問網站任一需登入頁面
- **輸入資料**：Email、密碼（註冊時需二次輸入密碼確認）
- **處理流程**：Supabase Auth 驗證帳密 → 建立/驗證 session
- **輸出結果/使用者可見狀態**：成功→導向 dashboard；失敗→顯示錯誤訊息並停留在登入頁

### 2.2 建立分析任務
- **目的**：讓使用者針對指定 Threads 帳號啟動一次完整的爬取+分析流程
- **觸發條件**：已登入使用者在 dashboard 點擊「新增分析」
- **輸入資料**：Threads 帳號 username 或完整帳號 URL
- **處理流程**：驗證輸入格式 → 建立 `analysis_tasks` 記錄（status: pending）→ 觸發爬蟲 → 資料清理 → 數據分析 → 互動表現分群分析 → 寫入 `analysis_results`（status: completed/failed）
- **輸出結果/使用者可見狀態**：任務列表顯示新任務，狀態即時更新（pending → processing → completed/failed）

### 2.3 查看報告
- **目的**：讓使用者檢視某次分析任務的完整結果
- **觸發條件**：使用者點擊已完成（completed）的任務
- **輸入資料**：task_id
- **處理流程**：讀取該 task 對應的 `posts` 與 `analysis_results`
- **輸出結果/使用者可見狀態**：總覽指標卡片、Top 5 貼文表格、至少 2 張圖表、分群成因分析、3 點內容策略觀察、LLM 建議文字

### 2.4 重跑任務
- **目的**：讓使用者針對同一帳號重新取得最新資料
- **觸發條件**：使用者在任務列表點擊「重跑」
- **輸入資料**：既有 task_id 對應的帳號
- **處理流程**：檢查快取（1 小時內是否已有結果）→ 無快取則重新執行完整 pipeline → 更新該任務資料
- **輸出結果/使用者可見狀態**：任務狀態變回 processing，完成後更新報告內容與「最後更新時間」

### 2.5 刪除任務
- **目的**：讓使用者移除不再需要的分析任務
- **觸發條件**：使用者在任務列表點擊「刪除」並二次確認
- **輸入資料**：task_id
- **處理流程**：刪除 `analysis_tasks` 記錄（搭配 cascade 刪除關聯的 `posts`、`analysis_results`）
- **輸出結果/使用者可見狀態**：任務從列表移除，無法復原（刪除前彈窗二次確認）

### 2.6 多帳號比較
- **目的**：讓使用者並列比較兩個以上帳號的表現
- **觸發條件**：使用者在任務列表勾選 2 個以上已完成任務，點擊「比較」
- **輸入資料**：多個 task_id
- **處理流程**：讀取各任務的 `analysis_results`，彙整成同一組比較用資料結構
- **輸出結果/使用者可見狀態**：並列圖表（如平均互動率對比）與指標表格

### 2.7 匯出資料
- **目的**：讓使用者將分析結果帶出系統做進一步利用
- **觸發條件**：使用者在報告頁點擊「匯出 CSV」或「匯出 JSON」
- **輸入資料**：task_id、匯出格式選擇
- **處理流程**：讀取 `posts` 與 `analysis_results` 並轉換成對應格式
- **輸出結果/使用者可見狀態**：瀏覽器觸發檔案下載

### 2.8 互動表現分群分析
- **目的**：找出同一帳號裡「表現好」跟「表現差」的貼文各自的共同特徵，給出可解釋的成因，而非只給數字
- **觸發條件**：數據分析階段完成後自動觸發（屬於建立分析任務 pipeline 的一環，不需使用者額外操作）
- **輸入資料**：該任務全部已清理的貼文資料（含 likes、replies〔若可得〕、text 等欄位）
- **處理流程**：
  1. 依「讚數＋回覆數」的綜合互動分數，將貼文排序後分成三組：高互動／中互動／低互動（例如依百分位數切 33%/66%）
  2. 每組各挑 3–5 篇代表性貼文（優先取組內互動分數最具代表性、非離群值的樣本）
  3. 對三組使用**同一份 prompt 模板**（一致的 NLP 方法）請 LLM 分析該組貼文的共同特徵（內容類型、語氣、長度、主題等），產出「這組為什麼表現好/差」的文字分析
- **輸出結果/使用者可見狀態**：報告頁顯示三組（高/中/低互動）各自的代表貼文列表＋LLM 產出的成因分析文字，並明確標示「以下為觀察與 AI 推論，非絕對因果」

---

## 3. 使用者流程

1. 使用者訪問網站 → 未登入則導向登入頁
2. 登入成功 → 進入 dashboard，看到既有任務列表（若無任務則顯示空狀態引導）
3. 點擊「新增分析」→ 輸入帳號 → 送出
4. 系統顯示任務處理中 → 背景執行：爬取（失敗則 fallback mock 並標記來源）→ 清理 → 分析 → 依互動表現分群並用 LLM 分析成因
5. 任務完成 → 使用者點擊進入報告頁，查看總覽指標、Top 5、圖表、分群成因分析、內容策略觀察、LLM 建議
6. 使用者可選擇：匯出 CSV/JSON、勾選多個任務進行比較、重跑任務、刪除任務
7. 使用者可隨時登出

---

## 4. 資料與權限（Supabase）

| 資料表 | 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|---|
| `analysis_tasks` | id | uuid (PK) | ✓ | |
| | user_id | uuid (FK→auth.users) | ✓ | |
| | account | text | ✓ | Threads username |
| | status | text | ✓ | pending/processing/completed/failed |
| | created_at | timestamptz | ✓ | |
| | updated_at | timestamptz | ✓ | 用於 1 小時快取判斷 |
| `posts` | id | uuid (PK) | ✓ | |
| | task_id | uuid (FK→analysis_tasks) | ✓ | |
| | post_id | text | ✓ | Threads 原始貼文 ID，同 task 內需唯一 |
| | text | text | | 可為空（純圖片貼文） |
| | likes | int | ✓ | 預設 0 |
| | reposts | int | ✓ | 預設 0 |
| | quotes | int | ✓ | 預設 0 |
| | replies | int（nullable）| | 已知限制：固定為 null |
| | posted_at | timestamptz | | 可為空（抓取失敗的欄位） |
| | source | text | ✓ | 'scraped' 或 'mock' |
| `analysis_results` | id | uuid (PK) | ✓ | |
| | task_id | uuid (FK→analysis_tasks) | ✓ | 與 task 一對一 |
| | metrics | jsonb | ✓ | 平均值、分布等結構化指標 |
| | insights | jsonb | ✓ | 文字觀察、LLM 建議 |
| | group_analysis | jsonb | ✓ | 高/中/低三組的代表貼文 ID 清單＋各組 LLM 成因分析文字（結構：`{high: {post_ids: [], analysis: ""}, mid: {...}, low: {...}}`）|
| | created_at | timestamptz | ✓ | |

**資料關聯**：`analysis_tasks` 1—N `posts`；`analysis_tasks` 1—1 `analysis_results`；皆透過 `user_id`（`analysis_tasks` 上）追溯擁有者。

**存取權限（RLS）**：
- `analysis_tasks`：`user_id = auth.uid()` 才能 SELECT/INSERT/UPDATE/DELETE
- `posts`、`analysis_results`：透過 `task_id` join `analysis_tasks`，僅當 `analysis_tasks.user_id = auth.uid()` 時可存取
- 爬蟲與 LLM 分析寫入資料的動作走 server-side（service role key），不經過前端 anon key

---

## 5. 例外情境

| 功能 | 情境 | 行為 |
|---|---|---|
| 登入 | 帳密錯誤 | 顯示「帳號或密碼錯誤」，不指出是哪一項 |
| 登入 | 帳號不存在 | 同上，不洩漏帳號是否存在 |
| 建立任務 | 帳號格式不合法（含特殊符號等）| 前端即時驗證並提示格式錯誤 |
| 建立任務 | 帳號不存在/私人帳號 | 爬蟲回傳空結果 → 任務標記 failed，顯示「無法取得公開資料」 |
| 建立任務 | 資料不足（貼文數 < 30）| 允許以實際抓到的數量繼續分析，報告頁標註「實際樣本數 N 篇」 |
| 建立任務 | 爬取受阻（被擋/逾時）| retry 3 次（指數退避）→ 仍失敗則 fallback mock dataset，`posts.source` 標記為 mock，報告頁顯示資料來源警示 |
| 建立任務 | 欄位缺失（如 posted_at 為空）| 該筆資料對應分析指標以排除/null 處理，不中斷整體流程 |
| 建立任務 | 回覆數不可得 | `replies` 固定為 null，前端顯示「N/A（需認證端點，基於帳號安全考量未採集）」 |
| 建立任務 | 重複建立同帳號任務 | 允許建立新任務版本（不覆蓋），供歷史比較 |
| 建立任務 | API 逾時 | 單次請求 timeout 20 秒，重試 3 次後整體任務標記 failed |
| 分群分析 | 總貼文數 < 9 篇（無法穩定切三組且每組 ≥3 篇）| 跳過分群，報告頁顯示「樣本數不足，略過分群分析」 |
| 分群分析 | LLM API 呼叫失敗/逾時 | 該組顯示「分析暫時無法產生，可稍後重跑」，不影響其餘指標顯示 |
| 分群分析 | 某組貼文全部缺少文字內容（如純圖片）| 該組分析改以「圖片/連結型貼文，無法進行文字層級分析」說明，不強行讓 LLM 編造 |
| 重跑任務 | 任務正在 processing 中又被觸發重跑 | 忽略本次請求，提示「任務執行中，請稍候」 |
| 刪除任務 | 刪除不存在的 task_id（如已被刪除）| 回傳 404，前端提示「任務已不存在」 |
| 多帳號比較 | 勾選任務中有未完成的 | 禁用比較按鈕並提示「請選擇已完成的任務」 |
| 匯出 | 任務無資料可匯出 | 禁用匯出按鈕 |

---

## 6. 驗收標準（Given/When/Then，依功能列出成功/失敗/邊界案例）

**6.1 註冊/登入**
- Given 未登入使用者, When 訪問 dashboard, Then 導向登入頁
- Given 正確帳密, When 送出登入表單, Then 導向 dashboard 且 session 建立
- Given 錯誤密碼, When 送出登入表單, Then 顯示「帳號或密碼錯誤」且停留在登入頁

**6.2 建立分析任務**
- Given 已登入使用者輸入有效公開帳號, When 建立任務, Then 任務最終狀態為 completed，且 `posts` 表有 ≥1 筆資料
- Given 輸入不存在的帳號, When 建立任務, Then 任務狀態為 failed，前端顯示對應錯誤訊息
- Given 爬取過程全部 retry 失敗, When 建立任務, Then 自動切換為 mock 資料集，任務仍標記 completed，但 `posts.source` 全為 'mock'
- Given 同一帳號 1 小時內已有分析結果, When 再次建立任務, Then 直接複用既有結果，不重新爬取

**6.3 查看報告**
- Given 任務狀態為 completed, When 使用者開啟報告頁, Then 顯示總覽指標、Top 5、≥2 張圖表、分群成因分析、3 點觀察、LLM 建議
- Given 任務狀態為 failed, When 使用者點擊該任務, Then 顯示失敗原因，不進入報告頁

**6.4 重跑任務**
- Given 任務已存在且不在 processing 中, When 使用者點擊重跑, Then 狀態變回 processing，完成後更新資料與時間戳
- Given 任務正在 processing 中, When 使用者再次點擊重跑, Then 請求被忽略並提示執行中

**6.5 刪除任務**
- Given 使用者擁有該任務, When 二次確認刪除, Then 該任務與關聯 posts/analysis_results 一併被刪除
- Given 使用者嘗試刪除不屬於自己的任務, When 送出刪除請求, Then 被 RLS 拒絕，回傳權限錯誤

**6.6 多帳號比較**
- Given 使用者勾選 2 個已完成任務, When 點擊比較, Then 顯示並列指標與圖表
- Given 使用者僅勾選 1 個任務, When 嘗試比較, Then 比較按鈕為禁用狀態

**6.7 匯出**
- Given 任務已完成且有資料, When 點擊匯出 CSV, Then 瀏覽器下載對應 CSV 檔，欄位與 `posts`/`analysis_results` 一致
- Given 任務無資料, When 嘗試匯出, Then 匯出按鈕為禁用狀態

**6.8 跨使用者隔離（RLS）**
- Given 使用者 A 與 B 各自建立任務, When A 查詢任務列表, Then 只看到 A 自己的任務，看不到 B 的

**6.9 資料清理（邊界案例）**
- Given 原始貼文資料含重複 post_id, When 執行清理, Then 輸出資料無重複 post_id
- Given 貼文缺少 posted_at, When 執行清理與時間分布分析, Then 該筆資料不計入時間分布統計，但仍保留在總覽指標的貼文總數中

**6.10 互動表現分群分析**
- Given 任務貼文數 ≥9 篇, When 分析完成, Then `analysis_results.group_analysis` 含高/中/低三組，各組至少 3 篇代表貼文與一段 LLM 成因分析文字
- Given 任務貼文數 <9 篇, When 分析完成, Then 報告頁顯示「樣本數不足，略過分群分析」，其餘指標照常顯示
- Given 三組使用同一份 prompt 模板, When 檢查產出結果, Then 三組分析文字的結構/格式一致（僅內容依該組貼文不同）
- Given LLM 呼叫失敗, When 該組分析執行, Then 該組顯示錯誤提示，不影響其他兩組與任務整體 completed 狀態

---

## 7. 非功能需求

- **安全性**：Supabase anon key 僅用於前端公開操作（登入、讀取自己的資料）；爬蟲與 LLM 分析寫入資料走 server-side service role key，不暴露於前端；RLS 作為資料隔離的最後防線
- **效能/快取**：同一帳號 1 小時內重複建立任務，直接複用既有 `analysis_results`，不重新觸發爬蟲與 LLM 分析
- **可用性**：任務狀態需即時反映（pending/processing/completed/failed），避免使用者誤以為卡死
- **合規**：爬取範圍限於公開可見資料；回覆數涉及認證端點，基於帳號安全考量不採集（詳見 README 已知限制）
- **日誌**：爬蟲所有 retry/失敗事件、LLM 呼叫失敗事件需寫入 log，便於除錯
- **測試**：資料清理函式（去重、時區轉換、缺失值處理）、分析函式（平均值、Top 5、時間分布）、分群邏輯（切分三組的百分位數計算）需有單元測試，測試資料使用 mock dataset
- **部署**：前端使用 Next.js，部署於 Vercel；所需環境變數（Supabase URL、anon key、service role key、LLM API key 等）列於 `.env.example`

---

## 8. 開發拆解與優先級

| Checkpoint | 內容 | 優先級 | 依賴 | 預估時間 |
|---|---|---|---|---|
| 1 | PRD 定稿 | Must | — | 30 分鐘 |
| 2 | 爬蟲（Scrapling+StealthyFetcher，已驗證可取得 like/repost/quote）| Must | 1 | 已完成 |
| 3 | 資料清理（去重、缺失值、時區、字數/hashtag/mention/URL 統計）| Must | 2 | 30 分鐘 |
| 4 | 數據分析+圖表（指標計算、Top 5、時間分布、關鍵字）| Must | 3 | 45 分鐘 |
| 5 | 互動表現分群分析（三組切分 + 一致 NLP/LLM 成因分析）| Must | 4 | 30 分鐘 |
| 6 | Supabase schema + RLS | Must | 1 | 30 分鐘 |
| 7 | Next.js 登入+dashboard+報告頁 | Must | 6 | 60 分鐘 |
| 8 | LLM 內容策略建議+多帳號比較+匯出 | Should | 5, 7 | 45 分鐘 |
| 9 | Docker/一鍵啟動+單元測試 | Could | 2–8 | 30 分鐘 |
