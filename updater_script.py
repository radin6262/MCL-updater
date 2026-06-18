import sys
import os
import time
import subprocess
import argparse
import datetime
import tempfile
from pathlib import Path

def write_log(message):
    """Write a timestamped message to ud.log in the current working directory."""
    log_path = Path(os.getcwd()) / "ud.log"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

def main():
    parser = argparse.ArgumentParser(description='MCL Updater Helper')
    parser.add_argument('--current', required=True, help='Path to the current executable')
    parser.add_argument('--update', required=True, help='Path to the downloaded update file')
    args = parser.parse_args()

    current_exe = os.path.abspath(args.current)
    update_exe = os.path.abspath(args.update)

    # Log start of update process
    write_log("Updater started")
    write_log(f"Current executable (BEFORE): {current_exe}")
    write_log(f"Update file path: {update_exe}")
    write_log(f"Current file size: {os.path.getsize(current_exe) if os.path.exists(current_exe) else 0} bytes")
    write_log(f"Update file size: {os.path.getsize(update_exe) if os.path.exists(update_exe) else 0} bytes")

    # Wait for the main process to exit
    name = os.path.basename(current_exe)
    write_log(f"Waiting for {name} to exit...")

    wait_count = 0
    while True:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {name}'],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if name not in result.stdout:
            write_log(f"Process {name} has exited after {wait_count * 0.5} seconds")
            break
        wait_count += 1
        if wait_count % 10 == 0:  # every 5 seconds
            write_log(f"Still waiting for {name} to exit... ({wait_count * 0.5}s)")
        time.sleep(0.5)

    # Small extra delay to ensure file handles are released
    write_log("Additional 1 second delay for file handle release")
    time.sleep(1)

    # Log before replacement
    write_log(f"Attempting to replace {current_exe}")
    write_log(f"Update file exists: {os.path.exists(update_exe)}")
    write_log(f"Current file exists: {os.path.exists(current_exe)}")

    # Replace the old executable
    try:
        os.replace(update_exe, current_exe)   # atomic replace (Python 3.3+)
        write_log(f"Successfully replaced using os.replace()")
    except Exception as e:
        write_log(f"os.replace() failed: {str(e)}")
        write_log("Attempting fallback copy method")
        try:
            import shutil
            shutil.copy2(update_exe, current_exe)
            os.remove(update_exe)
            write_log(f"Successfully replaced using fallback copy")
        except Exception as e2:
            write_log(f"Fallback copy also failed: {str(e2)}")
            write_log("Update FAILED!")
            sys.exit(1)

    # Log after replacement
    write_log(f"Current executable (AFTER): {current_exe}")
    write_log(f"New file size: {os.path.getsize(current_exe) if os.path.exists(current_exe) else 0} bytes")
    write_log(f"Update file deleted: {not os.path.exists(update_exe)}")

    # Launch the new launcher
    write_log(f"Launching new executable: {current_exe}")
    try:
        subprocess.Popen([current_exe], creationflags=subprocess.CREATE_NO_WINDOW)
        write_log(f"Successfully launched new process")
    except Exception as e:
        write_log(f"Failed to launch new process: {str(e)}")

    write_log("Updater exiting")
    write_log("-" * 50)  # separator for next run

if __name__ == '__main__':
    main()
