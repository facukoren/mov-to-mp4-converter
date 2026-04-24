#!/usr/bin/env python3
"""UI para el converter MOV -> MP4. Modo local y nube (Modal)."""

from __future__ import annotations

import datetime
import logging
import queue
import subprocess
import threading
from pathlib import Path
from tkinter import (
    Tk, StringVar, BooleanVar, END, filedialog, messagebox, ttk, Listbox, Text,
    EXTENDED, font as tkfont,
)

from convert import (
    build_args,
    build_ffmpeg_cmd,
    check_ffmpeg,
    duration_seconds,
    human_size,
    probe_full,
)

# ── Paleta ────────────────────────────────────────────────────────────────────
BG       = "#fafafa"
SURFACE  = "#ffffff"
BORDER   = "#e5e5e7"
TEXT     = "#1d1d1f"
MUTED    = "#6e6e73"
ACCENT   = "#007aff"
ACCENT_H = "#0062cc"
SUCCESS  = "#34c759"
DANGER   = "#ff3b30"


def _load_modal():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        import os
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    import modal
    return modal


class ConverterUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("MOV → MP4")
        root.geometry("780x640")
        root.minsize(680, 560)
        root.configure(bg=BG)

        self.files: list[Path] = []
        self.dest_dir: Path | None = None
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.use_cloud = BooleanVar(value=False)
        self.log_visible = BooleanVar(value=False)
        self._logger = self._setup_logger()

        self._setup_styles()
        self._build()
        self._poll_queue()
        self._refresh_file_view()

    # ── Theming ───────────────────────────────────────────────────────────────

    def _setup_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Fuentes
        self.font_title = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.font_sub   = tkfont.Font(family="Segoe UI", size=10)
        self.font_h2    = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.font_body  = tkfont.Font(family="Segoe UI", size=10)
        self.font_small = tkfont.Font(family="Segoe UI", size=9)
        self.font_mono  = tkfont.Font(family="Consolas", size=9)

        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE, relief="flat", borderwidth=1)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.font_title)
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=self.font_sub)
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=self.font_body)
        style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=self.font_small)
        style.configure("CardH.TLabel", background=SURFACE, foreground=TEXT, font=self.font_h2)
        style.configure("Status.TLabel", background=BG, foreground=MUTED, font=self.font_small)

        # Botones
        style.configure(
            "Primary.TButton",
            background=ACCENT, foreground="#ffffff",
            padding=(24, 10), font=self.font_h2,
            borderwidth=0, relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_H), ("disabled", "#b0d3ff")],
            foreground=[("disabled", "#ffffff")],
        )

        style.configure(
            "Ghost.TButton",
            background=BG, foreground=TEXT,
            padding=(12, 6), font=self.font_body,
            borderwidth=1, relief="solid",
        )
        style.map("Ghost.TButton", background=[("active", "#f0f0f2")])

        style.configure(
            "Link.TButton",
            background=BG, foreground=ACCENT,
            padding=(0, 0), font=self.font_small,
            borderwidth=0, relief="flat",
        )
        style.map("Link.TButton", background=[("active", BG)])

        style.configure(
            "CardBtn.TButton",
            background=SURFACE, foreground=TEXT,
            padding=(10, 5), font=self.font_small,
            borderwidth=1, relief="solid",
        )
        style.map("CardBtn.TButton", background=[("active", "#f0f0f2")])

        # Segmented toggle
        style.configure(
            "Seg.TRadiobutton",
            background=SURFACE, foreground=TEXT,
            padding=(14, 6), font=self.font_body,
            borderwidth=0,
        )
        style.map(
            "Seg.TRadiobutton",
            background=[("selected", ACCENT), ("active", "#f0f0f2")],
            foreground=[("selected", "#ffffff")],
            indicatorcolor=[("selected", ACCENT), ("!selected", SURFACE)],
        )

        # Progress
        style.configure(
            "Primary.Horizontal.TProgressbar",
            background=ACCENT, troughcolor="#e8e8ec",
            borderwidth=0, thickness=6,
        )

    def _setup_logger(self) -> logging.Logger:
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = log_dir / f"conversion_{stamp}.log"
        logger = logging.getLogger("converter")
        logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        logger.info("Sesion iniciada")
        self._log_file = log_file
        return logger

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_frame = ttk.Frame(self.root, style="App.TFrame", padding=(24, 20))
        root_frame.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(root_frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="MOV → MP4", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Optimizá el peso de tus videos sin perder calidad",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # ── Card: archivos ────────────────────────────────────────────────────
        files_card = self._make_card(root_frame)
        files_card.pack(fill="both", expand=True, pady=(0, 12))

        files_header = ttk.Frame(files_card, style="Card.TFrame")
        files_header.pack(fill="x", padx=16, pady=(14, 8))
        self.files_title = ttk.Label(files_header, text="Videos", style="CardH.TLabel")
        self.files_title.pack(side="left")
        ttk.Button(
            files_header, text="+ Archivos", style="CardBtn.TButton",
            command=self.add_files,
        ).pack(side="right", padx=(4, 0))
        ttk.Button(
            files_header, text="+ Carpeta", style="CardBtn.TButton",
            command=self.add_folder,
        ).pack(side="right", padx=(4, 0))
        ttk.Button(
            files_header, text="Limpiar", style="CardBtn.TButton",
            command=self.clear_files,
        ).pack(side="right", padx=(4, 0))

        # Zona lista / empty state
        self.files_body = ttk.Frame(files_card, style="Card.TFrame")
        self.files_body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Empty state
        self.empty_frame = ttk.Frame(self.files_body, style="Card.TFrame")
        ttk.Label(
            self.empty_frame,
            text="📁",
            background=SURFACE, foreground=MUTED,
            font=tkfont.Font(family="Segoe UI", size=32),
        ).pack(pady=(24, 6))
        ttk.Label(
            self.empty_frame,
            text="Agregá videos .mov para empezar",
            style="Card.TLabel",
        ).pack()
        ttk.Label(
            self.empty_frame,
            text="Click en “+ Archivos” o “+ Carpeta”",
            style="CardMuted.TLabel",
        ).pack(pady=(2, 24))

        # Lista
        self.list_frame = ttk.Frame(self.files_body, style="Card.TFrame")
        self.listbox = Listbox(
            self.list_frame,
            selectmode=EXTENDED,
            bg=SURFACE, fg=TEXT,
            selectbackground=ACCENT, selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0,
            activestyle="none",
            font=self.font_body,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<Delete>", lambda e: self.remove_selected())

        # ── Card: opciones ────────────────────────────────────────────────────
        opts_card = self._make_card(root_frame)
        opts_card.pack(fill="x", pady=(0, 12))

        opts = ttk.Frame(opts_card, style="Card.TFrame")
        opts.pack(fill="x", padx=16, pady=14)

        # Destino
        dest_row = ttk.Frame(opts, style="Card.TFrame")
        dest_row.pack(fill="x")
        ttk.Label(dest_row, text="Destino", style="CardH.TLabel", width=14).pack(side="left")
        self.dest_var = StringVar(value="Misma carpeta que el origen")
        ttk.Label(
            dest_row, textvariable=self.dest_var,
            style="CardMuted.TLabel",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            dest_row, text="Cambiar", style="CardBtn.TButton",
            command=self.choose_dest,
        ).pack(side="right", padx=(4, 0))
        ttk.Button(
            dest_row, text="Origen", style="CardBtn.TButton",
            command=self.reset_dest,
        ).pack(side="right", padx=(4, 0))

        # Separador
        ttk.Frame(opts, style="Card.TFrame", height=12).pack(fill="x")

        # Modo (segmented)
        mode_row = ttk.Frame(opts, style="Card.TFrame")
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Procesar en", style="CardH.TLabel", width=14).pack(side="left")

        seg = ttk.Frame(mode_row, style="Card.TFrame")
        seg.pack(side="left")
        ttk.Radiobutton(
            seg, text="Local", style="Seg.TRadiobutton",
            variable=self.use_cloud, value=False,
            command=self._on_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            seg, text="Nube", style="Seg.TRadiobutton",
            variable=self.use_cloud, value=True,
            command=self._on_mode_change,
        ).pack(side="left")

        self.mode_hint = ttk.Label(mode_row, text="", style="CardMuted.TLabel")
        self.mode_hint.pack(side="left", padx=(12, 0))
        self._on_mode_change()

        # ── Progress ──────────────────────────────────────────────────────────
        prog_frame = ttk.Frame(root_frame, style="App.TFrame")
        prog_frame.pack(fill="x", pady=(0, 12))
        self.status_var = StringVar(value="Listo para convertir")
        ttk.Label(prog_frame, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(0, 4))
        self.progress = ttk.Progressbar(
            prog_frame, style="Primary.Horizontal.TProgressbar",
            mode="determinate",
        )
        self.progress.pack(fill="x")

        # ── Actions ───────────────────────────────────────────────────────────
        actions = ttk.Frame(root_frame, style="App.TFrame")
        actions.pack(fill="x", pady=(0, 8))

        self.toggle_log_btn = ttk.Button(
            actions, text="▸ Detalles", style="Link.TButton",
            command=self._toggle_log,
        )
        self.toggle_log_btn.pack(side="left")
        ttk.Button(
            actions, text="Ver logs", style="Link.TButton",
            command=self.open_logs_folder,
        ).pack(side="left", padx=(14, 0))

        self.start_btn = ttk.Button(
            actions, text="Convertir", style="Primary.TButton",
            command=self.start,
        )
        self.start_btn.pack(side="right")

        self.cancel_btn = ttk.Button(
            actions, text="Cancelar", style="Ghost.TButton",
            command=self.cancel, state="disabled",
        )
        self.cancel_btn.pack(side="right", padx=(0, 8))

        # ── Log (colapsable) ──────────────────────────────────────────────────
        self.log_frame = ttk.Frame(root_frame, style="App.TFrame")
        self.log = Text(
            self.log_frame,
            height=7, wrap="word",
            bg=SURFACE, fg=TEXT,
            borderwidth=1, relief="solid",
            highlightthickness=0,
            font=self.font_mono,
            padx=10, pady=8,
        )
        self.log.pack(fill="both", expand=True)

    def _make_card(self, parent) -> ttk.Frame:
        # Frame con "borde" simulado
        outer = ttk.Frame(parent, style="Card.TFrame")
        return outer

    # ── Empty state logic ─────────────────────────────────────────────────────

    def _refresh_file_view(self) -> None:
        count = len(self.files)
        self.files_title.config(
            text="Videos" if count == 0 else f"Videos ({count})"
        )
        if count == 0:
            self.list_frame.pack_forget()
            self.empty_frame.pack(fill="both", expand=True)
        else:
            self.empty_frame.pack_forget()
            self.list_frame.pack(fill="both", expand=True)

    def _on_mode_change(self) -> None:
        if self.use_cloud.get():
            self.mode_hint.config(text="los archivos se suben y procesan en Modal")
        else:
            self.mode_hint.config(text="usa el CPU de esta PC")

    def _toggle_log(self) -> None:
        if self.log_visible.get():
            self.log_frame.pack_forget()
            self.toggle_log_btn.config(text="▸ Detalles")
            self.log_visible.set(False)
        else:
            self.log_frame.pack(fill="both", expand=True, pady=(8, 0))
            self.toggle_log_btn.config(text="▾ Detalles")
            self.log_visible.set(True)

    # ── File management ───────────────────────────────────────────────────────

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Elegir .mov",
            filetypes=[("Videos MOV", "*.mov *.MOV"), ("Todos", "*.*")],
        )
        for p in paths:
            self._add_path(Path(p))
        self._refresh_file_view()

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Elegir carpeta con .mov")
        if not folder:
            return
        for p in sorted(Path(folder).rglob("*")):
            if p.suffix.lower() == ".mov":
                self._add_path(p)
        self._refresh_file_view()

    def _add_path(self, p: Path) -> None:
        if p in self.files or p.suffix.lower() != ".mov":
            return
        self.files.append(p)
        self.listbox.insert(END, f"  {p.name}   · {p.parent}")

    def remove_selected(self) -> None:
        sel = list(self.listbox.curselection())
        for idx in reversed(sel):
            self.listbox.delete(idx)
            del self.files[idx]
        self._refresh_file_view()

    def clear_files(self) -> None:
        self.files.clear()
        self.listbox.delete(0, END)
        self._refresh_file_view()

    def choose_dest(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta de destino")
        if folder:
            self.dest_dir = Path(folder)
            self.dest_var.set(str(self.dest_dir))

    def reset_dest(self) -> None:
        self.dest_dir = None
        self.dest_var.set("Misma carpeta que el origen")

    def open_logs_folder(self) -> None:
        import os
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        os.startfile(str(logs_dir))

    def append_log(self, text: str) -> None:
        self.log.insert(END, text + "\n")
        self.log.see(END)
        self._logger.info(text)

    # ── Start / cancel ────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.files:
            messagebox.showwarning("Nada para convertir", "Agrega videos primero.")
            return

        cloud = self.use_cloud.get()
        if not cloud:
            try:
                check_ffmpeg()
            except SystemExit as e:
                if messagebox.askyesno(
                    "ffmpeg no encontrado",
                    f"{e}\n\n¿Queres que lo instale ahora?",
                ):
                    self._install_ffmpeg()
                return

        self.cancel_flag.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress.config(maximum=max(len(self.files), 1), value=0)
        self.log.delete("1.0", END)

        files = list(self.files)
        dest = self.dest_dir
        target = self._run_all_cloud if cloud else self._run_all_local
        self.worker = threading.Thread(target=target, args=(files, dest), daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        self.cancel_flag.set()
        self.status_var.set("Cancelando...")

    def _install_ffmpeg(self) -> None:
        self.status_var.set("Instalando ffmpeg...")

        def run():
            try:
                subprocess.run(
                    ["winget", "install", "--id", "Gyan.FFmpeg", "--source", "winget",
                     "--accept-package-agreements", "--accept-source-agreements"],
                    check=True,
                )
                self._emit("log", "ffmpeg instalado. Cerra y volvé a abrir la app.")
                self._emit("status", "ffmpeg instalado. Reinicia la app.")
            except Exception as e:
                self._emit("log", f"Error instalando ffmpeg: {e}")

        threading.Thread(target=run, daemon=True).start()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _emit(self, kind: str, payload) -> None:
        self.msg_queue.put((kind, payload))

    def _finish(self) -> None:
        self._emit("done", None)

    # ── Local processing ──────────────────────────────────────────────────────

    def _run_all_local(self, files: list[Path], dest: Path | None) -> None:
        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._emit("log", "Cancelado.")
                break
            self._emit("status", f"[{i}/{len(files)}]  {src.name}")
            self._emit("log", f"[{i}/{len(files)}] {src.name}")
            try:
                self._run_one_local(src, dest)
            except subprocess.CalledProcessError as e:
                self._emit("log", f"  ERROR ffmpeg exit {e.returncode}")
            except Exception as e:
                self._emit("log", f"  ERROR: {e}")
            self._emit("overall", i)
        self._finish()

    def _run_one_local(self, src: Path, dest: Path | None) -> None:
        out_dir = dest if dest else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / (src.stem + ".mp4")
        if dst.exists() and dst.resolve() != src.resolve():
            self._emit("log", f"  [SKIP] ya existe: {dst}")
            return

        info = probe_full(src)
        map_args, codec_args, vstrat, astrat = build_args(info["streams"])

        self._emit("log", f"  {vstrat}")
        self._emit("log", f"  {astrat}")

        cmd = build_ffmpeg_cmd(src, dst, map_args, codec_args)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            if self.cancel_flag.is_set():
                proc.terminate()
                break

        proc.wait()
        if self.cancel_flag.is_set():
            dst.unlink(missing_ok=True)
            return
        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            self._emit("log", f"  ffmpeg stderr: {stderr.strip()[:500]}")
            raise subprocess.CalledProcessError(proc.returncode, cmd)

        src_size = src.stat().st_size
        dst_size = dst.stat().st_size
        ratio = (1 - dst_size / src_size) * 100
        self._emit("log", f"  {human_size(src_size)} → {human_size(dst_size)} ({ratio:+.1f}%)")

    # ── Cloud processing ──────────────────────────────────────────────────────

    def _run_all_cloud(self, files: list[Path], dest: Path | None) -> None:
        try:
            modal = _load_modal()
        except Exception as e:
            self._emit("log", f"ERROR cargando Modal: {e}")
            self._finish()
            return

        try:
            convert_fn = modal.Function.lookup("mov-to-mp4-converter", "convert")
        except Exception as e:
            self._emit("log", f"ERROR conectando con Modal: {e}")
            self._finish()
            return

        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._emit("log", "Cancelado.")
                break
            self._emit("status", f"[{i}/{len(files)}]  {src.name}  · nube")
            self._emit("log", f"[{i}/{len(files)}] {src.name}")
            try:
                self._run_one_cloud(src, dest, convert_fn)
            except Exception as e:
                self._emit("log", f"  ERROR: {e}")
            self._emit("overall", i)
        self._finish()

    def _run_one_cloud(self, src: Path, dest, convert_fn) -> None:
        out_dir = dest if dest else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / (src.stem + ".mp4")
        if dst.exists():
            self._emit("log", f"  [SKIP] ya existe: {dst}")
            return

        src_size = src.stat().st_size
        self._emit("log", f"  Subiendo {human_size(src_size)}...")
        video_bytes = src.read_bytes()

        self._emit("log", "  Procesando en nube...")
        result_bytes, stats = convert_fn.remote(video_bytes, src.name)

        self._emit("log", "  Descargando resultado...")
        dst.write_bytes(result_bytes)

        ratio = stats["ratio"]
        self._emit(
            "log",
            f"  {human_size(stats['src_size'])} → {human_size(stats['dst_size'])} ({ratio:+.1f}%)",
        )

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "overall":
                    self.progress.config(value=payload)
                elif kind == "done":
                    self.status_var.set("✓ Listo")
                    self.start_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)


def main() -> None:
    root = Tk()
    ConverterUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
