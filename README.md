# doubao-ime

macOS 上的「按住说话」语音输入工具：按住热键（默认右 Option）说话，调用豆包大模型流式语音识别（ASR），把识别文本实时填进**当前光标所在的任意 App**（Terminal、浏览器、编辑器……）。不是真正的输入法，而是一个常驻后台的小程序。

## 效果

- 按住右 Option → 开始录音 → 边说边把识别结果填进光标处。
- 松手 → 发送最后一包，拿到带标点的最终结果。
- 两种填字模式：
  - `live`（默认）：实时增量填字，识别修正时退格重打。最跟手。
  - `commit`：每句确认后整句填入，**从不退格**。最稳，但按句出字。

## 依赖

```bash
python3 -m pip install websockets sounddevice pyobjc-framework-Quartz
```

## 系统权限（macOS 系统设置 > 隐私与安全）

把以下权限授给**启动本脚本的那个终端 App**（Terminal / iTerm / VS Code 终端等）：

| 权限 | 用途 |
|---|---|
| 麦克风 Microphone | 录音（首次运行自动弹窗，点 Allow） |
| 输入监控 Input Monitoring | 全局热键监听 |
| 辅助功能 Accessibility | 把字打进其它 App |

改完开关后**重启终端**再运行。

## 运行

```bash
export DOUBAO_API_KEY=你的火山引擎APIKey   # 新版控制台的 X-Api-Key
export DOUBAO_MODE=live                    # 或 commit
python3 main.py
```

按住右 Option 说话，松手结束，Ctrl+C 退出。
想换热键改 `main.py` 里的 `HOTKEY_KEYCODE`（左 Option=58，右 Option=61）。

## 结构

- `doubao_asr.py` — 豆包 ASR WebSocket 客户端，封装二进制协议（gzip+JSON），异步流式接口。
- `typer.py` — 把文本合成键盘事件打进光标处；`LiveTyper`（增量退格重打）/ `CommitTyper`（只追加）。
- `main.py` — 全局热键监听 + 麦克风采集 + 串起识别与填字。

## 安全

不要把 API Key 写进代码或提交到仓库，只用环境变量 `DOUBAO_API_KEY`。