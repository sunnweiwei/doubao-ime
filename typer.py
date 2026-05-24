"""把文本"打"进当前光标处（合成键盘事件），需要"辅助功能"权限。

对外提供两种填字策略：
- LiveTyper：增量式。记住已打入的文本，新结果来了就找公共前缀，
  退格删掉变化的尾部再重打。识别修正时会退格——对应"删掉再填"。
- CommitTyper：只追加，从不退格。配合分句 definite 标记，每句确认后整句打入。
  对应"直接填、不删"。
"""
import time

import Quartz

KEY_BACKSPACE = 51


def _post(event):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def type_string(s):
    """插入一段 Unicode 文本（含中文）。"""
    if not s:
        return
    down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    Quartz.CGEventKeyboardSetUnicodeString(down, len(s), s)
    _post(down)
    up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
    Quartz.CGEventKeyboardSetUnicodeString(up, len(s), s)
    _post(up)


def send_backspace(n):
    for _ in range(n):
        _post(Quartz.CGEventCreateKeyboardEvent(None, KEY_BACKSPACE, True))
        _post(Quartz.CGEventCreateKeyboardEvent(None, KEY_BACKSPACE, False))
        time.sleep(0.002)


def _common_prefix_len(a, b):
    i = 0
    n = min(len(a), len(b))
    while i < n and a[i] == b[i]:
        i += 1
    return i


class LiveTyper:
    """增量式：维护已打入文本，新全量结果到来时做最小差异替换。"""

    def __init__(self):
        self.typed = ""

    def update(self, new_text):
        if new_text == self.typed:
            return
        prefix = _common_prefix_len(self.typed, new_text)
        send_backspace(len(self.typed) - prefix)
        type_string(new_text[prefix:])
        self.typed = new_text

    def reset(self):
        self.typed = ""


class CommitTyper:
    """只追加：根据 utterances 里 definite=true 的分句，逐句一次性打入，从不退格。"""

    def __init__(self):
        self._committed = 0  # 已打入的 definite 分句数量

    def update_from_result(self, result):
        utts = result.get("utterances") or []
        definite = [u for u in utts if u.get("definite")]
        for u in definite[self._committed:]:
            type_string(u.get("text", ""))
            self._committed += 1

    def reset(self):
        self._committed = 0