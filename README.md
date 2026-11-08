# swisseph-mcp

自建的 **Swiss Ephemeris 遠端 MCP 伺服器**。讓 claude.ai（網頁和手機 App）可以直接計算本命盤、行運、推運和合盤，而不是靠模型憑記憶估算星曆。

- 用 [`pyswisseph`](https://pypi.org/project/pyswisseph/)（Swiss Ephemeris 的 Python 綁定）做計算
- 用官方 `mcp` SDK 的 FastMCP，以 **Streamable HTTP**（stateless、JSON 回應）提供服務
- 只有 **4 個工具**，輸出是壓縮文字，**盡量節省 token**
- 可部署在 Render 免費方案，不需要資料庫，不存任何用戶資料

---

## 運作方式

```
claude.ai / 手機 App
        │  HTTPS  POST /<MCP_SECRET>/mcp   (JSON-RPC)
        ▼
 Render（Docker 容器）
   server.py ── FastMCP ──► 4 個工具 ──► pyswisseph ──► ephe/*.se1
```

1. Claude 判斷需要星盤數據時，呼叫其中一個工具，傳入出生日期、時間、時區和經緯度。
2. 伺服器把當地時間轉成 UTC，再轉成儒略日（Julian Day）。
3. pyswisseph 計算行星黃經、宮位和相位。
4. 結果以壓縮文字回傳，Claude 再根據數據做詮釋。

伺服器**不做任何占星詮釋**，只提供天文計算結果。

---

## 工具

預設採用 **回歸黃道（tropical）、地心（geocentric）**，可用 `opt` 參數切換（見下）。

### `opt`：可選的計算模式

四個工具都有一個可選的 `opt` 字串，用逗號或空格分隔多個選項，不填就是預設。

| 選項 | 效果 |
|---|---|
| `sid=lahiri` | **恆星黃道**，ayanamsa 可選 `lahiri`、`fagan`、`kp`（Krishnamurti）、`raman`、`yukteshwar`、`deluce`；只寫 `sid` 預設用 Lahiri。宮位也一併改為恆星黃道 |
| `topo` | **地平（topocentric）**座標，以你給的經緯度為觀測點。主要影響月亮（約差 0.5°），其他星體幾乎不變 |
| `helio` | **日心**座標。地球（`Ear`）取代太陽和月亮；沒有南北交點和莉莉絲；**不輸出宮位和上升／天頂**（日心沒有意義） |

例子：`opt="sid=lahiri"`、`opt="sid=fagan topo"`、`opt="helio"`。

- 有使用選項時，輸出的第一行會標示模式，例如 `[sid=LAHIRI]`，方便確認。
- `helio` 與 `topo` 不能並用（會忽略 `topo`）。
- 在 `transits`、`progressed`、`synastry` 中，選項會套用到所有星盤；`topo` 使用各人自己的經緯度。
- 填錯會回傳明確的錯誤訊息，例如 `unknown ayanamsa 'xxx'`。

### 通用參數

| 參數 | 說明 | 例子 |
|---|---|---|
| `date` | 出生日期 `YYYY-MM-DD` | `1990-05-15` |
| `time` | 當地時間 `HH:MM`。不知道時間填 `unknown` | `14:30` |
| `tz` | IANA 時區名稱（會正確處理歷史夏令時間） | `Asia/Hong_Kong` |
| `lat` / `lon` | 出生地十進制經緯度，**北緯、東經為正** | `22.3193`, `114.1694` |
| `hsys` | 宮位制，預設 `P` | `P` Placidus、`K` Koch、`W` 整宮制、`R` Regiomontanus、`E` 等宮制 |
| `orb` | 容許度（度），見下表 | |

### `natal`：本命盤

回傳上升（ASC）、天頂（MC）、12 宮頭、各星體位置和所在宮位、相位。

| 參數 | 預設 |
|---|---|
| `date, time, tz, lat, lon` | 必填 |
| `hsys` | `P` |
| `orb` | `8`（六合為其 0.6 倍，即 4.8°） |

### `transits`：行運

某日的行運行星，對照本命盤的相位。

| 參數 | 預設 |
|---|---|
| 本命資料 `date, time, tz, lat, lon` | 必填 |
| `on` | 必填，行運日期 `YYYY-MM-DD`（以該日 UTC 12:00 計算） |
| `orb` | `2` |
| `moon` | `false`（月亮移動太快，預設不計入） |

行運星體：太陽至冥王星、真北交點。不含凱龍、莉莉絲、南交點。

### `progressed`：次限推運

「一日代一年」推運（secondary progression）：推運日 = 出生日 + 年齡（天）。

| 參數 | 預設 |
|---|---|
| 本命資料 | 必填 |
| `on` | 必填，推運到哪一天 |
| `orb` | `1` |

回傳推運的 ASC/MC、推運星體（所在宮位按**本命宮頭**計算）、推運對本命的相位。

### `synastry`：合盤

兩人比較：人物 2 的星體落入人物 1 的哪一宮（以及反向），加上雙方星體之間的相位。

參數與 `natal` 相同，但各加後綴 `1` 和 `2`（`date1, time1, tz1, lat1, lon1, date2, ...`），`hsys` 預設 `P`，`orb` 預設 `5`。

---

## 輸出格式（怎麼讀）

```
ASC 24Vir49 MC 24Gem51
H 1:24Vir49 2:23Lib37 3:24Sco05 ...
Sun 24Tau10 h9; Moon 24Cap20 h4; Mer 08Tau02R h8; ...
Asp: Moon tri Sun 0.2; Jup opp Ura 0.3; ...
```

| 符號 | 意思 |
|---|---|
| `24Tau10` | 金牛座 24°10′（度 + 星座縮寫 + 分） |
| 後面的 `R` | 逆行 |
| `h9` | 第 9 宮 |
| `Moon tri Sun 0.2` | 月亮與太陽三分相，誤差 0.2° |

**星座縮寫：** Ari Tau Gem Can Leo Vir Lib Sco Sag Cap Aqu Pis
**星體縮寫：** Sun Moon Mer Ven Mar Jup Sat Ura Nep Plu、`Chi` 凱龍、`Node` 真北交點、`SNode` 南交點、`Lil` 平均黑月莉莉絲（Mean Apogee）
**相位縮寫：** `conj` 合、`opp` 沖、`tri` 三分、`squ` 四分、`sex` 六分
**相位方向：** `transits` 的 `Asp(T→N)` 中，前者是行運星；`progressed` 的 `Asp(P→N)` 中，前者是推運星。

為了省 token：

- 相位按誤差由小到大排序，**最多 30 條**
- 南交點不列入相位（與北交點對稱，會重複）
- 每次回傳約 200–400 token；4 個工具的定義合共約 900 token

---

## 範例

在 claude.ai 加入 connector 後，直接用自然語言問：

> 用 swisseph 算 1990-05-15 14:30 香港出生的本命盤（22.3193N, 114.1694E），然後看 2026-11-08 的行運。

用恆星黃道（Lahiri）：

> 用 swisseph，opt 設 sid=lahiri，算同一個人的本命盤。

驗證用的標準答案（本命盤）：

| 模式 | ASC | 太陽 |
|---|---|---|
| 預設（回歸） | `24Vir49` | `24Tau10` |
| `sid=lahiri` | `01Vir05` | `00Tau26` |

太陽的差約 23°44′，等於 1990 年的 Lahiri ayanamsa。

---

## 部署（Render 免費方案）

### 1. 檔案結構

```
.
├── server.py          # MCP 伺服器
├── requirements.txt   # pyswisseph、mcp[cli]<2
├── Dockerfile         # 需要 gcc 和 g++ 來編譯 pyswisseph
├── ephe/              # 星曆檔（sepl_18、semo_18、seas_18）
└── README.md
```

### 2. 步驟

1. 把整個資料夾推上 GitHub（不要上傳 `.venv`）。
2. [render.com](https://render.com) → **New → Web Service** → 選這個 repo。
3. Language 選 **Docker**，Instance Type 選 **Free**。
4. Environment 新增 `MCP_SECRET` = 一串隨機字串（`openssl rand -hex 16`）。
5. Deploy，首次建置約 2–4 分鐘（pyswisseph 要編譯）。

### 3. 環境變數

| 變數 | 必填 | 說明 |
|---|---|---|
| `MCP_SECRET` | 建議 | 設了之後，MCP 端點變成 `/<MCP_SECRET>/mcp`；沒設則是 `/mcp`（任何人知道網址都能用） |
| `PORT` | 否 | Render 會自動提供；本機預設 `7860` |

### 4. 端點

| 路徑 | 方法 | 用途 |
|---|---|---|
| `/<MCP_SECRET>/mcp` | POST | MCP 端點，貼進 claude.ai |
| `/health` | GET / HEAD | 健康檢查，回 `ok`，給 UptimeRobot 用 |

### 5. 加入 claude.ai

Settings → Connectors → **Add custom connector**，貼上：

```
https://<你的服務名>.onrender.com/<MCP_SECRET>/mcp
```

在網頁版加入一次，手機 App 會自動同步。

### 6. 防止休眠（UptimeRobot）

Render 免費方案閒置 **15 分鐘**就休眠，喚醒約要 1 分鐘，第一次呼叫可能超時。

1. 在 [uptimerobot.com](https://uptimerobot.com) 註冊（免費）。
2. **+ New monitor** → 類型 **HTTP(s)**。
3. URL 填 `https://<你的服務名>.onrender.com/health`（**不要**填含 secret 的 MCP 網址）。
4. 間隔設 **5 分鐘**，建立。

Render 免費方案每月 750 小時，一個服務全天開著約 744 小時，剛好夠用，所以只能放這一個服務。

### 7. 更新程式

修改後 push 到 GitHub 的 `main`，Render 會自動重新部署。

---

## 本機開發

**不要用系統 pip 直接裝**，請用 venv：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
```

啟動並測試：

```bash
MCP_SECRET=test123 PORT=8799 python server.py
```

```bash
curl -s localhost:8799/health
curl -s localhost:8799/test123/mcp -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## 疑難排解

| 症狀 | 原因與解法 |
|---|---|
| `Failed building wheel for pyswisseph`，`install_layout` | 用了系統 pip（Debian/Ubuntu 打過補丁）。改用 venv，並先 `pip install -U setuptools wheel` |
| `No such file or directory: 'g++'` | pyswisseph 含 C++ 檔案，要裝 `g++`（Dockerfile 已處理） |
| `No module named 'mcp.server.fastmcp'` | 裝到了 mcp 2.x（`FastMCP` 已改名）。`requirements.txt` 已鎖定 `mcp[cli]<2` |
| PyPI 上找不到 pyswisseph 的 wheel | 正常，它只提供原始碼，一定要編譯 |
| 第一次呼叫很慢或超時 | Render 休眠中，等約 1 分鐘重試；設好 UptimeRobot 可避免 |
| `/health` 回 404 | 部署的 `server.py` 是沒有 `/health` 的舊版，更新 repo 即可 |
| `GET` MCP 網址回 406 | 正常，MCP 端點只接受帶有正確 `Accept` 標頭的 POST |
| 凱龍沒有出現在結果 | `ephe/` 缺少 `seas_18.se1`。Chiron 不在內建的 Moshier 星曆內，程式會靜默略過 |

---

## 限制

- **預設是回歸黃道、地心座標。** 恆星黃道、地平和日心要靠 `opt` 開啟；尚未支援：自訂 ayanamsa 數值、地平座標的海拔（固定為 0 米）。
- **`opt` 使用 Swiss Ephemeris 的全域設定**（`set_sid_mode`、`set_topo`），每次呼叫都會重新設定，單人使用沒有問題；若同時有大量並行請求，理論上可能互相干擾。
- **不知道出生時間（`unknown`）：** 以當地中午計算，不輸出宮位和上升／天頂，月亮可能有最多約 ±6° 的誤差。
- **極圈附近：** Placidus、Koch 等宮位制在高緯度無法計算，程式會**靜默改用整宮制（Whole Sign）**。
- **星曆檔範圍：** 隨附的 `*_18.se1` 涵蓋約公元 1800–2400 年。
- **時區：** 使用 Python `zoneinfo`。夏令時間轉換期間不存在或重複的當地時間，會取第一個解釋，不會報錯。
- **經緯度由 Claude 提供**，伺服器本身不做地名查詢。出生地不明確時，請先確認座標。
- **沒有登入機制。** 安全性只靠不公開的 URL 路徑（`MCP_SECRET`）。伺服器不儲存任何資料，風險主要是他人佔用你的免費額度，但請不要公開貼出完整 MCP 網址。
- 免費方案沒有 SLA，Render 可能隨時重啟服務。

---

## 授權與致謝

- 星曆引擎：[Swiss Ephemeris](https://www.astro.com/swisseph/)，Astrodienst AG，採 **AGPL-3.0 / 商業雙重授權**
- 綁定：[pyswisseph](https://github.com/astrorigin/pyswisseph)（AGPL-3.0）
- MCP SDK：[modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- `ephe/` 內的 `.se1` 檔來自 Astrodienst 官方的 [swisseph repo](https://github.com/aloistr/swisseph)

由於依賴 AGPL 的元件並以網路服務形式提供，若你公開此服務，請留意 AGPL 的原始碼提供義務。這裡不是法律意見，如有商業用途請自行查閱授權條款。
