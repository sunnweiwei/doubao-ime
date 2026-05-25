"""一条命令同时启动两套语音输入：

  python3 run_all.py

- main.py            日常语音输入（右 Option）
- main_translate.py  实验翻译输入（右 Command）

两者各自独立的进程，互不影响；Ctrl+C 一并退出。
不想要翻译那套时，照常单独 `python3 main.py` 即可，本启动器不改动任何原文件。
"""
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = ["main.py", "main_translate.py"]


def main():
    procs = []
    for s in SCRIPTS:
        procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, s)]))
    print(f"已启动 {len(procs)} 个进程：{', '.join(SCRIPTS)}（Ctrl+C 全部退出）")
    try:
        # 任一进程退出就跟着收尾
        while True:
            for p in procs:
                if p.poll() is not None:
                    return
            try:
                procs[0].wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        print("\n全部退出。")


if __name__ == "__main__":
    main()
