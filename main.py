"""豆包语音输入：按住热键说话，实时把识别文本填进当前光标处。

运行：  python3 main.py
按住右 Option 键说话，松手结束。Ctrl+C 退出。

需要的系统权限（系统设置 > 隐私与安全）：
- 麦克风 Microphone（首次运行会弹窗，点 Allow）
- 输入监控 Input Monitoring（全局热键）
- 辅助功能 Accessibility（把字打进其它 App）
都授权给"启动本脚本的那个终端 App"（Terminal / iTerm / ...）。
"""
import asyncio
import os
import threading

import sounddevice as sd
import Quartz

from doubao_asr import ASRSession, build_request_params
from typer import LiveTyper, CommitTyper

# ====== 配置 ======
API_KEY = os.environ.get("DOUBAO_API_KEY", "")  # 不要把 key 写进代码，用环境变量
MODE = os.environ.get("DOUBAO_MODE", "live")   # "live"=实时增量(会退格修正)  "commit"=逐句追加(不退格)
HOTKEY_KEYCODE = 61                            # 右 Option。左 Option=58
ENABLE_TWO_PASS = MODE == "live"               # live 模式开二遍识别，松手时纠错更准
SAMPLE_RATE = 16000
BLOCK = 1600                                   # 录音回调粒度 100ms
# ==================


class App:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.session = None
        self.stream = None
        self.recording = False
        self.typer = LiveTyper() if MODE == "live" else CommitTyper()

    # ---- asyncio 后台线程 ----
    def start_loop(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # ---- 识别结果回调（在 loop 线程里执行）----
    def _on_result(self, text, is_final, result):
        if MODE == "live":
            self.typer.update(text)
        else:
            self.typer.update_from_result(result)
        tag = "FINAL" if is_final else "..."
        print(f"\r[{tag}] {text}", end="", flush=True)

    def _on_error(self, code, msg):
        print(f"\n[ASR ERROR {code}] {msg}")

    # ---- 按键事件（在主线程 run loop 里执行）----
    def on_press(self):
        if self.recording:
            return
        self.recording = True
        self.typer.reset()
        print(f"\n🎙  录音中（模式={MODE}）...")
        asyncio.run_coroutine_threadsafe(self._begin(), self.loop)

    def on_release(self):
        if not self.recording:
            return
        self.recording = False
        asyncio.run_coroutine_threadsafe(self._end(), self.loop)

    async def _begin(self):
        params = build_request_params(enable_two_pass=ENABLE_TWO_PASS)
        try:
            self.session = ASRSession(API_KEY, params, self._on_result, self._on_error)
            await self.session.__aenter__()
        except Exception as e:
            print(f"\n[连接失败] {type(e).__name__}: {e}")
            self.session = None
            return

        def audio_cb(indata, frames, time_info, status):
            if self.session:
                self.loop.call_soon_threadsafe(self.session.feed, bytes(indata))

        self.stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1,
                                        dtype="int16", blocksize=BLOCK,
                                        callback=audio_cb)
        self.stream.start()

    async def _end(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.session:
            try:
                await self.session.finish()
            finally:
                await self.session.__aexit__(None, None, None)
                self.session = None
        print("\n✅ 结束\n")


def main():
    if not API_KEY:
        print("请先设置环境变量 DOUBAO_API_KEY，例如：\n"
              "  export DOUBAO_API_KEY=你的key\n  python3 main.py")
        return
    app = App()
    app.start_loop()

    def tap_cb(proxy, type_, event, refcon):
        if type_ == Quartz.kCGEventFlagsChanged:
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode)
            if keycode == HOTKEY_KEYCODE:
                flags = Quartz.CGEventGetFlags(event)
                down = bool(flags & Quartz.kCGEventFlagMaskAlternate)
                if down:
                    app.on_press()
                else:
                    app.on_release()
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
        tap_cb, None)
    if tap is None:
        print("无法创建事件监听。请确认已在「输入监控 / 辅助功能」里授权当前终端 App，"
              "然后重启终端再试。")
        return
    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src,
                              Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)

    print("=" * 48)
    print("  豆包语音输入已启动")
    print(f"  模式: {MODE}    热键: 右 Option (keycode {HOTKEY_KEYCODE})")
    print("  按住右 Option 说话，松手结束。Ctrl+C 退出。")
    print("=" * 48)
    try:
        Quartz.CFRunLoopRun()
    except KeyboardInterrupt:
        print("\n再见。")


if __name__ == "__main__":
    main()