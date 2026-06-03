import ctypes
import ctypes.wintypes as wt
import html
import json
import math
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import quote
from urllib.request import Request, urlopen

APP_TITLE = "即时英文翻译助手"
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_T = 0x54
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
HC_ACTION = 0
CF_UNICODETEXT = 13

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = wt.LPARAM
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.OpenClipboard.argtypes = [wt.HWND]
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ULONG_PTR]
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = wt.LPVOID
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]


def normalize_selected_text(text):
    return re.sub(r"\s+", " ", text or "").strip().strip("\u200b\ufeff")


def looks_like_english(text):
    clean = text.strip()
    if len(clean) < 2 or len(clean) > 4000:
        return False
    letters = re.findall(r"[A-Za-z]", clean)
    if not letters:
        return False
    return len(letters) >= 2 and sum(1 for ch in clean if ord(ch) < 128) / max(len(clean), 1) > 0.65


def translate_to_chinese(text):
    encoded = quote(text)
    urls = [
        ("Google Translate", "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=" + encoded),
        ("MyMemory", "https://api.mymemory.translated.net/get?q=" + encoded + "&langpair=en%7Czh-CN"),
    ]
    last_error = None
    for provider, url in urls:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            if provider == "Google Translate":
                translated = "".join(part[0] for part in data[0] if part and part[0])
            else:
                translated = data.get("responseData", {}).get("translatedText", "")
            translated = html.unescape(translated).strip()
            if translated:
                return translated, provider
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"在线翻译失败：{last_error}")


def clipboard_get_text():
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clipboard_set_text(text):
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        if text is None:
            return True
        data = text + "\0"
        size = len(data) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(0x0042, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        try:
            ctypes.memmove(ptr, ctypes.create_unicode_buffer(data), size)
        finally:
            kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        return True
    finally:
        user32.CloseClipboard()


def send_ctrl_c():
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(0x43, 0, 0, 0)
    user32.keybd_event(0x43, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def extract_selected_text(restore_clipboard=True):
    old_text = clipboard_get_text()
    marker = f"__translator_marker_{time.time_ns()}__"
    clipboard_set_text(marker)
    time.sleep(0.04)
    send_ctrl_c()
    time.sleep(0.22)
    new_text = clipboard_get_text()
    if restore_clipboard:
        clipboard_set_text(old_text)
    if not new_text or new_text == marker:
        return ""
    return normalize_selected_text(new_text)


IRREGULAR_PAST = {"was", "were", "went", "came", "saw", "made", "took", "gave", "got", "found", "thought", "knew", "became", "began", "felt", "left", "kept", "held", "brought", "bought", "told", "said", "met", "wrote", "read", "heard", "lost", "paid", "put", "ran", "sat", "stood", "understood"}
IRREGULAR_PARTICIPLES = {"been", "done", "gone", "seen", "made", "taken", "given", "gotten", "found", "known", "become", "begun", "felt", "left", "kept", "held", "brought", "bought", "told", "said", "met", "written", "read", "heard", "lost", "paid", "put", "run", "sat", "stood", "understood"}
MODAL_MEANINGS = {
    "can": "can 表示能力、许可或可能性。",
    "could": "could 常表示过去能力、委婉请求或较弱可能性。",
    "may": "may 表示许可或可能性。",
    "might": "might 表示较弱可能性。",
    "must": "must 表示必须，或对现在情况的强推测。",
    "should": "should 表示建议、义务或预期。",
    "would": "would 常表示意愿、假设、过去习惯或委婉表达。",
}
CONNECTOR_NOTES = {
    "because": "because 引出原因状语从句。",
    "although": "although 引出让步状语从句。",
    "though": "though 引出让步状语从句。",
    "if": "if 引出条件从句。",
    "when": "when 引出时间从句。",
    "while": "while 可引出时间或对比关系。",
    "who": "who 常引出修饰人的定语从句。",
    "which": "which 常引出修饰物或整句话的定语从句。",
    "that": "that 可引出宾语从句或定语从句。",
    "where": "where 常引出地点从句。",
    "why": "why 可引出原因疑问句，也可引出宾语从句中的原因说明。",
    "but": "but 表示转折。",
    "so": "so 表示结果或目的。",
}


def sentence_kind(text, words):
    stripped = text.strip()
    if stripped.endswith("?"):
        return "这是疑问句，阅读时先找助动词或疑问词，再回到主语和谓语。"
    if words and words[0] in {"what", "why", "how", "where", "when", "who", "whom", "whose"}:
        return "句首有疑问词，重点看它询问的是时间、原因、方式、地点还是对象。"
    if words and words[0] in {"do", "does", "did", "is", "are", "was", "were", "can", "could", "will", "would", "should", "may", "might", "must"}:
        return "句首像是助动词或情态动词，常见结构是“助动词 + 主语 + 动词”。"
    return "这是陈述句或陈述性片段，先抓主语和谓语，再看修饰成分。"


def find_tense_notes(words):
    joined = " " + " ".join(words) + " "
    notes = []
    has_participle = any(w.endswith("ed") or w in IRREGULAR_PARTICIPLES for w in words)
    if re.search(r"\b(have|has)\s+been\s+\w+ing\b", joined):
        notes.append("现在完成进行时：have/has been + V-ing，强调动作从过去持续到现在。")
    elif re.search(r"\b(have|has)\s+\w+(ed|en)\b", joined) or (("have" in words or "has" in words) and has_participle):
        notes.append("现在完成时：have/has + 过去分词，常表示过去动作对现在的影响。")
    if re.search(r"\bhad\s+been\s+\w+ing\b", joined):
        notes.append("过去完成进行时：had been + V-ing，强调过去某时间点之前一直在进行。")
    elif "had" in words and has_participle:
        notes.append("过去完成时：had + 过去分词，表示“过去的过去”。")
    if "will" in words or "shall" in words or re.search(r"\b(am|is|are|was|were)\s+going\s+to\b", joined):
        notes.append("将来表达：will/shall 或 be going to，表示预测、计划或临时决定。")
    if re.search(r"\b(am|is|are)\s+\w+ing\b", joined):
        notes.append("现在进行时：am/is/are + V-ing，表示正在发生或近期安排。")
    if re.search(r"\b(was|were)\s+\w+ing\b", joined):
        notes.append("过去进行时：was/were + V-ing，表示过去某时正在进行。")
    if "did" in words or any(w.endswith("ed") or w in IRREGULAR_PAST for w in words):
        notes.append("过去式/过去分词线索：-ed、did 或不规则形式可能表示过去动作，也可能作定语修饰名词。")
    be_words = {"is", "are", "am", "was", "were", "be", "been", "being"}
    if any(w in be_words and i + 1 < len(words) and (words[i + 1].endswith("ed") or words[i + 1] in IRREGULAR_PARTICIPLES) for i, w in enumerate(words)):
        notes.append("被动语态线索：be + 过去分词，重点通常在承受动作的人或物。")
    if not notes:
        notes.append("没有明显复杂时态标记，可能是一般现在时、祈使句或短语片段。")
    return notes


def analyze_grammar(text):
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text.lower())
    original_words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    if not words:
        return "没有检测到可分析的英文单词。"
    notes = ["句子类型：" + sentence_kind(text, words), "时态/语态："]
    notes.extend("  - " + item for item in find_tense_notes(words))
    modals = [w for w in words if w in MODAL_MEANINGS]
    if modals:
        notes.append("情态动词：")
        notes.extend("  - " + MODAL_MEANINGS[m] for m in dict.fromkeys(modals))
    connectors = [w for w in words if w in CONNECTOR_NOTES]
    if connectors:
        notes.append("从句/逻辑关系：")
        notes.extend("  - " + CONNECTOR_NOTES[c] for c in dict.fromkeys(connectors))
    joined = " " + " ".join(words) + " "
    phrase_notes = []
    if re.search(r"\bto\s+[a-z]+\b", joined):
        phrase_notes.append("to + 动词原形常是不定式，可表示目的、将要做的事或名词后的补充说明。")
    if any(w.endswith("ing") for w in words):
        phrase_notes.append("V-ing 可能是进行时、动名词或现在分词，需看它前面有没有 be 动词。")
    if any(w in {"a", "an", "the"} for w in words):
        phrase_notes.append("冠词 a/an/the 用来标记名词是否特指；the 通常表示说话双方都知道的对象。")
    if any(w in {"in", "on", "at", "for", "from", "with", "by", "about", "into", "through", "over", "under", "between"} for w in words):
        phrase_notes.append("介词短语通常补充时间、地点、方式、原因或对象，翻译时可后置再调整语序。")
    if any(w in {"more", "most", "better", "best", "less", "least", "worse", "worst"} for w in words) or "than" in words:
        phrase_notes.append("比较级/最高级线索：more/-er 表示“更……”，most/-est 表示“最……”。")
    if phrase_notes:
        notes.append("短语结构：")
        notes.extend("  - " + item for item in phrase_notes)
    content_words = []
    for word in original_words:
        if len(word) >= 5 and word.lower() not in {"there", "their", "about", "which", "would", "could", "should"} and word.lower() not in [x.lower() for x in content_words]:
            content_words.append(word)
    if content_words:
        notes.append("阅读提示：重点词可先看 " + " / ".join(content_words[:8]) + "，再回到整句确认语境。")
    return "\n".join(notes)


class SelectionMonitor:
    def __init__(self, callback):
        self.callback = callback
        self.enabled = True
        self.running = False
        self.hook = None
        self.mouse_proc = None
        self.down_pos = None
        self.down_time = 0
        self.thread_id = 0

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._message_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)

    def _message_loop(self):
        self.thread_id = kernel32.GetCurrentThreadId()

        @LowLevelMouseProc
        def mouse_proc(n_code, w_param, l_param):
            if n_code == HC_ACTION and self.enabled:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if w_param == WM_LBUTTONDOWN:
                    self.down_pos = (info.pt.x, info.pt.y)
                    self.down_time = time.time()
                elif w_param == WM_LBUTTONUP and self.down_pos:
                    distance = math.hypot(info.pt.x - self.down_pos[0], info.pt.y - self.down_pos[1])
                    duration = time.time() - self.down_time
                    self.down_pos = None
                    if distance >= 18 and duration >= 0.08:
                        threading.Timer(0.18, self.callback).start()
            return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)

        self.mouse_proc = mouse_proc
        self.hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self.mouse_proc, None, 0)
        user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT, VK_T)
        msg = wt.MSG()
        while self.running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                self.callback()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterHotKey(None, 1)


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x720")
        self.root.minsize(520, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.events = queue.Queue()
        self.last_auto_text = ""
        self.last_auto_time = 0
        self.auto_enabled = tk.BooleanVar(value=True)
        self.keep_top = tk.BooleanVar(value=True)
        self.restore_clipboard = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="已开启：拖选英文后松开鼠标，或按 Ctrl+Shift+T。")
        self._build_ui()
        self.monitor = SelectionMonitor(self.capture_selection)
        self.monitor.start()
        self.root.after(100, self.process_events)
        self.root.attributes("-topmost", True)

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 6))
        style.configure("TCheckbutton", font=("Microsoft YaHei UI", 10))
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        ttk.Button(header, text="退出", command=self.shutdown).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="隐藏", command=self.hide_window).pack(side="right")
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(12, 8))
        ttk.Checkbutton(controls, text="监听鼠标选中", variable=self.auto_enabled, command=self.toggle_auto).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(controls, text="窗口置顶", variable=self.keep_top, command=self.toggle_topmost).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(controls, text="恢复剪贴板文本", variable=self.restore_clipboard).pack(side="left")
        ttk.Label(outer, textvariable=self.status_text, wraplength=660).pack(fill="x", pady=(0, 10))
        ttk.Label(outer, text="英文原文").pack(anchor="w")
        self.source = tk.Text(outer, height=7, wrap="word", font=("Segoe UI", 11), padx=10, pady=8)
        self.source.pack(fill="x", pady=(4, 10))
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 12))
        ttk.Button(actions, text="翻译并解释", command=self.translate_manual).pack(side="left")
        ttk.Button(actions, text="复制中文", command=self.copy_translation).pack(side="left", padx=8)
        ttk.Button(actions, text="清空", command=self.clear_all).pack(side="left")
        ttk.Label(outer, text="中文翻译").pack(anchor="w")
        self.translation = tk.Text(outer, height=6, wrap="word", font=("Microsoft YaHei UI", 12), padx=10, pady=8)
        self.translation.pack(fill="both", expand=True, pady=(4, 10))
        ttk.Label(outer, text="语法解释").pack(anchor="w")
        self.grammar = tk.Text(outer, height=10, wrap="word", font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        self.grammar.pack(fill="both", expand=True, pady=(4, 0))

    def set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def toggle_auto(self):
        self.monitor.enabled = bool(self.auto_enabled.get())
        self.status_text.set("已开启监听：拖选英文后松开鼠标，或按 Ctrl+Shift+T。" if self.auto_enabled.get() else "已暂停鼠标监听；仍可粘贴英文后点击翻译。")

    def toggle_topmost(self):
        self.root.attributes("-topmost", bool(self.keep_top.get()))

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        if self.keep_top.get():
            self.root.attributes("-topmost", True)

    def capture_selection(self):
        self.events.put(("capture", None))

    def process_events(self):
        while True:
            try:
                event, _ = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "capture":
                self.handle_capture()
        self.root.after(120, self.process_events)

    def handle_capture(self):
        if not self.auto_enabled.get():
            return
        try:
            selected = extract_selected_text(self.restore_clipboard.get())
        except Exception as exc:
            self.status_text.set(f"读取选中文本失败：{exc}")
            return
        if not looks_like_english(selected):
            return
        now = time.time()
        if selected == self.last_auto_text and now - self.last_auto_time < 2:
            return
        self.last_auto_text = selected
        self.last_auto_time = now
        self.show_window()
        self.translate_text(selected, "选中文本")

    def translate_manual(self):
        text = normalize_selected_text(self.source.get("1.0", "end"))
        if not text:
            messagebox.showinfo(APP_TITLE, "请先输入或选中一段英文。")
            return
        self.translate_text(text, "手动输入")

    def translate_text(self, text, source):
        self.set_text(self.source, text)
        self.set_text(self.translation, "翻译中...")
        self.set_text(self.grammar, analyze_grammar(text))
        self.status_text.set(f"正在翻译：{source}")
        threading.Thread(target=self._translate_worker, args=(text,), daemon=True).start()

    def _translate_worker(self, text):
        try:
            translated, provider = translate_to_chinese(text)
            self.root.after(0, lambda: self.finish_translation(translated, provider))
        except Exception as exc:
            self.root.after(0, lambda: self.finish_error(exc))

    def finish_translation(self, translated, provider):
        self.set_text(self.translation, translated)
        self.status_text.set(f"完成，翻译来源：{provider}。")

    def finish_error(self, exc):
        self.set_text(self.translation, "在线翻译暂时失败。请检查网络，或稍后重试。")
        self.status_text.set(str(exc))

    def copy_translation(self):
        text = normalize_selected_text(self.translation.get("1.0", "end"))
        if text and text != "翻译中...":
            clipboard_set_text(text)
            self.status_text.set("中文翻译已复制到剪贴板。")

    def clear_all(self):
        self.set_text(self.source, "")
        self.set_text(self.translation, "")
        self.set_text(self.grammar, "")
        self.status_text.set("已清空。")

    def shutdown(self):
        self.monitor.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    TranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
