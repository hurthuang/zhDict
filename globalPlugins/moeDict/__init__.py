# -*- coding: utf-8 -*-
# NVDA Addon: moeDict
# alt+NVDA+k        → 基本查詢（簡短）
# alt+shift+NVDA+k  → 豐富查詢（完整字典＋翻譯）

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
import wx

# ── API 設定 ──────────────────────────────────────────────
MOEDICT_API  = "https://www.moedict.tw/a/{}.json"
DICTAPI_URL  = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"
GTRANS_API   = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=auto&tl=zh-TW&dt=t&q={}"
)
TIMEOUT = 10

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

# ── 語言判斷 ──────────────────────────────────────────────
_RE_CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')

def _is_chinese(text):
    if not text:
        return False
    cjk = sum(1 for c in text if _RE_CJK.match(c))
    return (cjk / len(text)) > 0.3

# ── 取得選取文字 ──────────────────────────────────────────
def _get_selected_text():
    try:
        obj = api.getFocusObject()
        if obj:
            info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
            text = info.text.strip()
            if text:
                return text
    except Exception:
        pass
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

# ── Google 翻譯 ───────────────────────────────────────────
def _gtranslate(text):
    url = GTRANS_API.format(urllib.parse.quote(text, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    if not raw or not raw[0]:
        return text
    return "".join(seg[0] for seg in raw[0] if seg[0]).strip()

# ── 萌典解析（共用，rich 控制詳細程度）──────────────────
def _fetch_moedict(word, rich=False):
    url = MOEDICT_API.format(urllib.parse.quote(word, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
            # 基本模式只取第一條義項
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

# ── 英文字典解析 ──────────────────────────────────────────
def _fetch_english(word, rich=False):
    url = DICTAPI_URL.format(urllib.parse.quote(word.lower(), safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            translated = _gtranslate(word)
            return f"【{word}】\n譯文：{translated}\n（字典查無此詞）"
        raise

    lines = [f"【{word}】"]

    # 中文譯名（永遠都有）
    zh_word = _gtranslate(word)
    if zh_word and zh_word.lower() != word.lower():
        lines.append(f"中文：{zh_word}")

    if not rich:
        # 基本：只取第一個詞性的第一條定義
        entry = data[0]
        phonetics = entry.get("phonetics", [])
        for ph in phonetics:
            if ph.get("text", "").strip():
                lines.append(f"音標：{ph['text'].strip()}")
                break
        meanings = entry.get("meanings", [])
        if meanings:
            m = meanings[0]
            pos = m.get("partOfSpeech", "")
            if pos:
                lines.append(f"詞性：{pos}")
            defs = m.get("definitions", [])
            if defs:
                en_def = defs[0].get("definition", "")
                zh_def = _gtranslate(en_def)
                lines.append(f"釋義：{zh_def}")
    else:
        # 豐富：音標 + 所有詞性 + 最多 4 條定義（含例句、同反義）
        entry = data[0]
        phonetics = entry.get("phonetics", [])
        for ph in phonetics:
            if ph.get("text", "").strip():
                lines.append(f"音標：{ph['text'].strip()}")
                break

        for meaning in entry.get("meanings", []):
            pos = meaning.get("partOfSpeech", "")
            lines.append(f"\n【{pos}】")
            for i, d in enumerate(meaning.get("definitions", [])[:4], 1):
                en_def  = d.get("definition", "")
                zh_def  = _gtranslate(en_def) if en_def else ""
                example = d.get("example", "")
                lines.append(f"{i}. {zh_def}")
                if zh_def != en_def:
                    lines.append(f"   ({en_def})")
                if example:
                    zh_ex = _gtranslate(example)
                    lines.append(f"   例：{zh_ex}")
                    if zh_ex != example:
                        lines.append(f"      ({example})")
            synonyms = meaning.get("synonyms", [])[:5]
            if synonyms:
                lines.append(f"   同義：{', '.join(synonyms)}")
            antonyms = meaning.get("antonyms", [])[:5]
            if antonyms:
                lines.append(f"   反義：{', '.join(antonyms)}")

    return "\n".join(lines)

# ── 背景查詢 ──────────────────────────────────────────────
def _query_worker(word, rich):
    try:
        if _is_chinese(word):
            result = _fetch_moedict(word, rich=rich)
            title = f"國語字典：{word}"
        else:
            result = _fetch_english(word, rich=rich)
            title = f"英文字典：{word}"
    except urllib.error.URLError as e:
        result = f"網路連線失敗：{e.reason}"
        title = "查詢失敗"
    except Exception as e:
        result = f"發生錯誤：{e}"
        title = "查詢失敗"

    wx.CallAfter(ui.browseableMessage, result, title)

# ── GlobalPlugin ──────────────────────────────────────────
class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    scriptCategory = "國語字典與翻譯"

    def script_queryBasic(self, gesture):
        """基本查詢：中文查注音＋第一條釋義；英文查中文譯名＋音標＋第一條定義"""
        self._query(rich=False)

    def script_queryRich(self, gesture):
        """豐富查詢：中文查完整字典；英文查完整字典含例句、同反義詞"""
        self._query(rich=True)

    def _query(self, rich):
        word = _get_selected_text()
        if not word:
            ui.message("請先選取要查詢的文字，或 Ctrl+C 複製後再按熱鍵。")
            return
        if len(word) > 500:
            ui.message("選取的文字過長，請縮小範圍。")
            return
        ui.message(f"查詢：{word[:10]}{'…' if len(word) > 10 else ''}")
        threading.Thread(target=_query_worker, args=(word, rich), daemon=True).start()

    __gestures = {
        "kb:alt+NVDA+k":       "queryBasic",
        "kb:alt+shift+NVDA+k": "queryRich",
    }
