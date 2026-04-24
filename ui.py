#!/usr/bin/env python3
"""UI simple (Tkinter) para el converter MOV -> MP4. Soporta modo local y nube (Modal)."""

from __future__ import annotations

import datetime
import logging
import queue
import subprocess
import threading
from pathlib import Path
from tkinter import (
    Tk, StringVar, BooleanVar, END, filedialog, messagebox, ttk, Listbox, Text, SINGLE,
)

from convert import (
    build_args,
    build_ffmpeg_cmd,
    check_ffmpeg,
    duration_seconds,
    human_size,
    probe_full,
)


def _load_modal():
    """Importa modal e inyecta credenciales desde .env si existen."""
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
        root.title("MOV -> MP4 converter")
        root.geometry("720x580")

        self.files: list[Path] = []
        self.dest_dir: Path | None = None
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.use_cloud = BooleanVar(value=False)
        self._logger = self._setup_logger()

        self._build()
        self._poll_queue()

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

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Agregar archivos...", command=self.add_files).pack(side="left")
        ttk.Button(top, text="Agregar carpeta...", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(top, text="Quitar seleccionado", command=self.remove_selected).pack(side="left")
        ttk.Button(top, text="Limpiar", command=self.clear_files).pack(side="left", padx=4)

        list_frame = ttk.LabelFrame(self.root, text="Archivos a convertir")
        list_frame.pack(fill="both", expand=True, **pad)
        self.listbox = Listbox(list_frame, selectmode=SINGLE)
        self.listbox.pack(fill="both", expand=True, padx=4, pady=4)

        dest = ttk.Frame(self.root)
        dest.pack(fill="x", **pad)
        ttk.Label(dest, text="Destino:").pack(side="left")
        self.dest_var = StringVar(value="(misma carpeta que el origen)")
        ttk.Label(dest, textvariable=self.dest_var, foreground="#444").pack(side="left", padx=6)
        ttk.Button(dest, text="Elegir...", command=self.choose_dest).pack(side="right")
        ttk.Button(dest, text="Usar origen", command=self.reset_dest).pack(side="right", padx=4)

        # Toggle local / nube
        mode_frame = ttk.Frame(self.root)
        mode_frame.pack(fill="x", padx=8, pady=2)
        ttk.Label(mode_frame, text="Procesamiento:").pack(side="left")
        ttk.Radiobutton(
            mode_frame, text="Local (tu PC)",
            variable=self.use_cloud, value=False,
            command=self._on_mode_change,
        ).pack(side="left", padx=8)
        ttk.Radiobutton(
            mode_frame, text="Nube (Modal) — mas rapido, no usa tu CPU",
            variable=self.use_cloud, value=True,
            command=self._on_mode_change,
        ).pack(side="left")
        self.mode_label = ttk.Label(mode_frame, text="", foreground="#888")
        self.mode_label.pack(side="left", padx=8)

        progress = ttk.Frame(self.root)
        progress.pack(fill="x", **pad)
        self.status_var = StringVar(value="Listo.")
        ttk.Label(progress, textvariable=self.status_var).pack(anchor="w")
        self.overall = ttk.Progressbar(progress, mode="determinate")
        self.overall.pack(fill="x", pady=2)
        self.current = ttk.Progressbar(progress, mode="determinate")
        self.current.pack(fill="x", pady=2)

        log_frame = ttk.LabelFrame(self.root, text="Log  —  guardado en logs/")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = Text(log_frame, height=8, wrap="word")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.start_btn = ttk.Button(actions, text="Convertir", command=self.start)
        self.start_btn.pack(side="right")
        self.cancel_btn = ttk.Button(actions, text="Cancelar", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=4)
        ttk.Button(actions, text="Ver logs", command=self.open_logs_folder).pack(side="left")

    def _on_mode_change(self) -> None:
        if self.use_cloud.get():
            self.mode_label.config(text="Los archivos se suben a Modal, se procesan en nube y se descargan automaticamente.")
        else:
            self.mode_label.config(text="")

    # ── File management ────────────────────────────────────────────────────────

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Elegir .mov",
            filetypes=[("Videos MOV", "*.mov *.MOV"), ("Todos", "*.*")],
        )
        for p in paths:
            self._add_path(Path(p))

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Elegir carpeta con .mov")
        if not folder:
            return
        for p in sorted(Path(folder).rglob("*")):
            if p.suffix.lower() == ".mov":
                self._add_path(p)

    def _add_path(self, p: Path) -> None:
        if p in self.files or p.suffix.lower() != ".mov":
            return
        self.files.append(p)
        self.listbox.insert(END, str(p))

    def remove_selected(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.listbox.delete(idx)
        del self.files[idx]

    def clear_files(self) -> None:
        self.files.clear()
        self.listbox.delete(0, END)

    def choose_dest(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta de destino")
        if folder:
            self.dest_dir = Path(folder)
            self.dest_var.set(str(self.dest_dir))

    def reset_dest(self) -> None:
        self.dest_dir = None
        self.dest_var.set("(misma carpeta que el origen)")

    def open_logs_folder(self) -> None:
        import os
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        os.startfile(str(logs_dir))

    def append_log(self, text: str) -> None:
        self.log.insert(END, text + "\n")
        self.log.see(END)
        self._logger.info(text)

    # ── Start / cancel ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.files:
            messagebox.showwarning("Nada para convertir", "Agrega archivos primero.")
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
        self.overall.config(maximum=len(self.files), value=0)
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

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _emit(self, kind: str, payload) -> None:
        self.msg_queue.put((kind, payload))

    def _finish(self) -> None:
        self._emit("done", None)

    # ── Local processing ───────────────────────────────────────────────────────

    def _run_all_local(self, files: list[Path], dest: Path | None) -> None:
        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._emit("log", "Cancelado.")
                break
            self._emit("overall", i - 1)
            self._emit("status", f"[{i}/{len(files)}] {src.name}")
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
        total = duration_seconds(info)

        self._emit("log", f"  {vstrat}")
        self._emit("log", f"  {astrat}")
        self._emit("current_max", max(total, 0.01))
        self._emit("current", 0)

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
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    self._emit("current", int(line.split("=", 1)[1]) / 1_000_000)
                except ValueError:
                    pass
            elif line == "progress=end":
                self._emit("current", total)

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
        self._emit("log", f"  {human_size(src_size)} -> {human_size(dst_size)} ({ratio:+.1f}%)")

    # ── Cloud processing ───────────────────────────────────────────────────────

    def _run_all_cloud(self, files: list[Path], dest: Path | None) -> None:
        try:
            modal = _load_modal()
        except Exception as e:
            self._emit("log", f"ERROR cargando Modal: {e}")
            self._emit("log", "Instala con:  pip install modal")
            self._finish()
            return

        try:
            convert_fn = modal.Function.lookup("mov-to-mp4-converter", "convert")
        except Exception as e:
            self._emit("log", f"ERROR conectando con Modal: {e}")
            self._emit("log", "Asegurate de haber deployado: python -m modal deploy modal_worker.py")
            self._finish()
            return

        for i, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._emit("log", "Cancelado.")
                break
            self._emit("overall", i - 1)
            self._emit("status", f"[{i}/{len(files)}] {src.name}  (nube)")
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
        self._emit("current_max", 3)
        self._emit("current", 1)

        video_bytes = src.read_bytes()

        self._emit("log", "  Procesando en nube (Modal)...")
        self._emit("current", 2)

        result_bytes, stats = convert_fn.remote(video_bytes, src.name)

        self._emit("log", "  Descargando resultado...")
        dst.write_bytes(result_bytes)
        self._emit("current", 3)

        ratio = stats["ratio"]
        self._emit(
            "log",
            f"  {human_size(stats['src_size'])} -> {human_size(stats['dst_size'])} ({ratio:+.1f}%)",
        )

    # ── Queue polling ──────────────────────────────────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "overall":
                    self.overall.config(value=payload)
                elif kind == "current_max":
                    self.current.config(maximum=payload, value=0)
                elif kind == "current":
                    self.current.config(value=payload)
                elif kind == "done":
                    self.status_var.set("Listo.")
                    self.start_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
                    self.current.config(value=0)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)


def main() -> None:
    root = Tk()
    ConverterUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
