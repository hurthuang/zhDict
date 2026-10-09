# zhDict — NVDA 國語字典與英文翻譯查詢附加元件

[English](#english) | [中文](#中文)

---

## 中文

### 簡介

zhDict 是一個 [NVDA](https://www.nvaccess.org/) 螢幕閱讀器的附加元件，讓使用者可以選取文字後快速查詢字典或翻譯：

- **中文**：查詢[教育部重編國語辭典修訂本](https://dict.revised.moe.edu.tw/)（透過[萌典 API](https://www.moedict.tw/)），顯示注音、詞性、釋義、例句、似義詞等。萌典查無此詞時附上英文翻譯。
- **英文**：查詢 [Wiktionary](https://en.wiktionary.org/)，提供音標、逐義項的中文對應詞、詞性、釋義、例句、同反義詞；並搭配 Google 翻譯將英文釋義翻譯為中文。
- **整句**：選取整句時不查字典，直接翻譯（英文翻成中文、中文翻成英文）。

語言自動判斷，無需手動切換。

---

### 系統需求

- NVDA 2023.1 或更新版本
- Windows 10 / 11
- 網路連線（查詢時需連線至萌典、Wiktionary 及 Google 翻譯）

---

### 安裝

1. 至 [Releases](https://github.com/hurthuang/zhDict/releases) 下載最新的 `.nvda-addon` 檔案
2. 直接雙擊該檔案，NVDA 會提示安裝
3. 重新啟動 NVDA 後即可使用

---

### 使用方式

| 熱鍵 | 功能 |
|---|---|
| `Alt + NVDA + K` | **基本查詢**：注音 + 第一條釋義（中文）；音標 + 中文對應詞 + 第一條釋義（英文） |
| `Alt + Shift + NVDA + K` | **豐富查詢**：完整字典內容，含所有義項、例句、引文、似義詞／同反義詞 |

**使用步驟：**
1. 在任何應用程式中選取要查詢的文字（或先 `Ctrl+C` 複製）
2. 按下熱鍵，NVDA 會唸出查詢的文字
3. 結果顯示於結果視窗，可用方向鍵逐行閱讀，按 `Esc` 關閉

> 熱鍵可在 NVDA 偏好設定 → 按鍵手勢 → **國語字典與翻譯** 中自訂。

**結果視窗（方便低視力使用者閱讀）：**

| 操作 | 功能 |
|---|---|
| `Ctrl + 滾輪`、`Ctrl + 加號／減號`，或「放大字體」「縮小字體」按鈕 | 放大／縮小字體 |
| `Ctrl + 0` | 字體還原預設大小 |
| `Ctrl + T` 或「切換配色」按鈕 | 切換配色：系統預設 → 黑底白字 → 黑底黃字 |

字體大小、配色、視窗大小（含最大化）都會自動記住，下次查詢直接套用。

**自動檢查更新：**
NVDA 啟動時會在背景自動檢查一次是否有新版本，若有才會詢問是否下載安裝；已是最新版本則不會有任何提示。

---

### 資料來源

| 來源 | 用途 |
|---|---|
| [萌典 API](https://www.moedict.tw/) | 中文字典（教育部授權資料） |
| [Wiktionary](https://en.wiktionary.org/) | 英文字典：釋義、例句、音標、同反義詞、逐義項中文翻譯（原用 Free Dictionary API，該服務長期無法連線後改用） |
| Google Translate（非官方端點） | 英文釋義翻譯為中文、單字的各詞性中文對應詞、整句翻譯 |

> **注意**：Google Translate 使用非官方免費端點，未來可能失效。

---

### 已知限制

- 萌典單字查詢需輸入至少兩個字；單一字元請選取後查詢（API 限制）
- 離線時無法使用
- 同義詞、反義詞是單字逐一翻譯，脫離上下文時中文可能不精確

---

## English

### Introduction

zhDict is an [NVDA](https://www.nvaccess.org/) screen reader add-on for quick dictionary lookup and translation:

- **Chinese text**: Queries the [Ministry of Education Revised Mandarin Chinese Dictionary](https://dict.revised.moe.edu.tw/) via the [moedict API](https://www.moedict.tw/), showing phonetics (Bopomofo), part of speech, definitions, examples, and synonyms. Words not found in moedict get an English translation.
- **English text**: Queries [Wiktionary](https://en.wiktionary.org/) for IPA, per-sense Chinese equivalents, part of speech, definitions, examples, and synonyms/antonyms. Definitions are translated into Traditional Chinese via Google Translate.
- **Sentences**: Selected sentences are translated directly instead of looked up (English to Chinese, Chinese to English).

Language is detected automatically — no manual switching needed.

---

### Requirements

- NVDA 2023.1 or later
- Windows 10 / 11
- Internet connection (required for moedict, Wiktionary and Google Translate)

---

### Installation

1. Download the latest `.nvda-addon` file from [Releases](https://github.com/hurthuang/zhDict/releases)
2. Double-click the file; NVDA will prompt you to install it
3. Restart NVDA

---

### Usage

| Hotkey | Function |
|---|---|
| `Alt + NVDA + K` | **Basic lookup**: phonetics + first definition (Chinese); IPA + Chinese equivalents + first definition (English) |
| `Alt + Shift + NVDA + K` | **Rich lookup**: full dictionary content with all senses, examples, quotations, and synonyms/antonyms |

**Steps:**
1. Select text in any application (or copy with `Ctrl+C`)
2. Press the hotkey — NVDA will announce the text being looked up
3. Results appear in a result window; read line by line with the arrow keys, press `Esc` to close

> Hotkeys can be reassigned in NVDA Preferences → Input Gestures → **Dictionary & Translation**.

**Result window (for low-vision users):**

| Action | Function |
|---|---|
| `Ctrl + mouse wheel`, `Ctrl + plus/minus`, or the zoom buttons | Enlarge / shrink the font |
| `Ctrl + 0` | Reset the font size |
| `Ctrl + T` or the "switch colors" button | Cycle color schemes: system default → white on black → yellow on black |

Font size, color scheme and window size (including maximized state) are remembered for the next lookup.

**Automatic update check:**
On NVDA startup, zhDict checks GitHub in the background for a newer release and only asks whether to download and install it if an update is actually available; otherwise it stays silent.

---

### Data Sources

| Source | Purpose |
|---|---|
| [moedict API](https://www.moedict.tw/) | Chinese dictionary (Ministry of Education licensed data) |
| [Wiktionary](https://en.wiktionary.org/) | English dictionary: definitions, examples, IPA, synonyms/antonyms, per-sense Chinese translations (switched from Free Dictionary API after it became persistently unreachable) |
| Google Translate (unofficial endpoint) | Translates English definitions to Chinese, Chinese equivalents by part of speech, sentence translation |

> **Note**: The Google Translate endpoint is unofficial and may stop working in the future.

---

### Known Limitations

- moeDict requires at least two characters for lookup (API limitation)
- Requires internet access; no offline mode
- Synonyms/antonyms are translated word by word, so their Chinese may be imprecise out of context

---

### License

MIT — see [LICENSE](LICENSE)
