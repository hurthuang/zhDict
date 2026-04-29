# zhDict — NVDA 國語字典與英文翻譯查詢附加元件

[English](#english) | [中文](#中文)

---

## 中文

### 簡介

zhDict 是一個 [NVDA](https://www.nvaccess.org/) 螢幕閱讀器的附加元件，讓使用者可以選取文字後快速查詢字典或翻譯：

- **中文**：查詢[教育部重編國語辭典修訂本](https://dict.revised.moe.edu.tw/)（透過[萌典 API](https://www.moedict.tw/)），顯示注音、詞性、釋義、例句、似義詞等。
- **英文**：查詢 [Free Dictionary API](https://dictionaryapi.dev/)，提供音標、詞性、中文釋義、例句、同反義詞；並搭配 Google 翻譯將英文定義翻譯為中文。

語言自動判斷，無需手動切換。

---

### 系統需求

- NVDA 2023.1 或更新版本
- Windows 10 / 11
- 網路連線（查詢時需連線至萌典及 Google 翻譯）

---

### 安裝

1. 至 [Releases](https://github.com/hurt/zhDict/releases) 下載最新的 `.nvda-addon` 檔案
2. 直接雙擊該檔案，NVDA 會提示安裝
3. 重新啟動 NVDA 後即可使用

---

### 使用方式

| 熱鍵 | 功能 |
|---|---|
| `Alt + NVDA + K` | **基本查詢**：注音 + 第一條釋義（中文）；譯名 + 音標 + 第一條定義（英文） |
| `Alt + Shift + NVDA + K` | **豐富查詢**：完整字典內容，含所有義項、例句、引文、似義詞／同反義詞 |

**使用步驟：**
1. 在任何應用程式中選取要查詢的文字（或先 `Ctrl+C` 複製）
2. 按下熱鍵，NVDA 會說「查詢中，請稍候…」
3. 結果顯示於可瀏覽的對話框，可用方向鍵逐行閱讀，焦點離開自動關閉

> 熱鍵可在 NVDA 偏好設定 → 按鍵手勢 → **國語字典與翻譯** 中自訂。

---

### 資料來源

| 來源 | 用途 |
|---|---|
| [萌典 API](https://www.moedict.tw/) | 中文字典（教育部授權資料） |
| [Free Dictionary API](https://dictionaryapi.dev/) | 英文字典 |
| Google Translate（非官方端點） | 英文定義翻譯為中文 |

> **注意**：Google Translate 使用非官方免費端點，未來可能失效。

---

### 已知限制

- 萌典單字查詢需輸入至少兩個字；單一字元請選取後查詢（API 限制）
- 豐富查詢的英文因需多次呼叫翻譯 API，回應時間較長
- 離線時無法使用

---

## English

### Introduction

zhDict is an [NVDA](https://www.nvaccess.org/) screen reader add-on for quick dictionary lookup and translation:

- **Chinese text**: Queries the [Ministry of Education Revised Mandarin Chinese Dictionary](https://dict.revised.moe.edu.tw/) via the [moedict API](https://www.moedict.tw/), showing phonetics (Bopomofo), part of speech, definitions, examples, and synonyms.
- **English text**: Queries the [Free Dictionary API](https://dictionaryapi.dev/) for phonetics, definitions, and examples. Definitions are translated into Traditional Chinese via Google Translate.

Language is detected automatically — no manual switching needed.

---

### Requirements

- NVDA 2023.1 or later
- Windows 10 / 11
- Internet connection (required for dictionary and translation queries)

---

### Installation

1. Download the latest `.nvda-addon` file from [Releases](https://github.com/hurt/zhDict/releases)
2. Double-click the file; NVDA will prompt you to install it
3. Restart NVDA

---

### Usage

| Hotkey | Function |
|---|---|
| `Alt + NVDA + K` | **Basic lookup**: phonetics + first definition (Chinese); translation + phonetics + first definition (English) |
| `Alt + Shift + NVDA + K` | **Rich lookup**: full dictionary content with all senses, examples, quotations, and synonyms/antonyms |

**Steps:**
1. Select text in any application (or copy with `Ctrl+C`)
2. Press the hotkey — NVDA will say "Querying…"
3. Results appear in a browseable dialog; navigate with arrow keys; closes automatically when focus leaves

> Hotkeys can be reassigned in NVDA Preferences → Input Gestures → **Dictionary & Translation**.

---

### Data Sources

| Source | Purpose |
|---|---|
| [moedict API](https://www.moedict.tw/) | Chinese dictionary (Ministry of Education licensed data) |
| [Free Dictionary API](https://dictionaryapi.dev/) | English dictionary |
| Google Translate (unofficial endpoint) | Translates English definitions to Chinese |

> **Note**: The Google Translate endpoint is unofficial and may stop working in the future.


---

### License

MIT — see [LICENSE](LICENSE)
