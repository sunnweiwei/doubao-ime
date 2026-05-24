"""豆包大模型流式语音识别 (ASR) 的 WebSocket 客户端。

封装二进制协议（gzip + JSON），对外暴露一个异步流式接口：
喂音频字节进去，回调实时吐出识别文本。

协议要点（实测）：
- 鉴权用新版控制台的 X-Api-Key（无需单独 App ID）。
- 服务端响应不做 gzip 压缩，且只有 flags 最低位为 1 时才带 4 字节 sequence。
- 流式发裸 PCM 帧时音频格式声明为 "pcm"。
- 双向流式优化版不是每包都回，必须持续发包，否则触发 45000081 等包超时。
"""
import asyncio
import gzip
import json
import os
import ssl
import struct
import uuid

import websockets


def _ssl_context():
    """构造 SSL 上下文。

    DOUBAO_CA_BUNDLE  指向公司根证书 (PEM)，正规做法。
    DOUBAO_INSECURE_SSL=1  跳过证书校验（公司 SSL 拦截时图省事用，安全性降低）。
    默认走系统默认校验。
    """
    if os.environ.get("DOUBAO_INSECURE_SSL", "0") != "0":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ca = os.environ.get("DOUBAO_CA_BUNDLE")
    if ca:
        # 在系统默认证书库之上，追加用户提供的根证书
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(os.path.expanduser(ca))
        return ctx
    return None  # 用 websockets 默认上下文

URL_STREAM = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
URL_NOSTREAM = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
URL = URL_STREAM  # 向后兼容
# ASR 2.0（seedasr，小时版）。1.0 为 volc.bigasr.sauc.duration
RESOURCE_ID = "volc.seedasr.sauc.duration"

# ---- 二进制协议常量 ----
PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001
FULL_CLIENT = 0b0001
AUDIO_ONLY = 0b0010
FULL_SERVER = 0b1001
ERROR_RESP = 0b1111
NO_SERIAL = 0b0000
JSON_SERIAL = 0b0001
GZIP = 0b0001
NO_COMP = 0b0000


def _header(msg_type, flags, serial, comp):
    return bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE,
        (msg_type << 4) | flags,
        (serial << 4) | comp,
        0x00,
    ])


def _build_full_client(params):
    body = gzip.compress(json.dumps(params).encode())
    msg = _header(FULL_CLIENT, 0b0001, JSON_SERIAL, GZIP)
    msg += struct.pack(">i", 1)
    msg += struct.pack(">I", len(body))
    msg += body
    return msg


def _build_audio(chunk, seq, last):
    body = gzip.compress(chunk)
    if last:
        flags = 0b0011
        seq = -seq
    else:
        flags = 0b0001
    msg = _header(AUDIO_ONLY, flags, NO_SERIAL, GZIP)
    msg += struct.pack(">i", seq)
    msg += struct.pack(">I", len(body))
    msg += body
    return msg


def _parse(data):
    header_size = (data[0] & 0x0f) * 4
    msg_type = data[1] >> 4
    flags = data[1] & 0x0f
    comp = data[2] & 0x0f
    rest = data[header_size:]
    if msg_type == ERROR_RESP:
        code = struct.unpack(">I", rest[:4])[0]
        size = struct.unpack(">I", rest[4:8])[0]
        msg = rest[8:8 + size]
        if comp == GZIP and msg:
            try:
                msg = gzip.decompress(msg)
            except Exception:
                pass
        return ("ERROR", code, flags, msg.decode("utf-8", "replace"))
    if msg_type == FULL_SERVER:
        seq = None
        if flags & 0b0001:
            seq = struct.unpack(">i", rest[:4])[0]
            rest = rest[4:]
        size = struct.unpack(">I", rest[:4])[0]
        body = rest[4:4 + size]
        if comp == GZIP and body:
            body = gzip.decompress(body)
        obj = json.loads(body.decode("utf-8")) if body else {}
        return ("SERVER", seq, flags, obj)
    return ("OTHER", msg_type, flags, data[:16].hex())


def build_request_params(*, enable_two_pass=False, show_utterances=True,
                         enable_punc=True, enable_ddc=False):
    """构造 full client request 的 JSON 参数。"""
    request = {
        "model_name": "bigmodel",
        "enable_punc": enable_punc,
        "enable_ddc": enable_ddc,
        "show_utterances": show_utterances,
    }
    if enable_two_pass:
        # 双向流式优化版的二遍识别：VAD 判停时用非流式模型重识别该分句，更准。
        request["enable_nonstream"] = True
    return {
        "user": {"uid": "doubao-ime"},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000,
                  "bits": 16, "channel": 1},
        "request": request,
    }


def _auth_headers(api_key):
    return {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }


async def recognize_once(api_key, pcm_bytes, params, timeout=15.0):
    """把整段音频用流式输入模式 (bigmodel_nostream) 跑一遍，返回最准的文本。

    适合"松手后对整段录音再优化一遍"：准确率比双向流式更高。
    """
    chunk = int(16000 * 0.2) * 2
    ws = await websockets.connect(URL_NOSTREAM,
                                  additional_headers=_auth_headers(api_key),
                                  max_size=None, ssl=_ssl_context())
    try:
        await ws.send(_build_full_client(params))
        await ws.recv()  # 首包确认
        seq = 1
        if pcm_bytes:
            for i in range(0, len(pcm_bytes), chunk):
                seq += 1
                piece = pcm_bytes[i:i + chunk]
                last = i + chunk >= len(pcm_bytes)
                await ws.send(_build_audio(piece, seq, last))
        else:
            await ws.send(_build_audio(b"", seq + 1, True))
        final_text = ""
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                break
            kind, _seq, flags, body = _parse(raw)
            if kind == "ERROR":
                break
            if kind != "SERVER":
                continue
            res = body.get("result") or {}
            text = res.get("text") if isinstance(res, dict) else None
            if text:
                final_text = text
            if flags & 0b0010:
                break
        return final_text
    finally:
        await ws.close()


class ASRSession:
    """一次按住说话的识别会话。

    用法：
        async with ASRSession(api_key, params, on_result) as s:
            s.feed(pcm_bytes)        # 多次喂 200ms 左右的 PCM
            ...
            await s.finish()         # 松手后调用，发送最后一包并等最终结果
    """

    CHUNK = int(16000 * 0.2) * 2  # 200ms 16k mono s16le = 6400 字节

    def __init__(self, api_key, params, on_result, on_error=None):
        self.api_key = api_key
        self.params = params
        self.on_result = on_result      # callable(text, is_final)
        self.on_error = on_error
        self.ws = None
        self.logid = None
        self._queue = asyncio.Queue()
        self._finished = asyncio.Event()
        self._tasks = []

    async def __aenter__(self):
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        self.ws = await websockets.connect(URL, additional_headers=headers,
                                           max_size=None, ssl=_ssl_context())
        self.logid = self.ws.response.headers.get("X-Tt-Logid")
        await self.ws.send(_build_full_client(self.params))
        await self.ws.recv()  # 首包确认
        self._tasks = [asyncio.create_task(self._sender()),
                       asyncio.create_task(self._receiver())]
        return self

    async def __aexit__(self, *exc):
        for t in self._tasks:
            t.cancel()
        if self.ws:
            await self.ws.close()

    def feed(self, pcm_bytes):
        """线程安全地塞入 PCM 数据（从录音线程调用需用 call_soon_threadsafe）。"""
        self._queue.put_nowait(pcm_bytes)

    async def finish(self):
        """标记说话结束：发完剩余音频 + 最后一包，等待 receiver 收到最终结果。"""
        self._finished.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _sender(self):
        seq = 1
        buf = b""
        while True:
            if not self._finished.is_set():
                try:
                    buf += await asyncio.wait_for(self._queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
            else:
                # 结束信号：把队列里剩下的都取出来
                try:
                    while True:
                        buf += self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            while len(buf) >= self.CHUNK:
                seq += 1
                await self.ws.send(_build_audio(buf[:self.CHUNK], seq, last=False))
                buf = buf[self.CHUNK:]
            if self._finished.is_set():
                seq += 1
                await self.ws.send(_build_audio(buf, seq, last=True))
                return

    async def _receiver(self):
        while True:
            try:
                raw = await self.ws.recv()
            except websockets.ConnectionClosed:
                return
            kind, seq, flags, body = _parse(raw)
            if kind == "ERROR":
                if self.on_error:
                    self.on_error(seq, body)
                return
            if kind != "SERVER":
                continue
            res = body.get("result") or {}
            text = res.get("text") if isinstance(res, dict) else None
            is_final = bool(flags & 0b0010)
            if text is not None or is_final:
                self.on_result(text or "", is_final, res)
            if is_final:
                return
