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
from concurrent.futures import ThreadPoolExecutor
import wx
import gui
import globalVars
from scriptHandler import script
import addonHandler

addonHandler.initTranslation()

# ── API 設定 ──────────────────────────────────────────────
MOEDICT_API    = "https://www.moedict.tw/a/{}.json"
WIKTIONARY_API = "https://en.wiktionary.org/api/rest_v1/page/definition/{}"
WIKTIONARY_RAW = "https://en.wiktionary.org/w/index.php?title={}&action=raw"
DATAMUSE_URL   = "https://api.datamuse.com/sug?s={}&max=5"
GTRANS_API   = (
    "https://translate.googleapis.com/translate_a/single"
    "?client=gtx&sl=auto&tl={}&dt=t&q={}"
)
TRANSLATE_BATCH_CHARS = 1500  # 批次翻譯每次請求的原文長度上限，網址太長會被拒
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

# ── 結果視窗 ──────────────────────────────────────────────
# 不用 ui.browseableMessage：它的視窗無法縮放字體，也無法記住大小，低視力者看不清楚。
# 改用自己的唯讀文字框，Ctrl+滾輪／Ctrl+加減號縮放，大小存在設定檔，換行交給文字框依視窗寬度處理。
_SETTINGS_FILE = os.path.join(globalVars.appArgs.configPath, "zhDict.json")
_FONT_DEFAULT, _FONT_MIN, _FONT_MAX, _FONT_STEP = 12, 8, 72, 2
_FONT_FACE = "Microsoft JhengHei"
# 配色：(名稱, 文字色, 背景色)；None 表示用系統顏色，Windows 高對比主題也會套用
_THEMES = [
    ("系統預設", None, None),
    ("黑底白字", (255, 255, 255), (0, 0, 0)),
    ("黑底黃字", (255, 255, 0), (0, 0, 0)),
]

def _load_settings():
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_settings(settings):
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f)
    except Exception:
        pass

def _font_size():
    size = _load_settings().get("fontSize", _FONT_DEFAULT)
    return size if isinstance(size, int) and _FONT_MIN <= size <= _FONT_MAX else _FONT_DEFAULT

class ResultDialog(wx.Dialog):

    def __init__(self, parent, title, message):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.text = wx.TextCtrl(self, value=message, style=wx.TE_MULTILINE | wx.TE_READONLY)
        # 縮放與配色都有快捷鍵，按鈕是給用滑鼠的低視力使用者看得到、點得到
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            ("放大字體(&I)", lambda evt: self._zoom(_FONT_STEP)),
            ("縮小字體(&O)", lambda evt: self._zoom(-_FONT_STEP)),
            ("切換配色(&T)", lambda evt: self._cycleTheme()),
        ):
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.RIGHT, 8)
        buttons.AddStretchSpacer()
        closeButton = wx.Button(self, wx.ID_CLOSE, "關閉(&C)")
        closeButton.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
        buttons.Add(closeButton)
        self.SetEscapeId(wx.ID_CLOSE)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(sizer)
        settings = _load_settings()
        theme = settings.get("theme", 0)
        self.theme = theme if isinstance(theme, int) and 0 <= theme < len(_THEMES) else 0
        self._applyTheme()
        size = settings.get("windowSize")
        if isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v >= 200 for v in size):
            self.SetSize(wx.Size(*size))
        else:
            self.SetSize(self.FromDIP(wx.Size(720, 520)))
        self.CentreOnScreen()
        if settings.get("windowMaximized") is True:
            self.Maximize()

        self.fontSize = _font_size()
        self._applyFont()
        self.text.Bind(wx.EVT_MOUSEWHEEL, self.onMouseWheel)
        self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.text.SetInsertionPoint(0)
        self.text.SetFocus()

    def onClose(self, evt):
        # 最大化時只記住「最大化」，保留先前的一般大小，取消最大化後才不會變成整個螢幕大
        settings = _load_settings()
        settings["windowMaximized"] = self.IsMaximized()
        if not self.IsMaximized() and not self.IsIconized():
            settings["windowSize"] = list(self.GetSize())
        _save_settings(settings)
        self.Destroy()

    def _applyFont(self):
        font = self.text.GetFont()
        font.SetPointSize(self.fontSize)
        if wx.FontEnumerator.IsValidFacename(_FONT_FACE):
            font.SetFaceName(_FONT_FACE)
        self.text.SetFont(font)

    def _applyTheme(self):
        _, fg, bg = _THEMES[self.theme]
        self.text.SetForegroundColour(wx.Colour(*fg) if fg else wx.NullColour)
        self.text.SetBackgroundColour(wx.Colour(*bg) if bg else wx.NullColour)
        self.text.Refresh()

    def _cycleTheme(self):
        self.theme = (self.theme + 1) % len(_THEMES)
        self._applyTheme()
        settings = _load_settings()
        settings["theme"] = self.theme
        _save_settings(settings)
        ui.message(f"配色：{_THEMES[self.theme][0]}")

    def _zoom(self, delta):
        """delta 為 0 表示還原預設大小。"""
        size = _FONT_DEFAULT if delta == 0 else self.fontSize + delta
        size = max(_FONT_MIN, min(_FONT_MAX, size))
        if size == self.fontSize:
            return
        self.fontSize = size
        self._applyFont()
        settings = _load_settings()
        settings["fontSize"] = size
        _save_settings(settings)
        ui.message(f"字體 {size}")

    def onMouseWheel(self, evt):
        if not evt.ControlDown():
            evt.Skip()
            return
        self._zoom(_FONT_STEP if evt.GetWheelRotation() > 0 else -_FONT_STEP)

    def onCharHook(self, evt):
        key = evt.GetKeyCode()
        if evt.ControlDown() and not evt.AltDown():
            if key in (ord("="), ord("+"), wx.WXK_NUMPAD_ADD):
                self._zoom(_FONT_STEP)
                return
            if key in (ord("-"), wx.WXK_NUMPAD_SUBTRACT):
                self._zoom(-_FONT_STEP)
                return
            if key in (ord("0"), wx.WXK_NUMPAD0):
                self._zoom(0)
                return
            if key == ord("T"):
                self._cycleTheme()
                return
        evt.Skip()

def _show_result(message, title):
    gui.mainFrame.prePopup()
    dlg = ResultDialog(gui.mainFrame, title, message)
    dlg.Show()
    gui.mainFrame.postPopup()
    dlg.Raise()

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
# 釋義偶爾夾帶模板樣式，例如 <style>.mw-parser-output .defdate{…}</style>，連內容一起去掉
_RE_HTML_BLOCK = re.compile(r'<(style|script)\b[^>]*>.*?</\1\s*>', re.IGNORECASE | re.DOTALL)
# 釋義後面的巢狀子義項清單：子義項本身會再以獨立釋義出現，留著會斷行又重複
_RE_SUBLIST = re.compile(r'<(ol|ul)\b.*', re.IGNORECASE | re.DOTALL)
# 「See Appendix:Possessive#English.」這類指向附錄的導覽句，不是釋義
_RE_SEE_APPENDIX = re.compile(r'\s*See\s+<a\b[^>]*href="[^"]*/Appendix:[^"]*"[^>]*>.*?</a>\s*\.?', re.IGNORECASE | re.DOTALL)
_RE_SPACES = re.compile(r'\s+')

def _strip_html(text):
    """Wiktionary 釋義/例句是帶 HTML 標籤的字串，先去掉樣式、子清單、附錄導覽句，再解 entity、去標籤。"""
    text = _RE_HTML_BLOCK.sub('', text)
    text = _RE_SUBLIST.sub('', text)
    text = _RE_SEE_APPENDIX.sub('', text)
    text = _RE_HTML_TAG.sub('', html.unescape(text))
    return _RE_SPACES.sub(' ', text).strip()

# ── Wiktionary 逐義項中文翻譯 ─────────────────────────────
# 定義 API 只有英文釋義；中文翻譯要從頁面原始碼的翻譯區塊解析：
# {{trans-top|英文義項說明}} … *: Mandarin: {{t+|cmn|會議|tr=huìyì}} … {{trans-bottom}}
_RE_ENGLISH_SECTION = re.compile(r'^==\s*English\s*==\s*$(.*?)(?=^==[^=].*==\s*$|\Z)', re.MULTILINE | re.DOTALL)
# 義項說明裡可能再嵌模板（{{trans-top|to score {{w|run}}}}），所以參數取到行尾最後一個 }}
# trans-top-see 是附「另見」連結的變體，第一個參數一樣是義項說明
_RE_TRANS_BLOCK = re.compile(r'\{\{trans-top(?:-see)?\|([^\n]*)\}\}[^\n]*\n(.*?)\{\{trans-bottom\}\}', re.DOTALL)
_RE_CMN_TERM = re.compile(r'\{\{(?:t|t\+|tt|tt\+|t-check|t\+check)\|cmn\|([^{}]+)\}\}')
_RE_WIKI_TEMPLATE = re.compile(r'\{\{([^{}]*)\}\}')
_RE_WIKI_LINK = re.compile(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]')

def _template_text(m):
    """把內嵌模板換成它最後一個非具名參數，例如 {{w|run}} → run、{{lb|en|computing}} → computing。"""
    args = [a for a in m.group(1).split('|')[1:] if '=' not in a]
    return args[-1] if args else ''

def _flatten_templates(text):
    prev = None
    while prev != text:  # 由內而外展開巢狀模板
        prev, text = text, _RE_WIKI_TEMPLATE.sub(_template_text, text)
    return text

# ── 簡轉繁 ────────────────────────────────────────────────
# Wiktionary 的中文詞大多是繁體，偶爾混入簡體。Windows 內建的轉換是逐字的（头发 → 頭發），
# 所以只轉「確定是簡體」的詞：轉成簡體不變、轉成繁體會變；已是繁體的詞一律不動。
_LCMAP_SIMPLIFIED_CHINESE = 0x02000000
_LCMAP_TRADITIONAL_CHINESE = 0x04000000

def _lcmap(text, flag):
    import ctypes
    f = ctypes.windll.kernel32.LCMapStringEx
    n = f("zh-TW", flag, text, len(text), None, 0, None, None, 0)
    if n <= 0:
        return text
    buf = ctypes.create_unicode_buffer(n)
    f("zh-TW", flag, text, len(text), buf, n, None, None, 0)
    return buf.value[:n]

def _to_traditional(term):
    try:
        trad = _lcmap(term, _LCMAP_TRADITIONAL_CHINESE)
        if trad != term and _lcmap(term, _LCMAP_SIMPLIFIED_CHINESE) == term:
            return trad
    except Exception:
        pass
    return term

def _wiki_raw(title):
    url = WIKTIONARY_RAW.format(urllib.parse.quote(title, safe="/"))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8")

def _clean_wikitext(text):
    text = _RE_WIKI_LINK.sub(r'\1', text)
    return _RE_SPACES.sub(' ', text).strip()

def _cmn_term(params):
    """{{t+|cmn|我|alt=我的|tr=wǒ de}} 的參數 → 要顯示的詞；有 alt= 時用 alt。"""
    parts = params.split('|')
    alt = next((p[4:] for p in parts if p.startswith('alt=')), "")
    term = alt or parts[0]
    term = _RE_WIKI_LINK.sub(r'\1', term).replace('[[', '').replace(']]', '').strip()
    # 偶有拉丁字母的網路用語（hello 的 ciallo），不含中文字的不列
    return _to_traditional(term) if _RE_CJK.search(term) else ""

_RE_IPA = re.compile(r'\{\{IPA\|en\|([^{}\n]*)\}\}')
_RE_ACCENT = re.compile(r'\{\{(?:a|accent)\|([^{}]*)\}\}')
_RE_LINE_ACCENT = re.compile(r'\|a=([^|{}]*)')
_RE_NYM = re.compile(r'\{\{(syn|synonyms|ant|antonyms)\|en\|([^{}\n]*)\}\}')
_RE_NYM_SECTION = re.compile(r'^=+\s*(Synonyms|Antonyms)\s*=+\s*$(.*?)(?=^=|\Z)', re.MULTILINE | re.DOTALL)
_RE_LINK_EN = re.compile(r'\{\{l\|en\|([^|{}]+)')
_RE_COL_EN = re.compile(r'\{\{col\d?\|en\|([^{}]*)\}\}')
_IPA_MAX, _NYM_MAX = 3, 10

def _ipa_label(accents):
    """口音標籤 → 顯示用的「英」「美」；英美通用或沒標示的不加標籤。
    口音清單常是混合的（RP,AU,NZ,South Africa），有英式或美式就算；
    完全不含英美口音（只有蘇格蘭、澳洲等）或已過時的讀音，回傳 None 表示不列。"""
    accents = {a.strip() for a in accents.replace('|', ',').split(',') if a.strip()}
    if not accents:
        return ""
    if accents & {"obsolete", "dated", "archaic"}:
        return None
    uk = bool(accents & {"RP", "UK", "British", "SSB"})
    us = bool(accents & {"GA", "US", "GenAm", "American"})
    if uk and us:
        return ""
    if uk or us:
        return "英" if uk else "美"
    return None

def _parse_ipa(text):
    """回傳 ["/ˈnɒl.ɪdʒ/（英）", "/ˈnɑ.lɪdʒ/（美）", ...]，最多 _IPA_MAX 個。"""
    result = []
    for line in text.splitlines():
        for params in _RE_IPA.findall(line):
            parts = params.split('|')
            named = dict(p.split('=', 1) for p in parts if '=' in p)
            # 口音可能標在 IPA 模板本身、同一行其他模板（{{enPR|hûrt|a=GenAm}}, {{IPA|en|/hɝt/}}），或 {{a|…}}
            accents = (named.get("a", "") or ",".join(_RE_LINE_ACCENT.findall(line))
                       or ",".join(_RE_ACCENT.findall(line)))
            label = _ipa_label(accents)
            # 英式、美式各留第一個就好（hurt 的英式另有 SSB 新式標音），沒標口音的不同讀音（read 的 /ɹɛd/）照列
            if label is None or (label and any(r.endswith(f"（{label}）") for r in result)):
                continue
            for p in parts:
                if '=' in p or not p.startswith('/'):
                    continue  # 只取音位標音 /…/，不取語音細節 […]
                item = f"{p}（{label}）" if label else p
                if p not in [r.split('（')[0] for r in result]:
                    result.append(item)
    return result[:_IPA_MAX]

def _nym_word(param):
    """syn/ant 模板參數 → 單字：去掉 Thesaurus: 前綴與 <q:…> 之類的行內修飾。"""
    param = re.sub(r'<[^>]*>', '', param).strip()
    return param[len("Thesaurus:"):] if param.startswith("Thesaurus:") else param

def _parse_nyms(text):
    """回傳 (同義詞列表, 反義詞列表)，來源是義項下的 {{syn|en|…}}／{{ant|en|…}} 與 Synonyms／Antonyms 小節。"""
    syn, ant = [], []
    def add(target, word):
        word = _clean_wikitext(word)
        if word and word not in target and len(target) < _NYM_MAX:
            target.append(word)
    for kind, params in _RE_NYM.findall(text):
        target = syn if kind.startswith("syn") else ant
        for p in params.split('|'):
            if '=' not in p:
                add(target, _nym_word(p))
    for kind, body in _RE_NYM_SECTION.findall(text):
        target = syn if kind == "Synonyms" else ant
        for w in _RE_LINK_EN.findall(body):
            add(target, _nym_word(w))
        for params in _RE_COL_EN.findall(body):
            for p in params.split('|'):
                if '=' not in p:
                    add(target, _nym_word(p))
    return syn, ant

def _wiktionary_page_info(title):
    """從 Wiktionary 頁面原始碼的英文段落取出：
    zh_senses 逐義項中文 [(英文義項說明, [中文詞, ...]), ...]、ipa 音標、syn 同義詞、ant 反義詞。
    任何連線或解析失敗都回傳空結果，不影響查詢本身。"""
    info = {"zh_senses": [], "ipa": [], "syn": [], "ant": []}
    try:
        m = _RE_ENGLISH_SECTION.search(_wiki_raw(title))
        if not m:
            return info
        text = m.group(1)
        info["ipa"] = _parse_ipa(text)
        info["syn"], info["ant"] = _parse_nyms(text)
        # 常用大字（例如 run）的翻譯放在「單字/translations」子頁面
        if "{{see translation subpage" in text:
            text += _wiki_raw(f"{title}/translations")
    except Exception:
        return info
    info["zh_senses"] = _parse_zh_senses(text)
    return info

_RE_POS_HEADING = re.compile(r'^={3,5}\s*([A-Za-z ]+?)\s*={3,5}\s*$', re.MULTILINE)

def _parse_zh_senses(text):
    """回傳 [(詞性, 英文義項說明, [中文詞, ...]), ...]，只取有中文（Mandarin）翻譯的義項。
    詞性是翻譯區塊前面最近的詞性標題（===Verb===），轉成中文；認不得的是空字串。"""
    headings = [(m.start(), m.group(1).lower()) for m in _RE_POS_HEADING.finditer(text)
                if m.group(1).lower() in _GDICT_POS]
    senses = []
    for block in _RE_TRANS_BLOCK.finditer(text):
        params, body = block.groups()
        pos = next((p for start, p in reversed(headings) if start < block.start()), "")
        mandarin = [line for line in body.splitlines() if "Mandarin:" in line]
        terms = []
        for line in mandarin:
            for term in map(_cmn_term, _RE_CMN_TERM.findall(line)):
                if term and term not in terms:
                    terms.append(term)
        if not terms:
            continue
        # trans-top 可能帶 id= 之類的具名參數，義項說明是不含 = 的那個參數
        gloss = next((p for p in _flatten_templates(params).split('|') if '=' not in p), "")
        senses.append((_GDICT_POS.get(pos, ""), _clean_wikitext(gloss), terms))
    return senses

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
def _gtranslate(text, tl="zh-TW"):
    """翻譯失敗（逾時、連線錯誤等）時不中斷查詢，直接回傳原文。"""
    url = GTRANS_API.format(tl, urllib.parse.quote(text, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return text
    if not raw or not raw[0]:
        return text
    return "".join(seg[0] for seg in raw[0] if seg[0]).strip()

def _gtranslate_many(texts):
    """一次翻譯多段文字，回傳 {原文: 譯文}。
    以換行串成幾個批次（每批不超過 TRANSLATE_BATCH_CHARS），各批同時送出；
    一批翻回來的行數對不上時，那一批改成逐句翻譯。翻譯失敗的句子對應到原文。"""
    texts = list(dict.fromkeys(t for t in texts if t and "\n" not in t))
    batches, batch, size = [], [], 0
    for t in texts:
        if batch and size + len(t) > TRANSLATE_BATCH_CHARS:
            batches.append(batch)
            batch, size = [], 0
        batch.append(t)
        size += len(t) + 1
    if batch:
        batches.append(batch)

    def translate_batch(batch):
        out = _gtranslate("\n".join(batch)).split("\n")
        if len(out) != len(batch):
            out = [_gtranslate(t) for t in batch]
        return [o.strip() or t for o, t in zip(out, batch)]

    result = {}
    if batches:
        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            for batch, out in zip(batches, pool.map(translate_batch, batches)):
                result.update(zip(batch, out))
    return result

_GDICT_POS = {
    "noun": "名詞", "verb": "動詞", "adjective": "形容詞", "adverb": "副詞",
    "pronoun": "代名詞", "preposition": "介系詞", "conjunction": "連接詞",
    "interjection": "感嘆詞", "article": "冠詞", "abbreviation": "縮寫",
    "prefix": "字首", "suffix": "字尾", "phrase": "片語",
    "auxiliary verb": "助動詞", "particle": "語助詞", "proper noun": "專有名詞",
    "determiner": "限定詞", "numeral": "數詞",
}

def _is_common_word(word):
    """Google 字典資料常混入古漢語罕用字（hurt 的「憖」、fast 的「翛」）或錯誤詞（「暾害」），
    一般人看不懂。只保留每個字都在 Big5 常用字範圍（0xA440–0xC67E）內的詞。"""
    for ch in word:
        try:
            b = ch.encode("big5")
        except UnicodeEncodeError:
            return False
        if len(b) == 2 and not 0xA440 <= int.from_bytes(b, "big") <= 0xC67E:
            return False
    return True

def _gdict(word):
    """Google 翻譯的字典模式：回傳 (主要譯名, [(中文詞性, [對應中文詞, ...]), ...])。
    片語、句子或連線失敗時沒有字典資料，詞性列表為空；連線失敗時主要譯名為原文。"""
    url = GTRANS_API.format("zh-TW", urllib.parse.quote(word, safe="")) + "&dt=bd"
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return word, []
    main = "".join(seg[0] for seg in (raw[0] or []) if seg[0]).strip() or word
    groups = []
    try:
        for pos_entry in raw[1] or []:
            # 單字多半是古文用字或詞的片段（present 的「斯、儀、今」），不列；常用的單字 Wiktionary 會給。
            # 偶有簡體混入（瞄准），轉成繁體；「你好!」這種帶標點的去掉標點
            words = (_to_traditional(w).strip("!?！？。") for w in pos_entry[1] if w)
            words = list(dict.fromkeys(w for w in words if len(w) > 1 and _is_common_word(w)))
            if words:
                groups.append((_GDICT_POS.get(pos_entry[0], pos_entry[0]), words))
    except (IndexError, TypeError):
        pass
    return main, groups

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
    words = [item.get("word", "") for item in data[:5]]
    words = [w for w in words if w and w.lower() != word.lower()]
    zh = _gtranslate_many(words)
    suggestions = []
    for w in words:
        zh_w = zh.get(w, w)
        zh_label = f"（{zh_w}）" if zh_w.lower() != w.lower() else ""
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
            # 萌典沒收的新詞、專有名詞（例如人工智慧），至少給個英文翻譯
            en = _gtranslate(word, tl="en") if len(word) > 1 else word
            return f"「{word}」查無此詞。" + (f"\n英文翻譯：{en}" if en != word else "")
        raise
    with resp_cm as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))

    entries = data if isinstance(data, list) else [data]
    lines = [word]
    seen_defs = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for het in entry.get("h", []):
            if not isinstance(het, dict):
                continue
            # 萌典的注音在 b，p 是漢語拼音
            bopomofo = _clean_type(het.get("b", "")) or _strip_pinyin(het.get("p", ""))
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
                    # 萌典的 e 是例句，本身已帶「如：」開頭；q 是古籍引文。順序照萌典網站：先例句後引文
                    for key, label in (("e", ""), ("q", "引：")):
                        val = d.get(key)
                        items = val if isinstance(val, list) else [val] if isinstance(val, str) else []
                        for item in items:
                            s = item if isinstance(item, str) else (item.get("f", "") if isinstance(item, dict) else "")
                            if s:
                                het_lines.append(f"  {label}{_clean(s)}")

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
    return result if len(result) > len(word) else f"「{word}」查無結果。"

# ── 英文字典查詢（Wiktionary，Free Dictionary API 長期無法連線後改用）──
def _wiktionary_entries(word):
    """回傳 Wiktionary 的英文詞條列表；頁面不存在回傳 None，其他 HTTP 錯誤照常拋出。"""
    url = WIKTIONARY_API.format(urllib.parse.quote(word, safe=""))
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return data.get("en", [])

def _only_proper_nouns(entries):
    return all(e.get("partOfSpeech") == "Proper noun" for e in entries)

def _zh_meaning_lines(word, zh_word, zh_groups, senses, tr):
    """單字的中文對應詞，盡量列完整：
    Wiktionary 有逐義項中文翻譯就列出「中文詞：義項說明」，Google 字典模式中沒出現過的再列在「其他譯法」；
    Wiktionary 沒有中文翻譯時，直接列 Google 字典模式依詞性分組的對應詞。"""
    lines = []
    if zh_word and zh_word.lower() != word.lower():
        lines.append(f"中文：{zh_word}")
    if senses:
        lines.append("各義項中文：")
        listed = set()
        for _pos, gloss, terms in senses:
            listed.update(terms)
            gloss = tr.get(gloss, gloss)
            # 用「：」不用括號：義項說明本身常以「（計算）」之類的領域標籤開頭
            lines.append(f"  {'、'.join(terms)}：{gloss}" if gloss else f"  {'、'.join(terms)}")
        others = [(pos, [w for w in words if w not in listed]) for pos, words in zh_groups]
        others = [(pos, words) for pos, words in others if words]
        if others:
            lines.append("其他譯法：")
            for pos_zh, words in others:
                lines.append(f"  {pos_zh}：{'、'.join(words)}")
    elif zh_groups:
        lines.append("各詞性中文：")
        for pos_zh, words in zh_groups:
            lines.append(f"  {pos_zh}：{'、'.join(words)}")
    return lines

_ZH_PER_POS, _ZH_PER_SENSE = 8, 2

def _zh_by_pos_lines(word, zh_word, zh_groups, senses):
    """基本查詢用：只回答「中文是什麼」，依詞性分組列出中文詞，不附義項說明。
    每個詞性先放 Wiktionary 逐義項的譯詞（照義項順序，品質較好），不足再用 Google 字典模式補，
    同一詞性內不重複，最多 _ZH_PER_POS 個。詞性順序照 Wiktionary 頁面，Google 才有的詞性接在後面。"""
    groups = {}
    for pos, _gloss, terms in senses:
        # 每個義項只取前 _ZH_PER_SENSE 個，免得一個冷門義項（run 的「衣物脫線」有四個譯詞）佔滿整行
        groups.setdefault(pos, []).extend(terms[:_ZH_PER_SENSE])
    for pos, words in zh_groups:
        groups.setdefault(pos, []).extend(words)
    lines = []
    for pos, words in groups.items():
        words = list(dict.fromkeys(w for w in words if _is_common_word(w)))[:_ZH_PER_POS]
        if words:
            lines.append(f"{pos}：{'、'.join(words)}" if pos else "、".join(words))
    # 主要譯詞通常已在詞性分組裡，不另列；沒有任何分組時（NASA → 美國太空總署）才單獨列出
    if not lines and zh_word and zh_word.lower() != word.lower():
        lines.append(zh_word)
    return lines

def _basic_definition(entries):
    """基本查詢用：回傳 (詞性, 英文釋義)，找不到回傳 (None, None)。
    Symbol／Letter 條目常是 ISO 代碼、字母名稱之類的冷知識；有些條目只有
    「本術語需要定義」的佔位文字。優先找一個詞性正常、且有實質釋義的條目。"""
    candidates = [e for e in entries if e.get("partOfSpeech") not in ("Symbol", "Letter")] or entries
    for group in (candidates, entries):
        for e in group:
            d = _first_real_definition(e)
            if d:
                return e.get("partOfSpeech", ""), d
    return None, None

def _rich_sections(entries):
    """豐富查詢用：回傳 [(詞性, [(英文釋義, [英文例句, ...]), ...]), ...]，每個詞性最多 4 條釋義、每條 2 個例句。"""
    sections = []
    for entry in entries:
        seen_defs = set()
        defs = []
        for d in entry.get("definitions", []):
            if len(defs) >= 4:
                break
            en_def = _strip_html(d.get("definition", ""))
            # Wiktionary 的巢狀子義項常被拆成重複或空白的條目，佔位文字也跳過
            if _is_stub_definition(en_def) or en_def in seen_defs:
                continue
            seen_defs.add(en_def)
            examples = [ex for ex in (_strip_html(x) for x in d.get("examples", [])[:2]) if ex]
            defs.append((en_def, examples))
        if defs:
            sections.append((entry.get("partOfSpeech", ""), defs))
    return sections

def _fetch_english(word, rich=False):
    # Wiktionary 頁面大小寫敏感（UI ≠ ui、NASA ≠ nasa），先試原本大小寫。
    # 句首被選取而大寫的一般單字要再查小寫：Hello 沒有自己的頁面；Session 則有，
    # 但只有姓氏、地名之類的專有名詞，一般詞義在 session 頁面。全大寫的縮寫不在此列。
    lower = word.lower()
    title = word  # 主要詞條所在的頁面，中文翻譯、音標、同反義詞也從這頁取
    try:
        entries = _wiktionary_entries(word)
        if lower != word and (not entries or (not word.isupper() and _only_proper_nouns(entries))):
            lower_entries = _wiktionary_entries(lower)
            if lower_entries:
                # 一般詞義排前面，原大小寫的專有名詞接在後面
                entries = lower_entries + (entries or [])
                title = lower
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            return f"英文字典服務目前無法連線（伺服器錯誤 {e.code}），並非網路問題，請稍後再試。"
        raise

    if entries is None:
        # 片語查不到時直接翻譯，拼字建議只對單一個字有意義
        if len(word.split()) > 1:
            return _translate_text(word)
        suggestions = _spell_suggest(word)
        if suggestions:
            lines = [f"「{word}」查無此詞，您是否要查："]
            for s in suggestions:
                lines.append(f"  • {s}")
            return "\n".join(lines)
        return f"「{word}」查無此詞，請確認拼字。"

    if not entries:
        return f"「{word}」查無英文詞條，請確認拼字。"

    # 提速：Google 字典模式和 Wiktionary 頁面原始碼同時抓；所有要翻譯的句子最後一次批次翻譯
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_gdict = pool.submit(_gdict, word)
        f_info = pool.submit(_wiktionary_page_info, title)
        zh_word, zh_groups = f_gdict.result()
        info = f_info.result()

    if not rich:
        # 基本查詢只回答「中文是什麼」：依詞性列中文詞。完全沒有中文對應詞時才退回翻譯第一條釋義
        zh_lines = _zh_by_pos_lines(word, zh_word, zh_groups, info["zh_senses"])
        if zh_lines:
            return "\n".join([word] + zh_lines)
        _pos, en_def = _basic_definition(entries)
        if en_def is None:
            return f"「{word}」查無可用釋義。"
        return f"{word}\n釋義：{_gtranslate(en_def)}"

    sections = _rich_sections(entries)
    syn, ant = info["syn"], info["ant"]
    to_translate = [en for _, defs in sections for en, exs in defs for en in [en] + exs]
    to_translate += syn + ant
    to_translate += [gloss for _, gloss, _ in info["zh_senses"]]
    tr = _gtranslate_many(to_translate)

    lines = [word]
    if info["ipa"]:
        lines.append(f"音標：{'、'.join(info['ipa'])}")
    lines.extend(_zh_meaning_lines(word, zh_word, zh_groups, info["zh_senses"], tr))

    def with_zh(words):
        out = []
        for w in words:
            zh = tr.get(w, w)
            out.append(f"{w}（{zh}）" if zh.lower() != w.lower() else w)
        return "、".join(out)
    if syn:
        lines.append(f"同義詞：{with_zh(syn)}")
    if ant:
        lines.append(f"反義詞：{with_zh(ant)}")

    for pos, defs in sections:
        lines.append(f"\n{pos}")
        for i, (en_def, examples) in enumerate(defs, 1):
            zh_def = tr.get(en_def, en_def)
            lines.append(f"{i}. {zh_def}")
            if zh_def != en_def:
                lines.append(f"   ({en_def})")
            for ex in examples:
                zh_ex = tr.get(ex, ex)
                lines.append(f"   例：{zh_ex}")
                if zh_ex != ex:
                    lines.append(f"      ({ex})")
    return "\n".join(lines)

# ── 整句翻譯 ──────────────────────────────────────────────
# 選取整句時查字典沒有意義，直接翻譯：英文等外文翻成中文，中文翻成英文。
_RE_SENTENCE_PUNCT = re.compile(r'[.!?;:,]\s|[.!?]$|[，。！？；：]')
_SENTENCE_WORDS = 4   # 外文超過這麼多個字視為句子；片語（take off、a piece of cake）仍查字典
_SENTENCE_CHARS = 12  # 中文超過這麼多個字視為句子；成語、俗語仍查萌典

def _is_sentence(text):
    if _is_chinese(text):
        return len(text) > _SENTENCE_CHARS or bool(_RE_SENTENCE_PUNCT.search(text))
    words = text.split()
    return len(words) > _SENTENCE_WORDS or (len(words) > 1 and bool(_RE_SENTENCE_PUNCT.search(text)))

def _translate_text(text):
    to_english = _is_chinese(text)
    translated = _gtranslate(text, tl="en" if to_english else "zh-TW")
    if translated == text:
        return "翻譯失敗，可能是翻譯服務暫時無法連線，請稍後再試。"
    return f"原文：{text}\n{'英文' if to_english else '中文'}：{translated}"

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
        if _is_sentence(word):
            source = "翻譯"
            result = _translate_text(word)
            title = f"翻譯：{word[:20]}{'…' if len(word) > 20 else ''}"
        elif is_zh:
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

    wx.CallAfter(_show_result, result, title)

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
        description="基本查詢：中文查注音＋第一條釋義；英文依詞性列出中文對應詞；整句直接翻譯",
        category="國語字典與翻譯",
        gesture="kb:alt+NVDA+k",
    )
    def script_queryBasic(self, gesture):
        """基本查詢：中文查注音＋第一條釋義；英文依詞性列出中文對應詞；整句直接翻譯"""
        self._query(rich=False)

    @script(
        description="豐富查詢：中文查完整字典；英文查完整字典含音標、例句、同反義詞；整句直接翻譯",
        category="國語字典與翻譯",
        gesture="kb:alt+shift+NVDA+k",
    )
    def script_queryRich(self, gesture):
        """豐富查詢：中文查完整字典；英文查完整字典含音標、例句、同反義詞；整句直接翻譯"""
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
