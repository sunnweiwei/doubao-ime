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

from doubao_asr import ASRSession, build_request_params, recognize_once
from typer import LiveTyper, CommitTyper, type_string
from overlay import OverlayController, setup_app

# ====== 配置 ======
API_KEY = os.environ.get("DOUBAO_API_KEY", "")  # 不要把 key 写进代码，用环境变量
# 填字模式：
#   "final"  —（默认，推荐）说话过程用悬浮窗实时预览，松手时把最终结果一次性填入。
#             不闪烁、不出乱码、绝不动你原有文本，是 continue 追加。
#   "commit" — 每句确认后整句追加，从不退格。说话中即可分句上屏，但按句出字。
#   "live"   —（实验）实时增量退格重打。最跟手，但终端里易闪烁/乱码，谨慎用。
MODE = os.environ.get("DOUBAO_MODE", "final")
SHOW_OVERLAY = os.environ.get("DOUBAO_OVERLAY", "1") != "0"  # 悬浮实时预览窗
# final 模式松手后，把整段音频用更准的 nostream 接口重跑一遍作为最终结果
NOSTREAM_FINAL = os.environ.get("DOUBAO_NOSTREAM_FINAL", "1") != "0"
HOTKEY_KEYCODE = 61                            # 右 Option。左 Option=58
ENABLE_TWO_PASS = MODE != "commit"             # 开二遍识别，最终结果更准
SAMPLE_RATE = 16000
BLOCK = 1600                                   # 录音回调粒度 100ms
# ==================


class App:
    def __init__(self, overlay=None):
        self.loop = asyncio.new_event_loop()
        self.session = None
        self.recording = False
        self.typer = LiveTyper() if MODE == "live" else CommitTyper()
        self.latest_text = ""
        self.final_text = ""
        self.overlay = overlay
        self._lock = threading.Lock()
        self._prebuf = []           # ws 未连上前先缓存音频，连上后补发
        self._all_audio = []        # 本次完整录音，供松手后整段 nostream 重识别
        # 启动时就把麦克风设备开好（保持 stopped），按下时 start() 几乎瞬时
        self.stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1,
                                        dtype="int16", blocksize=BLOCK,
                                        callback=self._audio_cb)

    # ---- asyncio 后台线程 ----
    def start_loop(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # ---- 录音回调（在 PortAudio 线程里执行）----
    def _audio_cb(self, indata, frames, time_info, status):
        data = bytes(indata)
        with self._lock:
            self._all_audio.append(data)
            if self.session is not None:
                self.loop.call_soon_threadsafe(self.session.feed, data)
            else:
                self._prebuf.append(data)

    # ---- 识别结果回调（在 loop 线程里执行）----
    def _on_result(self, text, is_final, result):
        self.latest_text = text
        if is_final:
            self.final_text = text
        if MODE == "live":
            self.typer.update(text)
        elif MODE == "commit":
            self.typer.update_from_result(result)
        if self.overlay:
            self.overlay.set_text(text)
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
        self.latest_text = ""
        self.final_text = ""
        with self._lock:
            self._prebuf = []
            self._all_audio = []
            self.session = None
        self.stream.start()                     # 立刻开始录音
        if self.overlay:
            self.overlay.show()                 # 显示"聆听中…"占位
        print(f"\n🎙  录音中（模式={MODE}）...")
        self._connect_handle = asyncio.run_coroutine_threadsafe(
            self._connect(), self.loop)

    def on_release(self):
        if not self.recording:
            return
        self.recording = False
        self.stream.stop()                      # 停止录音（设备不关，下次秒开）
        # 松手后保留当前文本，等最终结果刷新；不加任何图标
        asyncio.run_coroutine_threadsafe(self._end(), self.loop)

    async def _connect(self):
        """并行连接 WebSocket；连上后把按下后缓存的音频补发，再切到实时喂。"""
        params = build_request_params(enable_two_pass=ENABLE_TWO_PASS)
        try:
            session = ASRSession(API_KEY, params, self._on_result, self._on_error)
            await session.__aenter__()
        except Exception as e:
            print(f"\n[连接失败] {type(e).__name__}: {e}")
            return
        with self._lock:
            for chunk in self._prebuf:
                session.feed(chunk)
            self._prebuf = []
            self.session = session              # 之后录音回调直接喂 session

    async def _end(self):
        # 若松手时 WebSocket 还在连接中（短按），先等它连完并补发缓存音频
        if getattr(self, "_connect_handle", None):
            try:
                await asyncio.wrap_future(self._connect_handle)
            except Exception:
                pass
            self._connect_handle = None
        if self.session:
            try:
                await self.session.finish()
            finally:
                await self.session.__aexit__(None, None, None)
                self.session = None
        if MODE == "final":
            text = self.final_text or self.latest_text
            # 松手后把整段音频用更准的 nostream 接口重跑一遍，作为最终结果
            if NOSTREAM_FINAL:
                with self._lock:
                    full = b"".join(self._all_audio)
                try:
                    params = build_request_params(enable_two_pass=False)
                    accurate = await recognize_once(API_KEY, full, params)
                    if accurate:
                        text = accurate
                        if self.overlay:
                            self.overlay.set_text(text)
                except Exception as e:
                    print(f"\n[整段优化失败，用流式结果] {type(e).__name__}: {e}")
            # 一次性填入当前光标处（只追加，绝不退格）
            if text:
                type_string(text)
        if self.overlay:
            self.overlay.hide()
        print("\n✅ 结束\n")


def main():
    if not API_KEY:
        print("请先设置环境变量 DOUBAO_API_KEY，例如：\n"
              "  export DOUBAO_API_KEY=你的key\n  python3 main.py")
        return

    overlay = None
    if SHOW_OVERLAY:
        try:
            setup_app()                     # 初始化 NSApplication（无 Dock 图标）
            overlay = OverlayController()
        except Exception as e:
            print(f"[悬浮窗初始化失败，已禁用预览] {type(e).__name__}: {e}")

    app = App(overlay=overlay)
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