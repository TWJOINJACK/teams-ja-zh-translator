"""中日互譯快捷鍵小工具（Windows）

Ctrl+Alt+J：把目前輸入框的中文換成商務日文（全選 → 翻譯 → 貼回）
Ctrl+Alt+K：把選取的日文翻成繁體中文，顯示在滑鼠旁的小視窗
"""

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import simpledialog

# 改用 Windows 憑證庫驗證 HTTPS（防毒軟體如 Norton 會攔截並重簽連線）
import truststore

truststore.inject_into_ssl()

import anthropic  # noqa: E402
import keyboard
import pyperclip
import pystray
from PIL import Image, ImageDraw

APP_NAME = "TeamsTranslator"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "api_key": "",
    "model": "claude-opus-5-5",
    "effort": "low",
    "hotkey_reply": "ctrl+alt+j",
    "hotkey_read": "ctrl+alt+k",
}

PROMPT_ZH_TO_JA = """你是專業的中翻日譯者。使用者是台灣公司的老闆，正在 Microsoft Teams 上和日本的業務夥伴聊天。
把使用者寫的中文翻成自然、得體的商務日文：
- 使用です・ます體，適度敬語；對業務夥伴的口吻，禮貌但不過度客套，不要加原文沒有的寒暄。
- 保留原文的換行、語氣與意思；人名、公司名、產品名、數字、網址、@提及 保持原樣。
- 如果原文已經是日文，只做最小的潤飾。
只輸出翻譯結果本身，不要加任何說明、引號或前言。"""

PROMPT_JA_TO_ZH = """你是專業的日翻中譯者。使用者是台灣人，正在 Microsoft Teams 上讀日本業務夥伴傳來的訊息。
把日文翻成自然的台灣繁體中文：
- 意思準確，口吻自然，敬語的禮貌程度用適當的中文表達即可，不要逐字硬翻。
- 保留原文換行；人名、公司名、產品名、數字、網址保持原樣。
- 如果原文混有中文或英文，照常翻譯日文部分即可。
只輸出翻譯結果本身，不要加任何說明、引號或前言。"""

user32 = ctypes.windll.user32


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class Translator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=cfg["api_key"], timeout=60.0)

    def translate(self, text, system):
        response = self.client.beta.messages.create(
            model=self.cfg["model"],
            max_tokens=8000,
            system=system,
            output_config={"effort": self.cfg["effort"]},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("這段文字無法翻譯（被模型拒絕）")
        result = "".join(b.text for b in response.content if b.type == "text").strip()
        if not result:
            raise RuntimeError("沒有收到翻譯結果")
        return result


def wait_modifiers_released(timeout=1.5):
    end = time.time() + timeout
    while time.time() < end:
        if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift")):
            return
        time.sleep(0.02)


def copy_from_app(select_all):
    """送出 Ctrl+(A)+C，回傳複製到的文字；失敗回傳空字串。"""
    previous = pyperclip.paste()
    pyperclip.copy("")
    if select_all:
        keyboard.send("ctrl+a")
        time.sleep(0.05)
    keyboard.send("ctrl+c")
    end = time.time() + 1.0
    text = ""
    while time.time() < end:
        text = pyperclip.paste()
        if text:
            break
        time.sleep(0.03)
    if not text:
        pyperclip.copy(previous)
    return text


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.translator = Translator(cfg)
        self.jobs = queue.Queue()
        self.ui = queue.Queue()
        self.busy = threading.Lock()

        self.root = tk.Tk()
        self.root.withdraw()
        self.toast = None
        self.popup = None

        keyboard.add_hotkey(cfg["hotkey_reply"], lambda: self.jobs.put("reply"))
        keyboard.add_hotkey(cfg["hotkey_read"], lambda: self.jobs.put("read"))
        threading.Thread(target=self.worker, daemon=True).start()
        self.start_tray()
        self.root.after(50, self.pump_ui)

    # ---- 背景工作 ----
    def worker(self):
        while True:
            kind = self.jobs.get()
            if not self.busy.acquire(blocking=False):
                continue
            try:
                if kind == "reply":
                    self.do_reply()
                else:
                    self.do_read()
            except anthropic.AuthenticationError:
                self.ui.put(("toast_error", "API 金鑰無效，請從系統匣圖示重新設定"))
            except anthropic.RateLimitError:
                self.ui.put(("toast_error", "請求太頻繁，請稍後再試"))
            except anthropic.APIConnectionError:
                self.ui.put(("toast_error", "無法連線，請檢查網路"))
            except anthropic.APIStatusError as e:
                self.ui.put(("toast_error", f"翻譯服務錯誤（{e.status_code}）"))
            except Exception as e:  # noqa: BLE001 - 任何錯誤都要讓使用者看到
                self.ui.put(("toast_error", str(e)))
            finally:
                self.busy.release()

    def do_reply(self):
        wait_modifiers_released()
        hwnd = user32.GetForegroundWindow()
        text = copy_from_app(select_all=True)
        if not text.strip():
            self.ui.put(("toast_error", "輸入框是空的"))
            return
        self.ui.put(("toast", "翻譯成日文中…"))
        result = self.translator.translate(text, PROMPT_ZH_TO_JA)
        pyperclip.copy(result)
        if user32.GetForegroundWindow() == hwnd:
            keyboard.send("ctrl+a")
            time.sleep(0.05)
            keyboard.send("ctrl+v")
            self.ui.put(("toast_hide", None))
        else:
            self.ui.put(("toast_done", "視窗已切換，日文已複製到剪貼簿"))

    def do_read(self):
        wait_modifiers_released()
        text = copy_from_app(select_all=False)
        if not text.strip():
            self.ui.put(("toast_error", "請先用滑鼠選取要翻譯的日文"))
            return
        self.ui.put(("toast", "翻譯成中文中…"))
        result = self.translator.translate(text, PROMPT_JA_TO_ZH)
        self.ui.put(("toast_hide", None))
        self.ui.put(("popup", result))

    # ---- 介面（只在主執行緒操作 tkinter）----
    def pump_ui(self):
        try:
            while True:
                kind, payload = self.ui.get_nowait()
                if kind == "toast":
                    self.show_toast(payload)
                elif kind == "toast_error":
                    self.show_toast("⚠ " + payload, ms=4000)
                elif kind == "toast_done":
                    self.show_toast(payload, ms=3000)
                elif kind == "toast_hide":
                    self.hide_toast()
                elif kind == "popup":
                    self.show_popup(payload)
                elif kind == "set_key":
                    self.ask_api_key()
                elif kind == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self.pump_ui)

    def hide_toast(self):
        if self.toast is not None:
            self.toast.destroy()
            self.toast = None

    def show_toast(self, message, ms=None):
        self.hide_toast()
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=message, bg="#323232", fg="white", padx=16, pady=10,
                 font=("Microsoft JhengHei UI", 11)).pack()
        t.update_idletasks()
        x = t.winfo_screenwidth() - t.winfo_width() - 24
        y = t.winfo_screenheight() - t.winfo_height() - 72
        t.geometry(f"+{x}+{y}")
        self.toast = t
        if ms:
            t.after(ms, lambda: self.toast is t and self.hide_toast())

    def close_popup(self):
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None

    def show_popup(self, text):
        self.close_popup()
        p = tk.Toplevel(self.root)
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        p.configure(bg="#c8c8c8")
        frame = tk.Frame(p, bg="#fffdf5", padx=14, pady=10)
        frame.pack(padx=1, pady=1)
        tk.Label(frame, text=text, bg="#fffdf5", fg="#222", justify="left",
                 wraplength=460, font=("Microsoft JhengHei UI", 11)).pack(anchor="w")
        bar = tk.Frame(frame, bg="#fffdf5")
        bar.pack(fill="x", pady=(8, 0))
        tk.Button(bar, text="複製", relief="flat", bg="#e8e8e8",
                  command=lambda: pyperclip.copy(text)).pack(side="right", padx=(6, 0))
        tk.Button(bar, text="關閉 (Esc)", relief="flat", bg="#e8e8e8",
                  command=self.close_popup).pack(side="right")
        p.bind("<Escape>", lambda e: self.close_popup())
        p.bind("<FocusOut>", lambda e: p.after(150, self._close_if_unfocused, p))
        p.update_idletasks()
        mx, my = self.root.winfo_pointerxy()
        w, h = p.winfo_width(), p.winfo_height()
        x = min(mx + 16, p.winfo_screenwidth() - w - 8)
        y = min(my + 16, p.winfo_screenheight() - h - 48)
        p.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        p.focus_force()
        self.popup = p

    def _close_if_unfocused(self, p):
        if self.popup is p and p.focus_displayof() is None:
            self.close_popup()

    def ask_api_key(self):
        key = simpledialog.askstring(
            "中日翻譯 - API 金鑰",
            "請貼上 Claude API 金鑰（sk-ant-…）：",
            show="*", parent=self.root)
        if key and key.strip():
            self.cfg["api_key"] = key.strip()
            save_config(self.cfg)
            self.translator = Translator(self.cfg)
            self.show_toast("API 金鑰已更新", ms=2500)

    # ---- 系統匣 ----
    def start_tray(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(70, 90, 200))
        d.text((14, 18), "中日", fill="white")
        menu = pystray.Menu(
            pystray.MenuItem(
                f"{self.cfg['hotkey_reply'].upper()}：中→日（替換）", None, enabled=False),
            pystray.MenuItem(
                f"{self.cfg['hotkey_read'].upper()}：日→中（顯示）", None, enabled=False),
            pystray.MenuItem("設定 API 金鑰…", lambda: self.ui.put(("set_key", None))),
            pystray.MenuItem("結束", self.quit),
        )
        self.icon = pystray.Icon(APP_NAME, img, "中日翻譯", menu)
        self.icon.run_detached()

    def quit(self):
        self.icon.stop()
        keyboard.unhook_all()
        self.ui.put(("quit", None))

    def run(self):
        self.show_toast(
            f"中日翻譯已啟動：{self.cfg['hotkey_reply'].upper()} 中→日，"
            f"{self.cfg['hotkey_read'].upper()} 日→中", ms=4000)
        self.root.mainloop()


def main():
    # 只允許一個實例
    ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

    cfg = load_config()
    if not cfg["api_key"]:
        cfg["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if not cfg["api_key"]:
        root = tk.Tk()
        root.withdraw()
        key = simpledialog.askstring(
            "中日翻譯 - 首次設定",
            "請貼上 Claude API 金鑰（sk-ant-…）\n可在 console.anthropic.com 申請：",
            show="*", parent=root)
        root.destroy()
        if not key or not key.strip():
            sys.exit(0)
        cfg["api_key"] = key.strip()
    save_config(cfg)
    App(cfg).run()


if __name__ == "__main__":
    main()
