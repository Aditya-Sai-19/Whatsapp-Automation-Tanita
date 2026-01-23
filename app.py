from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from csv_loader import InvalidPhoneNumberError as CsvInvalidPhoneNumberError, load_clients_csv
from pdf_finder import PdfAmbiguousMatchError, PdfFinder, PdfNotFoundError
from whatsapp_bot import (
    InvalidPhoneNumberError as BotInvalidPhoneNumberError,
    WhatsAppBot,
    WhatsAppNotReadyError,
    WhatsAppSendError,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("WhatsApp PDF Sender")
        self.geometry("900x600")

        base_dir = Path(__file__).resolve().parent
        self.default_csv = base_dir / "data" / "clients.csv"
        self.default_reports_dir = base_dir / "reports"
        self.default_profile_dir = base_dir / "browser_profile"

        self._ui_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._worker_thread: threading.Thread | None = None

        self._build_ui()
        self.after(100, self._poll_ui_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        paths = ttk.LabelFrame(root, text="Inputs", padding=12)
        paths.pack(fill=tk.X)

        self.csv_path_var = tk.StringVar(value=str(self.default_csv))
        self.reports_dir_var = tk.StringVar(value=str(self.default_reports_dir))
        self.profile_dir_var = tk.StringVar(value=str(self.default_profile_dir))

        self._row_path_picker(paths, 0, "CSV file", self.csv_path_var, is_file=True)
        self._row_path_picker(paths, 1, "Reports folder", self.reports_dir_var, is_file=False)
        self._row_path_picker(paths, 2, "Browser profile folder", self.profile_dir_var, is_file=False)

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(12, 0))

        self.start_btn = ttk.Button(controls, text="Start Sending", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT)

        self.progress_label = ttk.Label(controls, text="Idle")
        self.progress_label.pack(side=tk.LEFT, padx=(12, 0))

        self.progress = ttk.Progressbar(controls, mode="determinate", length=300)
        self.progress.pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(root, text="Logs", padding=12)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_frame, height=20, wrap="word", state="disabled")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _row_path_picker(
        self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, *, is_file: bool
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        parent.columnconfigure(1, weight=1)

        def browse() -> None:
            if is_file:
                path = filedialog.askopenfilename(
                    title=f"Select {label}",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                )
            else:
                path = filedialog.askdirectory(title=f"Select {label}")

            if path:
                var.set(path)

        ttk.Button(parent, text="Browse", command=browse).grid(row=row, column=2, padx=(8, 0), pady=6)

    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state=("disabled" if running else "normal"))

    def _on_start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showwarning("Busy", "A run is already in progress.")
            return

        csv_path = Path(self.csv_path_var.get()).expanduser()
        reports_dir = Path(self.reports_dir_var.get()).expanduser()
        profile_dir = Path(self.profile_dir_var.get()).expanduser()

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.progress_label.configure(text="Starting…")

        self._set_running(True)

        self._worker_thread = threading.Thread(
            target=self._run_job,
            args=(csv_path, reports_dir, profile_dir),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_job(self, csv_path: Path, reports_dir: Path, profile_dir: Path) -> None:
        def qlog(s: str) -> None:
            self._ui_queue.put(("log", s))

        try:
            qlog(f"Loading CSV: {csv_path}")
            clients = load_clients_csv(csv_path)

            qlog(f"Indexing PDFs in: {reports_dir}")
            finder = PdfFinder(reports_dir)

            bot = WhatsAppBot(profile_dir, headless=False)
            bot.start(log=qlog)

            try:
                total = len(clients)
                self._ui_queue.put(("progress_init", total))

                for i, c in enumerate(clients, start=1):
                    self._ui_queue.put(("progress", (i - 1, total, f"{i}/{total} Preparing {c.client_name}")))

                    match = finder.find_pdf_for_client(c.client_name)
                    qlog(f"Sending to {c.client_name} ({c.mobile_number_raw}) -> {match.pdf_path.name}")

                    bot.send_pdf_to_phone(
                        phone_digits=c.mobile_number_e164_digits,
                        pdf_path=match.pdf_path,
                        log=qlog,
                    )

                    self._ui_queue.put(("progress", (i, total, f"{i}/{total} Sent to {c.client_name}")))

                self._ui_queue.put(("done", "All PDFs sent."))

            finally:
                bot.close()

        except (PdfNotFoundError, PdfAmbiguousMatchError, FileNotFoundError) as e:
            self._ui_queue.put(("error", str(e)))
        except (CsvInvalidPhoneNumberError, BotInvalidPhoneNumberError) as e:
            self._ui_queue.put(("error", str(e)))
        except (WhatsAppNotReadyError, WhatsAppSendError) as e:
            self._ui_queue.put(("error", str(e)))
        except Exception:
            self._ui_queue.put(("error", traceback.format_exc()))

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()

                if kind == "log":
                    self._log(str(payload))

                elif kind == "progress_init":
                    total = int(payload)
                    self.progress["maximum"] = total
                    self.progress["value"] = 0

                elif kind == "progress":
                    current, total, label = payload  # type: ignore[misc]
                    self.progress["maximum"] = total
                    self.progress["value"] = current
                    self.progress_label.configure(text=str(label))

                elif kind == "done":
                    self._log(str(payload))
                    self.progress_label.configure(text=str(payload))
                    self._set_running(False)

                elif kind == "error":
                    self._log(str(payload))
                    self.progress_label.configure(text="Error")
                    self._set_running(False)
                    messagebox.showerror("Error", str(payload))

        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_ui_queue)


if __name__ == "__main__":
    App().mainloop()
