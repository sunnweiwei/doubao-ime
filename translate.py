"""豆包机器翻译 (MT) REST 客户端：把文本翻成目标语言。

只被实验性的 main_translate.py 使用，不影响原有 ASR 语音输入法那一套。
鉴权同样用新版控制台的 X-Api-Key，资源 ID 固定 volc.speech.mt。
SSL 处理复用 doubao_asr 里的 _ssl_context（同样支持 DOUBAO_CA_BUNDLE / DOUBAO_INSECURE_SSL）。
"""
import json
import urllib.request
import uuid

from doubao_asr import _ssl_context

URL = "https://openspeech.bytedance.com/api/v3/machine_translation/matx_translate"
RESOURCE_ID = "volc.speech.mt"


def translate(api_key, text_list, target_language="en", source_language=None,
              timeout=10.0):
    """把 text_list 批量翻成 target_language，返回与输入一一对应的译文列表。

    source_language 留空（None/"")则由服务端自动检测源语言，因此任意语言皆可。
    text_list 长度不超过 16 条，单条不超过 1024 tokens（本场景一句一条，不会超）。
    """
    if not text_list:
        return []
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {"target_language": target_language, "text_list": list(text_list)}
    if source_language:
        body["source_language"] = source_language
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 20000000:
        raise RuntimeError(f"MT {result.get('code')}: {result.get('message')}")
    return [t.get("translation", "")
            for t in result.get("data", {}).get("translation_list", [])]
