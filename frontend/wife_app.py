"""
Dua Video Generator - Simple Wife-Friendly GUI
No password, no CLI, no Arabic typing needed.
Category -> Dua -> Generate. That's it.
"""

import glob
import json
import os
import queue
import re
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core.dua_database import DuaDatabase
from core.master_config import MASTER_EFFECTS
from core.project_info import PROJECT
from frontend.effect_preview import (
    EFFECT_INFO,
    build_effect_preview,
    preview_exists,
    preview_path,
)
from main import DuaVideoPipeline, dua_video_filename

# Generate EFFECT_OPTIONS dynamically from master config
EFFECT_OPTIONS = (
    [
        ("Auto (AI)", "auto"),
        ("Simple", "none"),
    ]
    + [(info["name"], key) for key, info in MASTER_EFFECTS.items()]
    + [
        ("Islamic Ultra Pack", "ultra_pack"),
    ]
)

FONT_SUB = ("Segoe UI", 12)
FONT_ARABIC = ("Traditional Arabic", 26, "bold")
FONT_URDU = ("Segoe UI", 17)

DONE = "\u2713"
NEW = ""


class _StdoutQueue:
    """Redirects stdout during generation into a queue the GUI can poll."""

    def __init__(self):
        self.lines = queue.Queue()

    def write(self, text):
        if text.strip():
            self.lines.put(text.rstrip())
        return len(text)

    def flush(self):
        pass


class DuaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.db = DuaDatabase()
        self.pipeline = DuaVideoPipeline()
        self.output_dir = PROJECT.OUTPUT_DIR
        self.selected_dua = None
        self.selected_category = None
        self.running = False
        self.only_new = True
        self._cat_buttons = {}
        self._dua_buttons = []
        self._sink = None
        self._gen_thread = None

        self.title("Dua Video Generator - MASOOD NASIR")
        self._center_window()
        self.minsize(1050, 680)

        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_icon()

        cats = self.db.get_categories()
        self._select_category(None)

    # ---------- Window helpers ----------

    def _center_window(self):
        w, h = 1200, 780
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _set_icon(self):
        icon = os.path.join(PROJECT.ASSETS_DIR, "icons", "app.ico")
        if os.path.exists(icon):
            with contextlib.suppress(tk.TclError):
                self.iconbitmap(icon)

    def _on_close(self):
        if self.running and not messagebox.askyesno(
            "Band Karein?", "Video abhi ban rahi hai.\nPhir bhi app band karein?"
        ):
            return
        self.destroy()

    def _bind_shortcuts(self):
        self.bind("<Return>", lambda e: self._start_generation())
        self.bind("<Control-n>", lambda e: self._open_add_dialog())
        self.bind("<Control-e>", lambda e: self._open_edit_dialog())
        self.bind("<Control-d>", lambda e: self._delete_dua())
        self.bind("<Control-o>", lambda e: self._open_folder())
        self.bind("<Control-r>", lambda e: self._reload_library())
        self.bind("<F5>", lambda e: self._reload_library())

    # ---------- UI ----------

    def _build_ui(self):
        self._header = ctk.CTkFrame(self, height=64)
        self._header.pack(fill="x", padx=10, pady=(10, 5))
        self._header.pack_propagate(False)

        ctk.CTkLabel(self._header, text="Dua Video Generator", font=("Segoe UI", 22, "bold")).pack(side="left", padx=18)
        ctk.CTkLabel(self._header, text="MASOOD NASIR | @bushranasir1075", font=FONT_SUB).pack(side="right", padx=18)

        self._body = ctk.CTkFrame(self)
        self._body.pack(fill="both", expand=True, padx=10, pady=5)

        self._sidebar = ctk.CTkFrame(self._body, width=250, corner_radius=12)
        self._sidebar.pack(side="left", fill="y", padx=(5, 3), pady=5)
        self._sidebar.pack_propagate(False)
        ctk.CTkLabel(self._sidebar, text="Dua Categories", font=("Segoe UI", 15, "bold")).pack(pady=(14, 8))

        self._list_frame = ctk.CTkFrame(self._body, width=340, corner_radius=12)
        self._list_frame.pack(side="left", fill="y", padx=3, pady=5)
        self._list_frame.pack_propagate(False)

        self._top_row = ctk.CTkFrame(self._list_frame, fg_color="transparent")
        self._top_row.pack(fill="x", padx=10, pady=(12, 4))
        ctk.CTkLabel(self._top_row, text="Duas", font=("Segoe UI", 15, "bold")).pack(side="left")
        self._only_new_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self._top_row,
            text="Sirf nayi",
            font=("Segoe UI", 12),
            variable=self._only_new_var,
            command=self._refresh_list,
        ).pack(side="right")

        self._scroll = ctk.CTkScrollableFrame(self._list_frame, corner_radius=0)
        self._scroll.pack(fill="both", expand=True, padx=6, pady=(4, 8))

        self._preview = ctk.CTkFrame(self._body, corner_radius=12)
        self._preview.pack(side="left", fill="both", expand=True, padx=3, pady=5)

        self._build_preview()
        self._build_categories()

    def _build_categories(self):
        all_btn = ctk.CTkButton(
            self._sidebar,
            text="  All Duas  ",
            font=FONT_SUB,
            anchor="w",
            height=40,
            corner_radius=10,
            command=lambda: self._select_category(None),
        )
        all_btn.pack(fill="x", padx=10, pady=3)
        self._cat_buttons[None] = all_btn
        for cat in self.db.get_categories():
            label = f"{cat.get('icon', '')}  {cat.get('name_urdu', cat.get('name', ''))}"
            btn = ctk.CTkButton(
                self._sidebar,
                text=label,
                font=FONT_SUB,
                anchor="w",
                height=40,
                corner_radius=10,
                command=lambda c=cat.get("id"): self._select_category(c),
            )
            btn.pack(fill="x", padx=10, pady=3)
            btn.bind("<Button-3>", lambda e, c=cat.get("id"): self._show_category_menu(e, c))
            self._cat_buttons[cat.get("id")] = btn
        self._refresh_category_counts()

    def _build_preview(self):
        # Scrollable preview area (lambi dua par scroll ho sakti hai)
        self._pv_scroll = ctk.CTkScrollableFrame(self._preview, corner_radius=12)
        self._pv_scroll.pack(fill="both", expand=True, padx=14, pady=(12, 4))

        self._pv_title = ctk.CTkLabel(self._pv_scroll, text="", font=("Segoe UI", 18, "bold"))
        self._pv_title.pack(pady=(18, 10))

        self._pv_arabic = ctk.CTkLabel(self._pv_scroll, text="", font=FONT_ARABIC, text_color="#E8D48B", wraplength=600)
        self._pv_arabic.pack(padx=20, pady=8)

        self._pv_urdu = ctk.CTkLabel(
            self._pv_scroll, text="", font=FONT_URDU, text_color="#D7D7D7", wraplength=600, justify="right"
        )
        self._pv_urdu.pack(padx=20, pady=10)

        self._pv_ref = ctk.CTkLabel(self._pv_scroll, text="", font=("Segoe UI", 13), text_color="#8FA3C0")
        self._pv_ref.pack(pady=6)

        ctk.CTkLabel(self._pv_scroll, text="", font=("Segoe UI", 2)).pack(pady=6)

        for w in (self._pv_scroll, self._pv_title, self._pv_arabic, self._pv_urdu, self._pv_ref):
            w.bind("<Button-3>", self._show_preview_menu)

        # Fixed controls area - hamesha nazar aayenge (scroll ke sath ghayab nahi honge)
        ctrl = ctk.CTkFrame(self._preview, corner_radius=12)
        ctrl.pack(fill="x", padx=14, pady=(4, 12))

        eff_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        eff_row.pack(fill="x", padx=40, pady=(10, 2))
        ctk.CTkLabel(eff_row, text="Effect:", font=("Segoe UI", 14, "bold")).pack(side="left")
        self._effect_var = ctk.StringVar(value="Auto (AI)")
        self._effect_menu = ctk.CTkOptionMenu(
            eff_row,
            variable=self._effect_var,
            height=32,
            width=260,
            values=[label for label, _ in EFFECT_OPTIONS],
            font=("Segoe UI", 13),
            command=self._on_effect_change,
        )
        self._effect_menu.pack(side="left", padx=(12, 0))
        self._preview_btn = ctk.CTkButton(
            eff_row,
            text="\u25b6 Preview",
            font=("Segoe UI", 13, "bold"),
            height=32,
            fg_color="#6A4B9C",
            hover_color="#57407E",
            command=self._play_effect_preview,
        )
        self._preview_btn.pack(side="left", padx=(10, 0))

        self._eff_desc = ctk.CTkLabel(ctrl, text="", font=("Segoe UI", 12), text_color="#9B9B9B", anchor="w")
        self._eff_desc.pack(fill="x", padx=40, pady=(0, 2))
        self._on_effect_change("Auto (AI)")

        gen_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        gen_row.pack(fill="x", padx=40, pady=(12, 6))
        self._gen_btn = ctk.CTkButton(
            gen_row,
            text="Video Banao",
            font=("Segoe UI", 20, "bold"),
            height=56,
            corner_radius=14,
            fg_color="#1F9E5A",
            hover_color="#17874C",
            command=self._start_generation,
        )
        self._gen_btn.pack(side="left", expand=True, fill="x")
        self._cancel_btn = ctk.CTkButton(
            gen_row,
            text="Cancel",
            font=("Segoe UI", 14, "bold"),
            height=56,
            width=120,
            corner_radius=14,
            fg_color="#B13E3E",
            hover_color="#8F3131",
            command=self._cancel_generation,
            state="disabled",
        )
        self._cancel_btn.pack(side="left", padx=(8, 0))

        self._progress = ctk.CTkProgressBar(ctrl, height=14, corner_radius=7)
        self._progress.pack(fill="x", padx=40, pady=(0, 4))
        self._progress.set(0)

        self._status = ctk.CTkLabel(ctrl, text="Pehle ek dua chunein", font=FONT_SUB)
        self._status.pack(pady=(4, 8))

        controls = ctk.CTkFrame(ctrl, fg_color="transparent")
        controls.pack(fill="x", padx=40, pady=(2, 10))
        self._play_btn = ctk.CTkButton(
            controls, text="\u25b6 Video Dekho", font=FONT_SUB, command=self._play_video, state="disabled"
        )
        self._play_btn.pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(controls, text="Output Folder Kholo", font=FONT_SUB, command=self._open_folder).pack(
            side="left", expand=True, fill="x", padx=3
        )
        ctk.CTkButton(controls, text="Nayi Dua Add Karo", font=FONT_SUB, command=self._open_add_dialog).pack(
            side="left", expand=True, fill="x", padx=3
        )

        edit_del = ctk.CTkFrame(ctrl, fg_color="transparent")
        edit_del.pack(fill="x", padx=40, pady=(0, 10))
        ctk.CTkButton(
            edit_del,
            text="\u2b06 Copy Arabic",
            font=FONT_SUB,
            command=lambda: self._copy_text(self.selected_dua.get("arabic", "") if self.selected_dua else ""),
        ).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(
            edit_del,
            text="\u2b06 Copy Urdu",
            font=FONT_SUB,
            command=lambda: self._copy_text(self.selected_dua.get("urdu", "") if self.selected_dua else ""),
        ).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(edit_del, text="\u270f Edit Dua", font=FONT_SUB, command=self._open_edit_dialog).pack(
            side="left", expand=True, fill="x", padx=3
        )
        ctk.CTkButton(
            edit_del,
            text="\u2715 Delete Dua",
            font=FONT_SUB,
            fg_color="#B13E3E",
            hover_color="#8F3131",
            command=self._delete_dua,
        ).pack(side="left", expand=True, fill="x", padx=3)

        self._log = ctk.CTkTextbox(self._preview, height=90, corner_radius=10, font=("Consolas", 11))
        self._log.pack(fill="x", padx=14, pady=(0, 12))
        self._log.configure(state="disabled")

    # ---------- State / Refresh ----------

    def _select_category(self, cat_id):
        self.selected_category = cat_id
        for cid, btn in self._cat_buttons.items():
            if cid == cat_id:
                btn.configure(fg_color="#1F6AA5")
            else:
                btn.configure(fg_color="#2B2B2B")
        self._refresh_list()

    def _is_generated(self, dua):
        cat_dir = os.path.join(self.output_dir, dua.get("category"))
        title_path = os.path.join(cat_dir, dua_video_filename(dua))
        legacy_path = os.path.join(cat_dir, f"{dua.get('id')}.mp4")
        return os.path.exists(title_path) or os.path.exists(legacy_path)

    def _refresh_list(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._dua_buttons = []
        if self.selected_category:
            duas = self.db.get_duas_by_category(self.selected_category)
        else:
            duas = self.db.get_all_duas()
        self._refresh_category_counts()
        if self._only_new_var.get():
            duas = [d for d in duas if not self._is_generated(d)]
        if not duas:
            ctk.CTkLabel(
                self._scroll,
                text="Koi nayi dua nahi bachi\n(Iss category ki sab videos ban chuki hain)",
                font=FONT_SUB,
                text_color="#9B9B9B",
            ).pack(pady=20)
        for dua in duas:
            status = DONE if self._is_generated(dua) else NEW
            btn = ctk.CTkButton(
                self._scroll,
                text=f"{status}  {dua.get('title', '')}",
                font=("Segoe UI", 13),
                anchor="w",
                height=38,
                corner_radius=8,
                fg_color="#333333",
                hover_color="#1F6AA5",
                command=lambda d=dua: self._select_dua(d),
            )
            btn.pack(fill="x", padx=4, pady=2)
            btn.bind("<Button-3>", lambda e, d=dua: self._show_dua_menu(e, d))
            self._dua_buttons.append((dua, btn))
        if not self.selected_dua or self.selected_dua.get("category") != self.selected_category:
            self._select_dua(duas[0] if duas else None)

    def _refresh_category_counts(self):
        all_duas = self.db.get_all_duas()
        all_total = len(all_duas)
        all_remaining = sum(1 for d in all_duas if not self._is_generated(d))
        all_btn = self._cat_buttons.get(None)
        if all_btn:
            all_btn.configure(text=f"  All Duas  ({all_remaining}/{all_total})")
        for cat in self.db.get_categories():
            cat_id = cat.get("id")
            btn = self._cat_buttons.get(cat_id)
            if btn is None:
                continue
            total = len(self.db.get_duas_by_category(cat_id))
            remaining = sum(1 for d in self.db.get_duas_by_category(cat_id) if not self._is_generated(d))
            label = f"{cat.get('icon', '')}  {cat.get('name_urdu', cat.get('name', ''))}  ({remaining}/{total})"
            btn.configure(text=label)

    def _select_dua(self, dua):
        if not dua:
            self.selected_dua = None
            self._pv_title.configure(text="")
            self._pv_arabic.configure(text="")
            self._pv_urdu.configure(text="")
            self._pv_ref.configure(text="")
            self._play_btn.configure(state="disabled")
            return
        self.selected_dua = dua
        self._pv_title.configure(text=dua.get("title", ""))
        self._pv_arabic.configure(text=dua.get("arabic", ""))
        self._pv_urdu.configure(text=dua.get("urdu", ""))
        ref = dua.get("reference", "")
        self._pv_ref.configure(text=f"Reference: {ref}" if ref else "")
        if self._is_generated(dua):
            self._gen_btn.configure(text="Video Banao (phir se)")
            self._play_btn.configure(state="normal")
        else:
            self._gen_btn.configure(text="Video Banao")
            self._play_btn.configure(state="disabled")
        self._log_write("")

    def _reload_library(self):
        self.db._load_data()
        self._refresh_category_counts()
        self._refresh_list()
        self._status.configure(text="Library refresh ho gayi")

    # ---------- Context menus ----------

    def _show_dua_menu(self, event, dua):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="\u25b6 Video Banao", command=lambda: self._ctx(dua, "gen"))
        if self._is_generated(dua):
            m.add_command(label="\u25b6 Video Dekho", command=lambda: self._ctx(dua, "play"))
        m.add_separator()
        m.add_command(label="\u270f Edit Dua", command=lambda: self._ctx(dua, "edit"))
        m.add_command(label="\u2715 Delete Dua", command=lambda: self._ctx(dua, "del"))
        m.add_separator()
        m.add_command(label="Copy Arabic", command=lambda: self._ctx(dua, "copy_ar"))
        m.add_command(label="Copy Urdu", command=lambda: self._ctx(dua, "copy_ur"))
        self._popup(m, event)

    def _show_preview_menu(self, event):
        dua = self.selected_dua
        if not dua:
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="\u25b6 Video Banao", command=lambda: self._ctx(dua, "gen"))
        if self._is_generated(dua):
            m.add_command(label="\u25b6 Video Dekho", command=lambda: self._ctx(dua, "play"))
        m.add_separator()
        m.add_command(label="\u270f Edit Dua", command=lambda: self._ctx(dua, "edit"))
        m.add_command(label="\u2715 Delete Dua", command=lambda: self._ctx(dua, "del"))
        m.add_separator()
        m.add_command(label="Copy Arabic", command=lambda: self._ctx(dua, "copy_ar"))
        m.add_command(label="Copy Urdu", command=lambda: self._ctx(dua, "copy_ur"))
        m.add_command(label="Output Folder Kholo", command=self._open_folder)
        self._popup(m, event)

    def _show_category_menu(self, event, cat_id):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Select", command=lambda: self._select_category(cat_id))
        m.add_command(label="Refresh Library", command=self._reload_library)
        self._popup(m, event)

    def _popup(self, m, event):
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _ctx(self, dua, action):
        if action == "gen":
            self._select_dua(dua)
            self._start_generation()
        elif action == "play":
            self._select_dua(dua)
            self._play_video()
        elif action == "edit":
            self._select_dua(dua)
            self._open_edit_dialog()
        elif action == "del":
            self._select_dua(dua)
            self._delete_dua()
        elif action == "copy_ar":
            self._copy_text(dua.get("arabic", ""))
        elif action == "copy_ur":
            self._copy_text(dua.get("urdu", ""))

    # ---------- Actions ----------

    def _play_video(self, dua=None):
        dua = dua or self.selected_dua
        if not dua:
            return
        cat_dir = os.path.join(self.output_dir, dua.get("category"))
        for name in (dua_video_filename(dua), f"{dua.get('id')}.mp4"):
            p = os.path.join(cat_dir, name)
            if os.path.exists(p):
                os.startfile(p)
                return
        self._status.configure(text="Video abhi nahi bani - pehle Video Banao dabayein")

    def _copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status.configure(text="Text copy ho gaya (Ctrl+V se paste karein)")

    def _open_folder(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.startfile(self.output_dir)

    # ---------- Logging ----------

    def _log_write(self, text):
        self._log.configure(state="normal")
        if text:
            self._log.insert("end", text + "\n")
            self._log.see("end")
        self._log.configure(state="disabled")

    def _set_progress(self, value):
        self._progress.set(value)

    # ---------- Effect preview ----------

    def _on_effect_change(self, label):
        key = dict(EFFECT_OPTIONS).get(label, "none")
        self._eff_desc.configure(text=EFFECT_INFO.get(key, ""))

    def _play_effect_preview(self):
        if self.running:
            self._status.configure(text="Pehle video banna khatam hone dein")
            return
        label = self._effect_var.get()
        key = dict(EFFECT_OPTIONS).get(label, "none")
        if preview_exists(key):
            os.startfile(preview_path(key))
            return
        self._preview_btn.configure(state="disabled", text="Bana raha hai...")
        self._status.configure(text="Preview ban raha hai... (thodi dair lagegi)")
        threading.Thread(target=self._build_and_play_preview, args=(key,), daemon=True).start()

    def _build_and_play_preview(self, key):
        try:
            path = build_effect_preview(key)
            self.after(0, lambda: self._finish_preview(path, None))
        except Exception as e:  # noqa: F841 — e captured by lambda
            self.after(0, lambda e=e: self._finish_preview(None, str(e)))

    def _finish_preview(self, path, error):
        self._preview_btn.configure(state="normal", text="\u25b6 Preview")
        if error:
            self._status.configure(text=f"Preview ban nahi saka: {error}")
        else:
            self._status.configure(text="Preview ready - ab dekh rahe hain")
            os.startfile(path)

    # ---------- Generation ----------

    def _start_generation(self):
        if self.running:
            return
        if not self.selected_dua:
            self._status.configure(text="Pehle ek dua chunein")
            return
        self.running = True
        self._gen_btn.configure(state="disabled", text="Ban raha hai...")
        self._cancel_btn.configure(state="normal")
        self._set_progress(0.05)
        self._status.configure(text="Video ban rahi hai... (2-4 minute lagte hain)")
        self._log_write("")

        dua = self.selected_dua
        self._gen_thread = threading.Thread(target=self._run_generation, args=(dua,), daemon=True)
        self._gen_thread.start()
        self.after(200, self._poll_log)

    def _run_generation(self, dua):
        sink = _StdoutQueue()
        self._sink = sink
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = sink, sink
        ok = False
        effect = dict(EFFECT_OPTIONS).get(self._effect_var.get(), "none")
        try:
            if effect == "ultra_pack":
                # Islamic Ultra Pack - sab kuch random!
                from core.mega_pack import MegaPackPipeline

                mega = MegaPackPipeline()
                result = mega.generate(
                    arabic=dua.get("arabic", ""),
                    urdu=dua.get("urdu", ""),
                    title=dua.get("name", dua.get("title", "")),
                )
                ok = result.success
                if not ok:
                    sink.lines.put(f"[ERROR] {result.error}")
            else:
                ok = self.pipeline.generate_video(dua.get("id"), effect=effect)
        except Exception as e:
            sink.lines.put(f"[ERROR] {e}")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        self.after(0, self._generation_done, ok)

    def _poll_log(self):
        if not self.running:
            return
        sink = self._sink
        if sink:
            while not sink.lines.empty():
                line = sink.lines.get()
                self._log_write(line)
                self._update_progress(line)
        self.after(200, self._poll_log)

    def _update_progress(self, line):
        if "Generating TTS" in line:
            self._set_progress(0.15)
        elif "TTS Generated" in line:
            self._set_progress(0.25)
        elif "Merging Audio" in line or "AudioMixer" in line:
            self._set_progress(0.4)
        elif "Audio ready" in line:
            self._set_progress(0.5)
        elif "Generating frames" in line:
            self._set_progress(0.6)
        elif "Frames generated" in line:
            self._set_progress(0.75)
        elif "Assembling video" in line:
            self._set_progress(0.8)
        elif "Video assembled" in line:
            self._set_progress(0.9)
        elif "Quality check" in line:
            self._set_progress(0.95)
        elif "[SUCCESS]" in line:
            self._set_progress(1.0)

    def _cancel_generation(self):
        if not self.running:
            return
        self.pipeline._cancel_requested = True
        self._cancel_btn.configure(state="disabled", text="Cancelling...")
        self._status.configure(text="Cancel ho raha hai... (is step ke baad rukega)")

    def _generation_done(self, ok):
        self.running = False
        self._sink = None
        self._cancel_btn.configure(state="disabled", text="Cancel")
        self._gen_btn.configure(state="normal")
        if ok:
            self._set_progress(1.0)
            self._status.configure(text="Ho gaya! Video output folder me hai. \u2713")
            if self.selected_dua:
                self._play_btn.configure(state="normal")
        else:
            self._set_progress(0)
            self._status.configure(text="Masla aaya - upar log me dekhein (internet check karein)")
            self._gen_btn.configure(text="Video Banao (phir try karein)")
        self._refresh_list()
        if self.selected_dua:
            self._gen_btn.configure(
                text="Video Banao (phir se)" if self._is_generated(self.selected_dua) else "Video Banao"
            )

    # ---------- Add / Edit / Delete Dua ----------

    def _open_add_dialog(self):
        self._dua_form(None)

    def _open_edit_dialog(self):
        if not self.selected_dua:
            self._status.configure(text="Pehle ek dua chunein")
            return
        self._dua_form(self.selected_dua)

    def _delete_dua(self):
        dua = self.selected_dua
        if not dua:
            self._status.configure(text="Pehle ek dua chunein")
            return
        title = dua.get("title", "")
        cat_dir = os.path.join(self.output_dir, dua.get("category"))
        video_paths = [
            os.path.join(cat_dir, dua_video_filename(dua)),
            os.path.join(cat_dir, f"{dua.get('id')}.mp4"),
        ]
        video_paths = [p for p in video_paths if os.path.exists(p)]
        msg = f"'{title}' ko library se delete karein?"
        if video_paths:
            msg += "\n\nSath hi uski bani hui video bhi delete ho jayegi."
        if not messagebox.askyesno("Delete Dua", msg, icon="warning"):
            return
        self._remove_dua_from_file(dua)
        for p in video_paths:
            with contextlib.suppress(OSError):
                os.remove(p)
        self.selected_dua = None
        self._select_category(dua.get("category"))

    def _cat_label_map(self):
        mapping = {}
        for c in self.db.get_categories():
            label = f"{c.get('icon', '')}  {c.get('name_urdu', c.get('name', ''))}"
            mapping[label] = c.get("id")
        return mapping

    def _dua_form(self, dua):
        editing = dua is not None
        cat_map = self._cat_label_map()
        labels = list(cat_map.keys())
        win = ctk.CTkToplevel(self)
        win.title("Dua Edit Karo" if editing else "Nayi Dua Add Karo")
        win.transient(self)
        win.grab_set()
        win.minsize(560, 620)
        win.geometry("640x700")
        win.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - 640) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - 700) // 2)
        win.geometry(f"640x700+{x}+{y}")

        ctk.CTkLabel(win, text="Dua Edit Karo" if editing else "Nayi Dua Add Karo", font=("Segoe UI", 18, "bold")).pack(
            pady=(12, 2)
        )
        ctk.CTkLabel(
            win, text="Arabic aur Urdu text zaroori hai. Baqi optional hai.", font=FONT_SUB, text_color="#9B9B9B"
        ).pack(pady=(0, 4))

        fields = ctk.CTkScrollableFrame(win, corner_radius=10)
        fields.pack(fill="both", expand=True, padx=20, pady=(6, 4))

        ctk.CTkLabel(fields, text="Title (Urdu):", font=("Segoe UI", 13)).pack(anchor="w", pady=(10, 2))
        title_e = ctk.CTkEntry(fields, height=34)
        title_e.pack(fill="x", padx=4)
        if editing:
            title_e.insert(0, dua.get("title", ""))

        current_cat_id = (dua.get("category") if editing else self.selected_category) or ""
        current_label = next((l for l, cid in cat_map.items() if cid == current_cat_id), labels[0] if labels else "")
        ctk.CTkLabel(fields, text="Category:", font=("Segoe UI", 13)).pack(anchor="w", pady=(10, 2))
        cat_var = ctk.StringVar(value=current_label)
        cat_menu = ctk.CTkOptionMenu(fields, variable=cat_var, height=34, values=labels, font=("Segoe UI", 13))
        cat_menu.pack(fill="x", padx=4)

        ctk.CTkLabel(fields, text="Arabic Dua:", font=("Segoe UI", 13)).pack(anchor="w", pady=(10, 2))
        arabic_t = ctk.CTkTextbox(fields, height=90, font=("Traditional Arabic", 20))
        arabic_t.pack(fill="x", padx=4)
        if editing:
            arabic_t.insert("1.0", dua.get("arabic", ""))

        ctk.CTkLabel(fields, text="Urdu Translation:", font=("Segoe UI", 13)).pack(anchor="w", pady=(10, 2))
        urdu_t = ctk.CTkTextbox(fields, height=90, font=("Segoe UI", 15))
        urdu_t.pack(fill="x", padx=4)
        if editing:
            urdu_t.insert("1.0", dua.get("urdu", ""))

        ctk.CTkLabel(fields, text="Reference (optional):", font=("Segoe UI", 13)).pack(anchor="w", pady=(10, 2))
        ref_e = ctk.CTkEntry(fields, height=34)
        ref_e.pack(fill="x", padx=4, pady=(0, 12))
        if editing:
            ref_e.insert(0, dua.get("reference", ""))

        def save():
            title = title_e.get().strip()
            arabic = arabic_t.get("1.0", "end").strip()
            urdu = urdu_t.get("1.0", "end").strip()
            ref = ref_e.get().strip()
            cat = cat_map.get(cat_var.get().strip(), current_cat_id)
            if not (title and arabic and urdu and cat):
                messagebox.showerror("Error", "Title, Arabic aur Urdu bharna zaroori hai.")
                return
            if editing:
                old_cat = dua.get("category")
                dua["title"] = title
                dua["title_en"] = title
                dua["arabic"] = arabic
                dua["urdu"] = urdu
                dua["reference"] = ref or ""
                dua["category"] = cat
                self._update_dua_file(dua, old_cat)
                win.destroy()
                self._select_category(cat)
            else:
                dua_id = re.sub(r"[^a-z0-9]+", "_", title.lower().strip()).strip("_") or "dua"
                if dua_id[0].isdigit():
                    dua_id = "d_" + dua_id
                existing = [d.get("id") for d in self.db.get_all_duas()]
                if dua_id in existing:
                    dua_id = f"{dua_id}_{int(time.time())}"
                new_dua = {
                    "id": dua_id,
                    "category": cat,
                    "title": title,
                    "title_en": title,
                    "arabic": arabic,
                    "urdu": urdu,
                    "reference": ref or "",
                }
                self._save_dua(new_dua)
                win.destroy()
                self._select_category(cat)

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(2, 14))
        ctk.CTkButton(
            bottom,
            text="Save",
            font=("Segoe UI", 15, "bold"),
            height=44,
            fg_color="#1F9E5A",
            hover_color="#17874C",
            command=save,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(
            bottom,
            text="Cancel",
            font=("Segoe UI", 15, "bold"),
            height=44,
            fg_color="#3A3A3A",
            hover_color="#555555",
            command=win.destroy,
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    # ---------- File persistence (atomic + backup) ----------

    def _read_duas_file(self):
        path = os.path.join(PROJECT.DATA_DIR, "duas.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {"duas": data}
        data.setdefault("duas", [])
        return data, path

    def _backup_file(self, path):
        try:
            bdir = os.path.join(PROJECT.DATA_DIR, "backup")
            os.makedirs(bdir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = os.path.splitext(os.path.basename(path))[0]
            shutil.copy2(path, os.path.join(bdir, f"{name}_{stamp}.json"))
            old = sorted(glob.glob(os.path.join(bdir, f"{name}_*.json")))
            for stale in old[:-20]:
                with contextlib.suppress(OSError):
                    os.remove(stale)
        except OSError:
            pass

    def _atomic_write(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _save_dua(self, dua):
        data, path = self._read_duas_file()
        self._backup_file(path)
        data["duas"].append(dua)
        self._atomic_write(path, data)

        cat_path = os.path.join(PROJECT.DATA_DIR, "categories.json")
        with open(cat_path, encoding="utf-8") as f:
            cdata = json.load(f)
        self._backup_file(cat_path)
        for c in cdata.get("categories", []):
            if c.get("id") == dua["category"]:
                c["dua_count"] = c.get("dua_count", 0) + 1
        cdata["total_duas"] = cdata.get("total_duas", 0) + 1
        self._atomic_write(cat_path, cdata)

        self.db._load_data()

    def _update_dua_file(self, dua, old_category):
        data, path = self._read_duas_file()
        self._backup_file(path)
        for i, d in enumerate(data["duas"]):
            if d.get("id") == dua.get("id"):
                data["duas"][i] = dua
                break
        self._atomic_write(path, data)

        cat_path = os.path.join(PROJECT.DATA_DIR, "categories.json")
        with open(cat_path, encoding="utf-8") as f:
            cdata = json.load(f)
        self._backup_file(cat_path)
        for c in cdata.get("categories", []):
            if c.get("id") == old_category and old_category != dua["category"]:
                c["dua_count"] = max(0, c.get("dua_count", 0) - 1)
            elif c.get("id") == dua["category"] and old_category != dua["category"]:
                c["dua_count"] = c.get("dua_count", 0) + 1
        self._atomic_write(cat_path, cdata)

        self.db._load_data()

    def _remove_dua_from_file(self, dua):
        data, path = self._read_duas_file()
        self._backup_file(path)
        data["duas"] = [d for d in data["duas"] if d.get("id") != dua.get("id")]
        self._atomic_write(path, data)

        cat_path = os.path.join(PROJECT.DATA_DIR, "categories.json")
        with open(cat_path, encoding="utf-8") as f:
            cdata = json.load(f)
        self._backup_file(cat_path)
        for c in cdata.get("categories", []):
            if c.get("id") == dua.get("category"):
                c["dua_count"] = max(0, c.get("dua_count", 0) - 1)
        cdata["total_duas"] = max(0, cdata.get("total_duas", 0) - 1)
        self._atomic_write(cat_path, cdata)

        self.db._load_data()


if __name__ == "__main__":
    app = DuaApp()
    app.mainloop()
