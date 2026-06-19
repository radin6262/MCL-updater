import sys
import os
import time
import subprocess
import argparse
import datetime
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont


def write_log(message):
    """Write a timestamped message to ud.log in the current working directory."""
    log_path = Path(os.getcwd()) / "ud.log"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


class UpdateWorker(QThread):
    """Performs the actual update work in a background thread."""
    status_signal = Signal(str)
    detail_signal = Signal(str)
    progress_signal = Signal(int)
    indeterminate_signal = Signal(bool)
    finished_signal = Signal()

    def __init__(self, current_exe, update_exe):
        super().__init__()
        self.current_exe = current_exe
        self.update_exe = update_exe
        self.name = os.path.basename(current_exe)

    def run(self):
        try:
            self.do_update()
        except Exception as e:
            write_log(f"Update failed with exception: {str(e)}")
            self.status_signal.emit(f"Update failed: {str(e)}")
            self.detail_signal.emit("Check ud.log for details")
            time.sleep(4)
        finally:
            self.finished_signal.emit()

    def do_update(self):
        name = self.name

        # ------------------------------------------------------------
        # Phase 1 – Wait for the main launcher to close
        # ------------------------------------------------------------
        self.indeterminate_signal.emit(True)
        self.status_signal.emit("Waiting for launcher to close...")
        self.detail_signal.emit(
            f"Closing {name}. If it doesn't close automatically, please close it manually."
        )
        write_log(f"Waiting for {name} to exit...")

        wait_count = 0
        while True:
            try:
                result = subprocess.run(
                    ['tasklist', '/FI', f'IMAGENAME eq {name}'],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )
                if name.lower() not in result.stdout.lower():
                    write_log(f"Process {name} exited after {wait_count * 0.5:.1f}s")
                    break
            except subprocess.TimeoutExpired:
                pass  # tasklist timed out, retry
            wait_count += 1
            if wait_count % 10 == 0:  # every 5 seconds
                write_log(f"Still waiting for {name}... ({wait_count * 0.5:.0f}s)")
                self.status_signal.emit(f"Waiting... ({wait_count * 0.5:.0f}s)")
            time.sleep(0.5)

        # Small delay to ensure file handles are released
        self.status_signal.emit("Finalizing...")
        self.detail_signal.emit("Releasing file handles")
        time.sleep(1)

        # ------------------------------------------------------------
        # Phase 2 – Copy the update file with live progress
        # ------------------------------------------------------------
        self.indeterminate_signal.emit(False)
        self.status_signal.emit("Copying update...")
        self.progress_signal.emit(0)

        update_size = os.path.getsize(self.update_exe)
        write_log(f"Update size: {update_size} bytes ({update_size / 1024 / 1024:.1f} MB)")

        temp_path = self.current_exe + ".new"
        total_copied = 0

        try:
            with open(self.update_exe, 'rb') as fsrc:
                with open(temp_path, 'wb') as fdst:
                    while True:
                        chunk = fsrc.read(65536)  # 64 KB
                        if not chunk:
                            break
                        fdst.write(chunk)
                        total_copied += len(chunk)

                        progress = int((total_copied / update_size) * 100)
                        self.progress_signal.emit(progress)

                        mb_done = total_copied / (1024 * 1024)
                        mb_total = update_size / (1024 * 1024)
                        self.detail_signal.emit(f"{mb_done:.1f} MB / {mb_total:.1f} MB")

            # Preserve file metadata
            shutil.copystat(self.update_exe, temp_path)

            # Atomic replace
            self.status_signal.emit("Applying update...")
            self.detail_signal.emit("")
            self.indeterminate_signal.emit(True)
            os.replace(temp_path, self.current_exe)

            write_log(f"Successfully replaced {self.current_exe}")

        except Exception as e:
            write_log(f"Copy/replace failed: {str(e)}")
            self.status_signal.emit(f"Error: {str(e)}")
            self.detail_signal.emit("Update FAILED – check ud.log")
            time.sleep(3)
            return

        # ------------------------------------------------------------
        # Phase 3 – Launch the updated launcher
        # ------------------------------------------------------------
        self.status_signal.emit("Starting updated launcher...")
        self.detail_signal.emit("")

        try:
            subprocess.Popen([self.current_exe],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            write_log(f"Launched new executable: {self.current_exe}")
        except Exception as e:
            write_log(f"Failed to launch: {str(e)}")
            self.status_signal.emit(f"Launch failed: {str(e)}")
            time.sleep(2)
            return

        self.status_signal.emit("Update complete!")
        write_log("Update complete – updater exiting")
        write_log("-" * 50)
        time.sleep(1)


class UpdaterWindow(QWidget):
    def __init__(self, current_exe, update_exe):
        super().__init__()
        self.current_exe = current_exe
        self.update_exe = update_exe
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Minecraft Launcher Updater")
        self.setFixedSize(480, 160)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        self.status_label = QLabel("Initializing update...")
        self.status_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(30)
        layout.addWidget(self.progress_bar)

        self.detail_label = QLabel("")
        self.detail_label.setFont(QFont("Segoe UI", 9))
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(self.detail_label)

        self.setLayout(layout)

        # Dark green theme
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a2e;
                color: #ffffff;
            }
            QProgressBar {
                border: 2px solid #00a86b;
                border-radius: 8px;
                background-color: #16213e;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00a86b;
                border-radius: 6px;
            }
        """)

    def start_update(self):
        """Start the background worker thread."""
        self.worker = UpdateWorker(self.current_exe, self.update_exe)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.detail_signal.connect(self.detail_label.setText)
        self.worker.progress_signal.connect(self.set_progress)
        self.worker.indeterminate_signal.connect(self.set_indeterminate)
        self.worker.finished_signal.connect(self.close)
        self.worker.start()

    def set_progress(self, value):
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(value)
        self.progress_bar.setTextVisible(True)
        QApplication.processEvents()

    def set_indeterminate(self, active):
        if active:
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(0)
            self.progress_bar.setTextVisible(False)
        else:
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setTextVisible(True)
            self.progress_bar.setValue(0)
        QApplication.processEvents()


def main():
    parser = argparse.ArgumentParser(description='MCL Updater Helper')
    parser.add_argument('--current', required=True,
                        help='Path to the current executable')
    parser.add_argument('--update', required=True,
                        help='Path to the downloaded update file')
    args = parser.parse_args()

    current_exe = os.path.abspath(args.current)
    update_exe = os.path.abspath(args.update)

    write_log("Updater started")
    write_log(f"Current executable: {current_exe}")
    write_log(f"Update file: {update_exe}")
    write_log(f"Current exists: {os.path.exists(current_exe)}")
    write_log(f"Update exists: {os.path.exists(update_exe)}")

    app = QApplication(sys.argv)
    window = UpdaterWindow(current_exe, update_exe)
    window.show()
    window.start_update()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
