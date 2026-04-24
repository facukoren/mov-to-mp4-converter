#!/usr/bin/env python3
"""UI para el converter MOV -> MP4. Modo local y nube (Modal)."""

from __future__ import annotations

import datetime
import logging
import platform
import queue
import subprocess
import sys
import threading
import time
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

        logger = logging.getLogger(f"converter_{stamp}")
        logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s.%(msecs)03d  %(levelname)-5s  %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)

        # Cabecera con info de entorno
        logger.info("=" * 70)
        logger.info("NUEVA SESION")
        logger.info("=" * 70)
        logger.info(f"fecha        {datetime.datetime.now().isoformat(timespec='seconds')}")
        logger.info(f"OS           {platform.system()} {platform.release()} ({platform.machine()})")
        logger.info(f"python       {sys.version.split()[0]}")
        try:
            ff = subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, text=True, timeout=3,
            )
            first_line = ff.stdout.splitlines()[0] if ff.stdout else "no disponible"
            logger.info(f"ffmpeg       {first_line}")
        except Exception:
            logger.info("ffmpeg       no disponible")
        try:
            import modal as _m
            logger.info(f"modal sdk    {_m.__version__}")
        except Exception:
            logger.info("modal sdk    no instalado")
        logger.info("-" * 70)

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
        log_container = ttk.Frame(self.log_frame, style="App.TFrame")
        log_container.pack(fill="both", expand=True)
        self.log = Text(
            log_container,
            height=10, wrap="word",
            bg=SURFACE, fg=TEXT,
            borderwidth=1, relief="solid",
            highlightthickness=0,
            font=self.font_mono,
            padx=10, pady=8,
        )
        log_sb = ttk.Scrollbar(log_container, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        # Tags de color por nivel
        self._log_tags = {"info", "debug", "warn", "error", "success", "header", "step", "metric"}
        self.log.tag_configure("debug",   foreground="#8e8e93")
        self.log.tag_configure("warn",    foreground="#ff9500")
        self.log.tag_configure("error",   foreground=DANGER,    font=self.font_mono)
        self.log.tag_configure("success", foreground=SUCCESS)
        self.log.tag_configure("header",  foreground=ACCENT,    font=(self.font_mono.actual("family"), 9, "bold"))
        self.log.tag_configure("step",    foreground=TEXT)
        self.log.tag_configure("metric",  foreground=MUTED)

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

    # ── Logging ───────────────────────────────────────────────────────────────

    def append_log(self, entry) -> None:
        """entry puede ser str (info plano) o tupla (level, text)."""
        if isinstance(entry, tuple):
            level, text = entry
        else:
            level, text = "info", entry

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "  ",
            "debug": "  ",
            "warn": "⚠ ",
            "error": "✕ ",
            "success": "✓ ",
            "header": "▸ ",
            "step": "→ ",
            "metric": "· ",
        }.get(level, "  ")

        line = f"[{ts}]  {prefix}{text}\n"
        start = self.log.index(END)
        self.log.insert(END, line)
        end = self.log.index(END)
        if level in self._log_tags:
            self.log.tag_add(level, start, end)
        self.log.see(END)

        log_level = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
            "debug": logging.DEBUG,
        }.get(level, logging.INFO)
        self._logger.log(log_level, text)

    def _log(self, level: str, msg: str) -> None:
        """Shortcut para emitir desde threads — solo info al archivo si no esta el Text."""
        self._emit("log", (level, msg))

    # ── Log helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_duration(sec: float) -> str:
        sec = max(sec, 0)
        if sec < 60:
            return f"{sec:.1f}s"
        m, s = divmod(int(sec), 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m {s:02d}s"

    def _log_source_metadata(self, info: dict, src_size: int) -> None:
        streams = info.get("streams", [])
        fmt = info.get("format", {})
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        dur = float(fmt.get("duration", 0) or 0)
        bitrate = int(fmt.get("bit_rate", 0) or 0)

        self._log("metric", f"archivo:   {human_size(src_size)}  ·  {self._fmt_duration(dur)}  ·  {bitrate/1_000_000:.1f} Mbps")

        if video:
            w = video.get("width", "?")
            h = video.get("height", "?")
            fps_raw = video.get("r_frame_rate", "0/1")
            try:
                n, d = fps_raw.split("/")
                fps = float(n) / float(d) if float(d) else 0
            except Exception:
                fps = 0
            codec = video.get("codec_name", "?")
            pix = video.get("pix_fmt", "?")
            trc = video.get("color_transfer", "") or "?"
            prim = video.get("color_primaries", "") or "?"
            rng = video.get("color_range", "") or "?"
            is_hdr = trc.lower() in {"arib-std-b67", "smpte2084"}
            hdr_tag = "HDR" if is_hdr else "SDR"

            self._log("metric", f"video:     {codec}  {w}×{h}  {fps:.2f} fps  {pix}")
            self._log("metric", f"color:     {hdr_tag}  primaries={prim}  transfer={trc}  range={rng}")

        if audio:
            codec = audio.get("codec_name", "?")
            sr = audio.get("sample_rate", "?")
            ch = audio.get("channels", "?")
            abr = int(audio.get("bit_rate", 0) or 0)
            if abr:
                self._log("metric", f"audio:     {codec}  {sr} Hz  {ch}ch  {abr/1000:.0f} kbps")
            else:
                self._log("metric", f"audio:     {codec}  {sr} Hz  {ch}ch")

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

        # Auto-expandir log al iniciar conversion (si esta colapsado)
        if not self.log_visible.get():
            self._toggle_log()

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
        session_start = time.monotonic()
        total_src = 0
        total_dst = 0
        ok, failed = 0, 0

        self._log("header", f"Sesion local · {len(files)} archivo(s)")
        self._log("debug",  f"destino: {dest or '(junto al origen)'}")

        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._log("warn", "Sesion cancelada por el usuario")
                break
            self._emit("status", f"[{i}/{len(files)}]  {src.name}")
            self._log("header", f"[{i}/{len(files)}] {src.name}")
            try:
                src_sz, dst_sz = self._run_one_local(src, dest)
                total_src += src_sz
                total_dst += dst_sz
                ok += 1
            except subprocess.CalledProcessError as e:
                failed += 1
                self._log("error", f"ffmpeg exit {e.returncode}")
            except Exception as e:
                failed += 1
                self._log("error", f"{type(e).__name__}: {e}")
            self._emit("overall", i)

        elapsed = time.monotonic() - session_start
        self._log("header", "Resumen de sesion")
        self._log("metric", f"archivos ok:       {ok}")
        if failed:
            self._log("metric", f"archivos fallados: {failed}")
        if total_src:
            saved = total_src - total_dst
            ratio = (1 - total_dst / total_src) * 100
            self._log("metric", f"tamaño total:      {human_size(total_src)} → {human_size(total_dst)}")
            self._log("metric", f"espacio ahorrado:  {human_size(saved)}  ({ratio:+.1f}%)")
        self._log("metric", f"tiempo total:      {self._fmt_duration(elapsed)}")
        self._finish()

    def _run_one_local(self, src: Path, dest: Path | None) -> tuple[int, int]:
        out_dir = dest if dest else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / (src.stem + ".mp4")
        if dst.exists() and dst.resolve() != src.resolve():
            self._log("warn", f"ya existe, se salta: {dst}")
            return 0, 0

        src_size = src.stat().st_size
        info = probe_full(src)
        self._log_source_metadata(info, src_size)

        map_args, codec_args, vstrat, astrat = build_args(info["streams"])
        duration = duration_seconds(info)

        self._log("step", f"video:  {vstrat}")
        self._log("step", f"audio:  {astrat}")

        cmd = build_ffmpeg_cmd(src, dst, map_args, codec_args)
        self._log("debug", "ffmpeg: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))

        started = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

        last_progress_log = 0.0
        last_pct = -10
        assert proc.stdout is not None
        for line in proc.stdout:
            if self.cancel_flag.is_set():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_ms=") and duration > 0:
                try:
                    sec = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                pct = int(sec / duration * 100)
                now = time.monotonic()
                if pct >= last_pct + 10 and now - last_progress_log > 1.0:
                    elapsed = now - started
                    speed = sec / elapsed if elapsed > 0 else 0
                    eta = (duration - sec) / speed if speed > 0 else 0
                    self._log(
                        "debug",
                        f"progreso {pct:>3}%   {speed:.2f}x realtime   ETA {self._fmt_duration(eta)}",
                    )
                    last_pct = pct
                    last_progress_log = now

        proc.wait()
        if self.cancel_flag.is_set():
            dst.unlink(missing_ok=True)
            self._log("warn", "encoding abortado")
            return 0, 0
        if proc.returncode != 0:
            stderr = (proc.stderr.read() if proc.stderr else "").strip()
            for ln in stderr.splitlines()[-8:]:
                self._log("error", f"ffmpeg: {ln}")
            raise subprocess.CalledProcessError(proc.returncode, cmd)

        elapsed = time.monotonic() - started
        dst_size = dst.stat().st_size
        ratio = (1 - dst_size / src_size) * 100
        speed = duration / elapsed if elapsed > 0 else 0

        self._log("success", f"listo: {dst.name}")
        self._log("metric",  f"tamaño:   {human_size(src_size)} → {human_size(dst_size)}  ({ratio:+.1f}%)")
        self._log("metric",  f"tiempo:   {self._fmt_duration(elapsed)}   ({speed:.2f}x realtime)")
        return src_size, dst_size

    # ── Cloud processing ──────────────────────────────────────────────────────

    def _run_all_cloud(self, files: list[Path], dest: Path | None) -> None:
        session_start = time.monotonic()
        total_src = 0
        total_dst = 0
        total_upload = 0.0
        total_process = 0.0
        total_download = 0.0
        ok, failed = 0, 0

        self._log("header", f"Sesion en nube (Modal) · {len(files)} archivo(s)")
        self._log("debug",  f"destino: {dest or '(junto al origen)'}")

        try:
            modal = _load_modal()
        except Exception as e:
            self._log("error", f"cargando Modal: {e}")
            self._log("debug", "solucion: pip install modal")
            self._finish()
            return

        try:
            self._log("step", "conectando con Modal...")
            convert_fn = modal.Function.lookup("mov-to-mp4-converter", "convert")
            self._log("success", "conectado a 'mov-to-mp4-converter.convert'")
        except Exception as e:
            self._log("error", f"conectando con Modal: {e}")
            self._log("debug", "solucion: python -m modal deploy modal_worker.py")
            self._finish()
            return

        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._log("warn", "Sesion cancelada por el usuario")
                break
            self._emit("status", f"[{i}/{len(files)}]  {src.name}  · nube")
            self._log("header", f"[{i}/{len(files)}] {src.name}")
            try:
                result = self._run_one_cloud(src, dest, convert_fn)
                if result:
                    src_sz, dst_sz, t_up, t_proc, t_down = result
                    total_src += src_sz
                    total_dst += dst_sz
                    total_upload += t_up
                    total_process += t_proc
                    total_download += t_down
                    ok += 1
            except Exception as e:
                failed += 1
                self._log("error", f"{type(e).__name__}: {e}")
            self._emit("overall", i)

        elapsed = time.monotonic() - session_start
        self._log("header", "Resumen de sesion")
        self._log("metric", f"archivos ok:       {ok}")
        if failed:
            self._log("metric", f"archivos fallados: {failed}")
        if total_src:
            saved = total_src - total_dst
            ratio = (1 - total_dst / total_src) * 100
            self._log("metric", f"tamaño total:      {human_size(total_src)} → {human_size(total_dst)}")
            self._log("metric", f"espacio ahorrado:  {human_size(saved)}  ({ratio:+.1f}%)")
            self._log("metric", f"subida total:      {self._fmt_duration(total_upload)}")
            self._log("metric", f"proceso total:     {self._fmt_duration(total_process)}")
            self._log("metric", f"bajada total:      {self._fmt_duration(total_download)}")
        self._log("metric", f"tiempo total:      {self._fmt_duration(elapsed)}")
        self._finish()

    def _run_one_cloud(self, src: Path, dest, convert_fn):
        out_dir = dest if dest else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / (src.stem + ".mp4")
        if dst.exists():
            self._log("warn", f"ya existe, se salta: {dst}")
            return None

        src_size = src.stat().st_size

        # Metadata local antes de subir
        try:
            info = probe_full(src)
            self._log_source_metadata(info, src_size)
        except Exception as e:
            self._log("debug", f"no se pudo leer metadata local: {e}")

        # Upload (leer + enviar)
        t0 = time.monotonic()
        self._log("step", f"leyendo {human_size(src_size)} del disco...")
        video_bytes = src.read_bytes()
        read_elapsed = time.monotonic() - t0

        t_up_start = time.monotonic()
        self._log("step", "subiendo + procesando en nube...")
        result_bytes, stats = convert_fn.remote(video_bytes, src.name)
        roundtrip = time.monotonic() - t_up_start

        # No tenemos breakdown exacto upload/proceso del lado server,
        # pero estimamos upload como tiempo minimo de transmisión.
        # El SDK devuelve solo cuando termino todo, asi que roundtrip = upload + proceso + download parcial.

        t_down_start = time.monotonic()
        dst.write_bytes(result_bytes)
        write_elapsed = time.monotonic() - t_down_start

        dst_size = stats["dst_size"]
        ratio = stats["ratio"]

        upload_mbps = (src_size * 8 / 1_000_000) / max(read_elapsed + roundtrip, 0.01)

        self._log("success", f"listo: {dst.name}")
        self._log("metric",  f"tamaño:   {human_size(src_size)} → {human_size(dst_size)}  ({ratio:+.1f}%)")
        self._log("metric",  f"lectura:  {self._fmt_duration(read_elapsed)}")
        self._log("metric",  f"nube:     {self._fmt_duration(roundtrip)}   (~{upload_mbps:.0f} Mbps efectivo)")
        self._log("metric",  f"escritura:{self._fmt_duration(write_elapsed)}")
        return src_size, dst_size, read_elapsed, roundtrip, write_elapsed

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
                    self.progress.config(value=self.progress["maximum"])
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)


def main() -> None:
    root = Tk()
    ConverterUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
