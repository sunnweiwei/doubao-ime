"""【实验】豆包语音翻译输入：按住热键说话，松手把译文（默认英文）填进当前光标处。

和日常那套（main.py，右 Option）完全独立、互不影响：
- 这套用 **右 Command** 键触发，复用 doubao_asr / typer，但悬浮窗用两行版 overlay2，
  上行显示原文识别、下行显示英文译文（分句实时翻译预览）。
- 松手时把整段原文用 MT 重译一遍（更连贯）作为最终结果，填入光标处。

运行：  python3 main_translate.py
按住右 Command 说话，松手结束。Ctrl+C 退出。

环境变量：
  DOUBAO_API_KEY        必填，火山引擎新版控制台的 X-Api-Key（需开通 volc.speech.mt）
  DOUBAO_TARGET_LANG    目标语言，默认 en（英文）
  DOUBAO_SOURCE_LANG    源语言，留空＝自动检测（任意语言皆可）；想固定中文可设 zh
  DOUBAO_OVERLAY*       同 overlay 的几个外观变量
"""
import asyncio
import os
import signal
import threading

import sounddevice as sd
import Quartz

from doubao_asr import ASRSession, build_request_params, connect_warm
from typer import type_string
from translate import translate
from overlay2 import OverlayController2, setup_app

# ====== 配置 ======
API_KEY = os.environ.get("DOUBAO_API_KEY", "")
TARGET_LANG = os.environ.get("DOUBAO_TARGET_LANG", "en")     # 默认翻成英文
SOURCE_LANG = os.environ.get("DOUBAO_SOURCE_LANG", "") or None  # 空＝自动检测
ENABLE_DDC = os.environ.get("DOUBAO_DDC", "1") != "0"       # 语义顺滑
# 松手后是否把整段原文再整体重译一遍：更连贯但多一次网络往返、松手会变慢。
# 默认关：直接用说话时已实时翻好的分句结果，松手几乎无延迟。
RETRANSLATE = os.environ.get("DOUBAO_FINAL_RETRANSLATE", "0") != "0"
HOTKEY_KEYCODE = 54                            # 右 Command。左 Command=55
SAMPLE_RATE = 16000
BLOCK = 1600                                   # 录音回调粒度 100ms
WARM_CONN = os.environ.get("DOUBAO_WARM_CONN", "1") != "0"  # 预热连接，消除握手延迟
# ==================


class App:
    def __init__(self, overlay=None):
        self.loop = asyncio.new_event_loop()
        self.session = None
        self.recording = False
        self.latest_text = ""           # 最新原文（全量）
        self.final_text = ""            # 最终原文
        self.overlay = overlay
        self._lock = threading.Lock()
        self._prebuf = []
        self._warm_ws = None
        # 分句翻译预览状态（仅 loop 线程访问）
        self._zh_sents = []             # 已确认的原文分句
        self._en_sents = []             # 对应译文（分句实时翻译填入）
        self._tr_lock = asyncio.Lock()  # 串行化翻译，保证译文顺序
        self.stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1,
                                        dtype="int16", blocksize=BLOCK,
                                        callback=self._audio_cb)

    # ---- asyncio 后台线程 ----
    def start_loop(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        if WARM_CONN:
            self.loop.create_task(self._rewarm())
        self.loop.run_forever()

    def _take_warm(self):
        ws = self._warm_ws
        self._warm_ws = None
        if ws is not None and ws.state.name == "OPEN":
            return ws
        return None

    async def _rewarm(self):
        if not WARM_CONN or self._warm_ws is not None:
            return
        try:
            self._warm_ws = await connect_warm(API_KEY)
        except Exception:
            self._warm_ws = None

    # ---- 录音回调（PortAudio 线程）----
    def _audio_cb(self, indata, frames, time_info, status):
        data = bytes(indata)
        with self._lock:
            if self.session is not None:
                self.loop.call_soon_threadsafe(self.session.feed, data)
            else:
                self._prebuf.append(data)

    # ---- 识别结果回调（loop 线程）----
    def _on_result(self, text, is_final, result):
        self.latest_text = text
        if is_final:
            self.final_text = text
        # 取出已确认（definite）的分句，新增的就实时翻译，喂到下行预览
        utts = (result or {}).get("utterances") or []
        definite = [u.get("text", "") for u in utts if u.get("definite")]
        if len(definite) > len(self._zh_sents):
            new = definite[len(self._zh_sents):]
            self._zh_sents = definite[:]
            self.loop.create_task(self._translate_new(new))
        self._refresh_overlay()

    def _refresh_overlay(self):
        if self.overlay:
            self.overlay.set_text(self.latest_text, " ".join(self._en_sents))

    async def _translate_new(self, new_texts):
        async with self._tr_lock:   # 串行：保证译文按句序追加
            try:
                ens = await self.loop.run_in_executor(
                    None, translate, API_KEY, new_texts, TARGET_LANG, SOURCE_LANG)
            except Exception as e:
                print(f"\n[分句翻译失败] {type(e).__name__}: {e}")
                return
            self._en_sents.extend(ens)
            self._refresh_overlay()

    def _on_error(self, code, msg):
        print(f"\n[ASR ERROR {code}] {msg}")

    # ---- 按键事件（主线程 run loop）----
    def on_press(self):
        if self.recording:
            return
        self.recording = True
        self.latest_text = ""
        self.final_text = ""
        self._zh_sents = []
        self._en_sents = []
        with self._lock:
            self._prebuf = []
            self.session = None
        self.stream.start()
        if self.overlay:
            self.overlay.show()
        print("\n🎙  录音中（翻译模式）...")
        self._connect_handle = asyncio.run_coroutine_threadsafe(
            self._connect(), self.loop)

    def on_release(self):
        if not self.recording:
            return
        self.recording = False
        self.stream.stop()
        asyncio.run_coroutine_threadsafe(self._end(), self.loop)

    async def _connect(self):
        params = build_request_params(enable_two_pass=True, enable_ddc=ENABLE_DDC)
        warm = self._take_warm()
        self.loop.create_task(self._rewarm())
        try:
            session = ASRSession(API_KEY, params, self._on_result,
                                 self._on_error, ws=warm)
            await session.__aenter__()
        except Exception as e:
            if warm is not None:
                try:
                    session = ASRSession(API_KEY, params, self._on_result,
                                         self._on_error)
                    await session.__aenter__()
                except Exception as e2:
                    print(f"\n[连接失败] {type(e2).__name__}: {e2}")
                    return
            else:
                print(f"\n[连接失败] {type(e).__name__}: {e}")
                return
        with self._lock:
            for chunk in self._prebuf:
                session.feed(chunk)
            self._prebuf = []
            self.session = session

    async def _end(self):
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
        # 等说话时在途的分句翻译都跑完，拿到已翻好的译文
        async with self._tr_lock:
            pass
        zh = self.final_text or self.latest_text
        en = " ".join(self._en_sents).strip()
        # 需要整段重译，或整句太短压根没分句（en 为空）时，才补翻一次
        if zh and (RETRANSLATE or not en):
            try:
                out = await self.loop.run_in_executor(
                    None, translate, API_KEY, [zh], TARGET_LANG, SOURCE_LANG)
                en = (out[0] if out else "") or en
            except Exception as e:
                print(f"\n[整段翻译失败，用分句结果] {type(e).__name__}: {e}")
        if en:
            type_string(en)
        if self.overlay:
            self.overlay.hide()
        print(f"\n✅ 原文: {zh}\n   译文: {en}\n")
        self.loop.create_task(self._rewarm())


def main():
    if not API_KEY:
        print("请先设置环境变量 DOUBAO_API_KEY，例如：\n"
              "  export DOUBAO_API_KEY=你的key\n  python3 main_translate.py")
        return

    overlay = None
    try:
        setup_app()
        overlay = OverlayController2()
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
                down = bool(flags & Quartz.kCGEventFlagMaskCommand)
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

    runloop = Quartz.CFRunLoopGetCurrent()

    def _stop(*_):
        Quartz.CFRunLoopStop(runloop)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    wake_timer = Quartz.CFRunLoopTimerCreate(
        None, Quartz.CFAbsoluteTimeGetCurrent(), 0.2, 0, 0,
        lambda *_: None, None)
    Quartz.CFRunLoopAddTimer(runloop, wake_timer, Quartz.kCFRunLoopCommonModes)

    print("=" * 48)
    print("  豆包语音翻译输入【实验】已启动")
    print(f"  目标语言: {TARGET_LANG}   源语言: {SOURCE_LANG or '自动检测'}")
    print(f"  热键: 右 Command (keycode {HOTKEY_KEYCODE})")
    print("  按住右 Command 说话，松手填入译文。Ctrl+C 退出。")
    print("=" * 48)
    try:
        Quartz.CFRunLoopRun()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app.stream.close()
        except Exception:
            pass
        Quartz.CGEventTapEnable(tap, False)
    print("\n再见。")


if __name__ == "__main__":
    main()
