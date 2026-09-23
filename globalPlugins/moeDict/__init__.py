# -*- coding: utf-8 -*-
# NVDA Addon: moeDict
# alt+NVDA+k        → 基本查詢
# alt+shift+NVDA+k  → 豐富查詢

import globalPluginHandler
import ui
import api
import textInfos
import threading
import urllib.request
import urllib.parse
import urllib.error
import json
import re
import os
import tempfile
import html
import unicodedata
import wx
import gui
from scriptHandler import script
import addonHandler

addonHandler.initTranslation()

# ── API 設定 ──────────────────────────────────────────────
MOEDICT_API    = "https://www.moedict.tw/a/{}.json"
WIKTIONARY_API = "https://en.wiktionary.org/api/rest_v1/page/definition/{}"
DATAMUSE_URL   = "https://api.datamuse.com/sug?s={}&max=5"
GTRANS_API   = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=auto&tl=zh-TW&dt=t&q={}"
)
GITHUB_LATEST_API = "https://api.github.com/repos/hurthuang/zhDict/releases/latest"
TIMEOUT = 10
TRANSLATE_TIMEOUT = 5  # 翻譯每次呼叫的逾時要短，避免豐富查詢因單次翻譯卡住而整體拖很久

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.moedict.tw/",
}

# ── 自動換行 ──────────────────────────────────────────────
_BREAK_AFTER = set('\u3002\uff01\uff1f\uff1b\uff0c\u3001\u300d\u300f\uff09')

def _dw(text):
    """計算字串顯示寬度（全形=2，半形=1）"""
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)

def _wrap(text, max_width=76):
    """自動換行，保留縮排，支援中文"""
    result = []
    for line in text.splitlines():
        if _dw(line) <= max_width:
            result.append(line)
            continue
        stripped = line.lstrip()
        indent_str = line[:len(line) - len(stripped)]
        indent_w = _dw(indent_str)
        current, current_w = indent_str, indent_w
        for ch in stripped:
            ch_w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
            if current_w + ch_w > max_width:
                if ch == ' ':
                    result.append(current.rstrip())
                    current, current_w = indent_str, indent_w
                    continue
                result.append(current)
                current, current_w = indent_str, indent_w
            current += ch
            current_w += ch_w
            if ch in _BREAK_AFTER and current_w >= max_width - 4:
                result.append(current)
                current, current_w = indent_str, indent_w
        if current.strip():
            result.append(current)
    return "\n".join(result)

# ── 語言判斷 ──────────────────────────────────────────────
_RE_CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')

def _is_chinese(text):
    if not text:
        return False
    cjk = sum(1 for c in text if _RE_CJK.match(c))
    return (cjk / len(text)) > 0.3

# ── 取得選取文字 ──────────────────────────────────────────
def _get_selected_text():
    # 方法一：一般文字控制項的系統選取
    try:
        obj = api.getFocusObject()
        if obj:
            info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
            text = info.text.strip()
            if text:
                return text
    except Exception:
        pass

    # 方法二：NVDA 瀏覽模式的虛擬游標選取
    try:
        import browseMode
        browseController = browseMode.BrowseModeDocumentTreeInterceptor
        obj = api.getFocusObject()
        if hasattr(obj, "treeInterceptor") and obj.treeInterceptor:
            ti = obj.treeInterceptor
            if hasattr(ti, "selection"):
                info = ti.selection
                text = info.text.strip()
                if text:
                    return text
    except Exception:
        pass

    # 方法三：剪貼簿（使用者先 Ctrl+C）
    try:
        text = api.getClipData()
        if text and text.strip():
            return text.strip()
    except Exception:
        pass
    return ""

# ── 萌典文字清理 ──────────────────────────────────────────
_PINYIN_CHARS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜńňǹ'
    '\u02ca\u02c7\u02cb\u02d9'
)
_RE_POS_PREFIX = re.compile(r'^\uff08?[\u4e00-\u9fff]{1,4}\uff09\s*')

def _strip_pinyin(text):
    return ''.join(c for c in text if c not in _PINYIN_CHARS).strip()

def _clean(text):
    text = text.replace('`', '').replace('\uff40', '')
    text = text.replace('~', '')
    text = _RE_POS_PREFIX.sub('', text)
    return text.strip()

def _clean_type(text):
    return text.replace('`', '').replace('\uff40', '').replace('~', '').strip()

# ── Wiktionary 文字清理 ────────────────────────────────────
_RE_HTML_TAG = re.compile(r'<[^>]+>')

def _strip_html(text):
    """Wiktionary 釋義/例句是帶 HTML 標籤的字串，先解 entity 再去標籤。"""
    return _RE_HTML_TAG.sub('', html.unescape(text)).strip()

def _is_stub_definition(text):
    """Wiktionary 詞條有時只有「本術語需要定義」之類的維護用佔位文字，不是真的釋義。"""
    return not text or "needs a definition" in text.lower()

def _first_real_definition(entry):
    """回傳這個詞性條目裡第一個非空、非佔位文字的釋義，找不到回傳 None。"""
    for d in entry.get("definitions", []):
        text = _strip_html(d.get("definition", ""))
        if not _is_stub_definition(text):
            return text
    return None

# ── Google 翻譯 ───────────────────────────────────────────
def _gtranslate(text):
    """翻譯失敗（逾時、連線錯誤等）時不中斷查詢，直接回傳原文。"""
    url = GTRANS_API.format(urllib.parse.quote(text, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return text
    if not raw or not raw[0]:
        return text
    return "".join(seg[0] for seg in raw[0] if seg[0]).strip()

# ── 拼字建議 ──────────────────────────────────────────────
def _spell_suggest(word):
    """用 Datamuse API 取得拼字建議，回傳 [(正確拼法, 中文譯名), ...]"""
    url = DATAMUSE_URL.format(urllib.parse.quote(word.lower(), safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    suggestions = []
    for item in data[:5]:
        w = item.get("word", "")
        if not w or w.lower() == word.lower():
            continue
        zh = _gtranslate(w)
        zh_label = f"（{zh}）" if zh and zh.lower() != w.lower() else ""
        suggestions.append(f"{w}{zh_label}")
    return suggestions


# ── 萌典中文查詢 ──────────────────────────────────────────
def _fetch_moedict(word, rich=False):
    url = MOEDICT_API.format(urllib.parse.quote(word, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        resp_cm = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"「{word}」查無此詞。"
        raise
    with resp_cm as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))

    entries = data if isinstance(data, list) else [data]
    lines = [f"【{word}】"]
    seen_defs = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for het in entry.get("h", []):
            if not isinstance(het, dict):
                continue
            bopomofo = _strip_pinyin(het.get("p", ""))
            het_lines = []
            if bopomofo:
                het_lines.append(f"注音：{bopomofo}")

            defs = het.get("d", [])
            if not rich:
                defs = defs[:1]

            for d_idx, d in enumerate(defs, 1):
                if not isinstance(d, dict):
                    continue
                pos = _clean_type(d.get("type", ""))
                f   = _clean(d.get("f", ""))
                pos_label = f"（{pos}）" if pos else ""
                het_lines.append(f"{d_idx}. {pos_label}{f}")

                if rich:
                    q_val = d.get("q")
                    if isinstance(q_val, list):
                        for q in q_val:
                            s = q if isinstance(q, str) else (q.get("f", "") if isinstance(q, dict) else "")
                            if s:
                                het_lines.append(f"  如：{_clean(s)}")
                    elif isinstance(q_val, str) and q_val:
                        het_lines.append(f"  如：{_clean(q_val)}")

                    e_val = d.get("e")
                    if isinstance(e_val, list):
                        for e in e_val:
                            s = e if isinstance(e, str) else (e.get("f", "") if isinstance(e, dict) else "")
                            if s:
                                het_lines.append(f"  引：{_clean(s)}")
                    elif isinstance(e_val, str) and e_val:
                        het_lines.append(f"  引：{_clean(e_val)}")

                    l = d.get("l", "")
                    if isinstance(l, str) and l.strip():
                        het_lines.append(f"  似：{_clean(l)}")

            key = tuple(het_lines)
            if key in seen_defs:
                continue
            seen_defs.add(key)
            lines.extend(het_lines)
            lines.append("")

    result = "\n".join(lines).strip()
    return result if len(result) > len(f"【{word}】") else f"「{word}」查無結果。"

# ── 英文字典查詢（Wiktionary，Free Dictionary API 長期無法連線後改用）──
def _fetch_english(word, rich=False):
    # Wiktionary 頁面大小寫敏感（UI ≠ ui、NASA ≠ nasa），先試原本大小寫，
    # 查無此詞再退回全小寫（句首被選取而大寫的一般單字，例如 Hello，得靠這步才查得到）。
    candidates = [word] if word.lower() == word else [word, word.lower()]
    data = None
    for candidate in candidates:
        url = WIKTIONARY_API.format(urllib.parse.quote(candidate, safe=""))
        req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            if e.code >= 500:
                return f"英文字典服務目前無法連線（伺服器錯誤 {e.code}），並非網路問題，請稍後再試。"
            raise

    if data is None:
        suggestions = _spell_suggest(word)
        if suggestions:
            lines = [f"「{word}」查無此詞，您是否要查："]
            for s in suggestions:
                lines.append(f"  • {s}")
            return "\n".join(lines)
        return f"「{word}」查無此詞，請確認拼字。"

    entries = data.get("en", [])
    if not entries:
        return f"「{word}」查無英文詞條，請確認拼字。"

    lines = [f"【{word}】"]
    zh_word = _gtranslate(word)
    if zh_word and zh_word.lower() != word.lower():
        lines.append(f"中文：{zh_word}")

    if not rich:
        # Symbol／Letter 條目常是 ISO 代碼、字母名稱之類的冷知識；有些條目只有
        # 「本術語需要定義」的佔位文字。優先找一個詞性正常、且有實質釋義的條目。
        candidates = [e for e in entries if e.get("partOfSpeech") not in ("Symbol", "Letter")] or entries
        entry, en_def = None, None
        for e in candidates:
            d = _first_real_definition(e)
            if d:
                entry, en_def = e, d
                break
        if entry is None:
            for e in entries:
                d = _first_real_definition(e)
                if d:
                    entry, en_def = e, d
                    break
        if entry is None:
            return f"「{word}」查無可用釋義。"
        pos = entry.get("partOfSpeech", "")
        if pos:
            lines.append(f"詞性：{pos}")
        zh_def = _gtranslate(en_def)
        lines.append(f"釋義：{zh_def}")
    else:
        for entry in entries:
            pos = entry.get("partOfSpeech", "")
            seen_defs = set()
            shown = 0
            section_lines = []
            for d in entry.get("definitions", []):
                if shown >= 4:
                    break
                en_def = _strip_html(d.get("definition", ""))
                # Wiktionary 的巢狀子義項常被拆成重複或空白的條目，佔位文字也跳過
                if _is_stub_definition(en_def) or en_def in seen_defs:
                    continue
                seen_defs.add(en_def)
                shown += 1
                zh_def = _gtranslate(en_def)
                section_lines.append(f"{shown}. {zh_def}")
                if zh_def != en_def:
                    section_lines.append(f"   ({en_def})")
                for ex in d.get("examples", [])[:2]:
                    ex_clean = _strip_html(ex)
                    if not ex_clean:
                        continue
                    zh_ex = _gtranslate(ex_clean)
                    section_lines.append(f"   例：{zh_ex}")
                    if zh_ex != ex_clean:
                        section_lines.append(f"      ({ex_clean})")
            if section_lines:
                lines.append(f"\n【{pos}】")
                lines.extend(section_lines)

    return "\n".join(lines)

# ── 檢查更新 ──────────────────────────────────────────────
def _parse_version(v):
    nums = [int(p) for p in re.findall(r'\d+', v)]
    nums += [0] * (4 - len(nums))
    return tuple(nums[:4])

def _current_version():
    try:
        return addonHandler.getCodeAddon().manifest.get("version", "0")
    except Exception:
        return "0"

def _check_update_worker(silent=False):
    """silent=True 用於開機自動檢查：沒有新版本時完全不提示，避免每次啟動都念一次。"""
    current = _current_version()
    req = urllib.request.Request(
        GITHUB_LATEST_API,
        headers={**_BROWSER_HEADERS, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if not silent:
            wx.CallAfter(ui.message, f"檢查更新失敗：{e}")
        return

    latest = data.get("tag_name", "").lstrip("vV")
    if _parse_version(latest) <= _parse_version(current):
        if not silent:
            wx.CallAfter(ui.message, f"目前已是最新版本（v{current}）。")
        return

    asset_url = None
    for asset in data.get("assets", []):
        if asset.get("name", "").endswith(".nvda-addon"):
            asset_url = asset.get("browser_download_url")
            break
    release_url = data.get("html_url", "https://github.com/hurthuang/zhDict/releases")
    wx.CallAfter(_prompt_update, latest, current, asset_url, release_url)

def _prompt_update(latest, current, asset_url, release_url):
    """在主執行緒彈出確認對話框；使用者按是才下載並開啟安裝。"""
    if not asset_url:
        ui.browseableMessage(
            f"有新版本可更新：v{latest}（目前使用：v{current}）\n\n下載頁面：\n{release_url}",
            "zhDict 有新版本",
        )
        return
    result = gui.messageBox(
        f"發現新版本 v{latest}（目前使用：v{current}）。\n\n是否立即下載並安裝？",
        "zhDict 有新版本",
        wx.YES_NO | wx.ICON_QUESTION,
    )
    if result == wx.YES:
        ui.message("正在下載更新…")
        threading.Thread(target=_download_and_install_worker, args=(asset_url,), daemon=True).start()

def _download_and_install_worker(asset_url):
    req = urllib.request.Request(asset_url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
    except Exception as e:
        wx.CallAfter(ui.message, f"下載更新失敗：{e}")
        return

    tmp_path = os.path.join(tempfile.gettempdir(), "zhDict-update.nvda-addon")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
    except Exception as e:
        wx.CallAfter(ui.message, f"儲存更新檔失敗：{e}")
        return

    # 交給系統開啟，觸發 NVDA 原生的附加元件安裝確認流程
    wx.CallAfter(os.startfile, tmp_path)

# ── 背景查詢 ──────────────────────────────────────────────
def _query_worker(word, rich):
    is_zh = _is_chinese(word)
    source = "國語字典" if is_zh else "英文字典"
    try:
        if is_zh:
            result = _fetch_moedict(word, rich=rich)
            title = f"國語字典：{word}"
        else:
            result = _fetch_english(word, rich=rich)
            title = f"英文字典：{word}"
    except urllib.error.URLError as e:
        result = f"網路連線失敗：{e.reason}"
        title = "查詢失敗"
    except TimeoutError:
        result = f"{source}服務逾時，可能是服務端忙線或故障（並非你的網路問題），請稍後再試。"
        title = "查詢逾時"
    except Exception as e:
        result = f"發生錯誤：{e}"
        title = "查詢失敗"

    wx.CallAfter(ui.browseableMessage, _wrap(result), title)

# ── GlobalPlugin ──────────────────────────────────────────
class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    scriptCategory = "國語字典與翻譯"

    def __init__(self):
        super().__init__()
        # 啟動時背景自動檢查一次更新，延遲幾秒避免搶在 NVDA 啟動流程前面；有新版才提示，沒有則靜默
        wx.CallLater(5000, lambda: threading.Thread(
            target=_check_update_worker, kwargs={"silent": True}, daemon=True
        ).start())

    @script(
        description="基本查詢：中文查注音＋第一條釋義；英文查譯名＋音標＋第一條定義",
        category="國語字典與翻譯",
        gesture="kb:alt+NVDA+k",
    )
    def script_queryBasic(self, gesture):
        """基本查詢：中文查注音＋第一條釋義；英文查譯名＋音標＋第一條定義"""
        self._query(rich=False)

    @script(
        description="豐富查詢：中文查完整字典；英文查完整字典含例句、同反義詞",
        category="國語字典與翻譯",
        gesture="kb:alt+shift+NVDA+k",
    )
    def script_queryRich(self, gesture):
        """豐富查詢：中文查完整字典；英文查完整字典含例句、同反義詞"""
        self._query(rich=True)

    def _query(self, rich):
        word = _get_selected_text()
        if not word:
            # 自動發送 Ctrl+C，等剪貼簿更新後重試
            self._query_with_copy(rich)
            return
        self._start_query(word, rich)

    def _query_with_copy(self, rich):
        """送出 Ctrl+C，等 300ms 後再讀剪貼簿"""
        import keyboardHandler
        # 記錄舊剪貼簿內容，避免誤用上一次的複製
        try:
            old_clip = api.getClipData()
        except Exception:
            old_clip = ""
        # 模擬 Ctrl+C
        try:
            import winUser
            winUser.keybd_event(0x11, 0, 0, 0)   # Ctrl down
            winUser.keybd_event(0x43, 0, 0, 0)   # C down
            winUser.keybd_event(0x43, 0, 2, 0)   # C up
            winUser.keybd_event(0x11, 0, 2, 0)   # Ctrl up
        except Exception:
            ui.message("請先選取要查詢的文字。")
            return
        # 等 350ms 後讀剪貼簿
        wx.CallLater(350, self._after_copy, rich, old_clip)

    def _after_copy(self, rich, old_clip):
        try:
            word = api.getClipData()
        except Exception:
            word = ""
        word = (word or "").strip()
        if not word or word == old_clip:
            ui.message("請先選取要查詢的文字。")
            return
        self._start_query(word, rich)

    def _start_query(self, word, rich):
        if len(word) > 500:
            ui.message("選取的文字過長，請縮小範圍。")
            return
        ui.message(f"查詢：{word[:10]}{'…' if len(word) > 10 else ''}")
        threading.Thread(target=_query_worker, args=(word, rich), daemon=True).start()
