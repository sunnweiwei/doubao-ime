# doubao-ime

macOS 上的「按住说话」语音输入工具。按住热键说话，调用豆包大模型语音识别（ASR 2.0），
把识别文本填进**当前光标所在的任意 App**（Terminal、浏览器、编辑器……）。

它不是真正的输入法，而是一个常驻后台运行的小程序：在哪个输入框聚焦，就往哪里填字。

## 效果

按住右 Option → 立刻开始录音，屏幕底部弹出**悬浮预览窗**实时显示识别文本；
松手 → 把最终结果一次性填进当前光标处（纯追加，不动已有文字）。

## 安装

```bash
python3 -m pip install -r requirements.txt
```

## 系统权限

在「系统设置 > 隐私与安全」里，把这几项授权给**启动本脚本的终端 App**
（Terminal / iTerm / VS Code 终端等），改完**重启终端**：

| 权限 | 用途 |
|---|---|
| 麦克风 Microphone | 录音（首次运行自动弹窗，点 Allow 即可） |
| 输入监控 Input Monitoring | 全局热键监听 |
| 辅助功能 Accessibility | 把字打进其它 App |

## 运行

```bash
export DOUBAO_API_KEY=你的火山引擎APIKey   # 新版控制台的 X-Api-Key
python3 main.py
```

按住右 Option 说话，松手填入，`Ctrl+C` 退出。脚本运行期间保持这个终端窗口不关。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DOUBAO_API_KEY` | — | 必填，火山引擎新版控制台的 X-Api-Key |
| `DOUBAO_MODE` | `final` | 填字模式，见下 |
| `DOUBAO_OVERLAY` | `1` | 设 `0` 关闭悬浮预览窗 |
| `DOUBAO_OVERLAY_BOTTOM` | `90` | 悬浮窗距屏幕底部像素 |
| `DOUBAO_OVERLAY_FONT` | `18` | 悬浮窗字号 |

填字模式 `DOUBAO_MODE`：

- `final`（默认，推荐）：说话时只在悬浮窗预览，松手一次性填入。不闪、不乱码、绝不动已有文字。
- `commit`：每句确认后整句追加，从不退格，说话中分句上屏。
- `live`（实验）：实时增量退格重打，最跟手，但在终端里易闪烁/乱码。

换热键：改 `main.py` 里的 `HOTKEY_KEYCODE`（右 Option=61，左 Option=58）。

<details>
<summary>报 CERTIFICATE_VERIFY_FAILED 怎么办</summary>

通常是 Python 缺根证书库（python.org 版装完未装证书）。装 certifi 即可
（已在 requirements.txt，本工具会优先使用）：`python3 -m pip install -r requirements.txt`。

少数受管控网络用了自建根证书代理时，再 `export DOUBAO_CA_BUNDLE=/path/to/根证书.pem` 追加。
应急可 `export DOUBAO_INSECURE_SSL=1` 跳过校验（降低安全性，不建议长期用）。
</details>

## 结构

- `doubao_asr.py` — 豆包 ASR WebSocket 客户端，封装二进制协议（gzip+JSON）。
- `typer.py` — 合成键盘事件把文本打进光标处。
- `overlay.py` — 屏幕悬浮实时预览窗（不抢焦点的 NSPanel）。
- `main.py` — 全局热键 + 麦克风采集 + 串起识别、预览与填字。

按下即开始录音并缓存音频，WebSocket 并行连接、连上后补发，所以按下到出字几乎无延迟。

## 安全

不要把 API Key 写进代码或提交到仓库，只用环境变量 `DOUBAO_API_KEY`。
