import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from glider_config import ensure_config_dir


def run_glider(glider_path: Path, config_path: Path):
    """启动 glider 进程"""
    try:
        process = subprocess.Popen(
            [str(glider_path), "-config", str(config_path)],
            stdout=None,
            stderr=None,
            universal_newlines=True,
        )
        return process
    except Exception as exc:
        print(f"Error starting glider: {exc}")
        return None


def kill_glider(process):
    """终止 glider 进程"""
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    except Exception as exc:
        print(f"Error killing glider: {exc}")


def run_collector():
    """执行节点收集脚本"""
    try:
        subprocess.run(["python", "run_collector.py"], check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Error running collector: {exc}")
        return False


def main():
    current_dir = Path(__file__).parent.absolute()
    config_dir = ensure_config_dir(current_dir)
    glider_binary = 'glider.exe' if os.name == 'nt' else 'glider'
    glider_path = current_dir / "glider" / glider_binary
    config_path = config_dir / "glider.conf"

    if not glider_path.exists():
        print(f"Error: glider executable not found at {glider_path}")
        sys.exit(1)

    try:
        glider_path.chmod(0o755)
    except Exception:
        pass

    glider_process = None

    def cleanup(signum, frame):
        print("\nReceived termination signal. Cleaning up...")
        if glider_process:
            kill_glider(glider_process)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        print(f"\n[{datetime.now()}] Starting initial glider process...")
        glider_process = run_glider(glider_path, config_path)
        if not glider_process:
            print("Failed to start initial glider process")
            sys.exit(1)
        print("Initial glider process started successfully")

        while True:
            print(f"[{datetime.now()}] Waiting 30 minutes until next update...")
            time.sleep(1800)

            print(f"\n[{datetime.now()}] Starting update cycle...")

            if run_collector():
                if glider_process:
                    print("Stopping current glider process...")
                    kill_glider(glider_process)

                print("Starting new glider process...")
                glider_process = run_glider(glider_path, config_path)
                if not glider_process:
                    print("Failed to start glider")
                    continue

                print("Update completed successfully")
            else:
                print("Collector failed, keeping current glider process")

    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt. Cleaning up...")
        if glider_process:
            kill_glider(glider_process)
        sys.exit(0)


if __name__ == "__main__":
    main()
