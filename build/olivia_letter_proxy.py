import base64
import http.server as _http_server
import json
import os
import random
import socketserver as _socketserver
import subprocess
import threading
import time
import urllib.request
import uuid

from mitmproxy import http, ctx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "letters.json")
MEMORY_PATH = os.path.join(BASE_DIR, "memory.json")

CONFIG = {}
OPENAI = {}
PERSONA = {}
LISTENER = {}
MEMORY = {}
MEMORY_MAX_ENTRIES = 30
MEMORY_MAX_CHARS = 3000
DISPATCH_ENC_CONF = ""
REPLY_CFG = {}
VIDEO_CFG = {}
TTS_CFG = {}

VIDEO_ENABLED = True
TTS_ENABLED = True
VIDEO_PROBABILITY = 0.3

_config_mtime = 0.0


def reload_config(force=False):
    global CONFIG, OPENAI, PERSONA, LISTENER, MEMORY, MEMORY_MAX_ENTRIES, MEMORY_MAX_CHARS
    global DISPATCH_ENC_CONF, REPLY_CFG, VIDEO_CFG, TTS_CFG
    global VIDEO_ENABLED, TTS_ENABLED, VIDEO_PROBABILITY, _config_mtime
    if not force:
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except Exception:
            mtime = _config_mtime
        if mtime == _config_mtime:
            return
        _config_mtime = mtime
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            CONFIG = json.load(f)
    except Exception:
        return
    OPENAI = CONFIG.get("openai", {})
    PERSONA = CONFIG.get("persona", {})
    LISTENER = CONFIG.get("listener", {})
    MEMORY = CONFIG.get("memory", {})
    MEMORY_MAX_ENTRIES = MEMORY.get("max_entries", 30)
    MEMORY_MAX_CHARS = MEMORY.get("max_chars", 3000)
    DISPATCH_ENC_CONF = CONFIG.get("dispatch", {}).get("enc_conf", "")
    REPLY_CFG = CONFIG.get("reply", {})
    VIDEO_CFG = CONFIG.get("video", {})
    TTS_CFG = CONFIG.get("tts", {})
    VIDEO_ENABLED = REPLY_CFG.get("video_enabled", True)
    TTS_ENABLED = REPLY_CFG.get("tts_enabled", True)
    VIDEO_PROBABILITY = REPLY_CFG.get("video_probability", 0.3)


reload_config()
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
VIDEO_PORT = 8765
VIDEO_HOST = "127.0.0.1"

LETTER_STATUS_PENDING = 1
LETTER_STATUS_AUDITING = 2
LETTER_STATUS_LLM_PROCESSING = 3
LETTER_STATUS_REPLIED = 4
LETTER_STATUS_FAILED = 5

AUDIT_PASSED = 2
REPLY_TYPE_NONE = 0
REPLY_TYPE_TEXT = 1
REPLY_TYPE_SPEECH = 2
REPLY_TYPE_MIX_PLAY = 3
REPLY_TYPE_MIX_SVS = 4

state = {
    "letters": {},
    "seq": 1000,
    "lock": threading.Lock(),
}

memory = {
    "history": [],
    "compressed": [],
    "overflow": [],
}


def load_data():
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        state["letters"] = loaded.get("letters", {})
        state["seq"] = loaded.get("seq", 1000)
    except Exception:
        pass


def seed_data():
    if not state["letters"]:
        now = int(time.time())
        state["letters"]["2001"] = {
            "id": "2001",
            "content": "林离你好，最近我经常听你的钢琴曲，很喜欢。想问下你最近练了什么新曲子？",
            "summary": "林离你好，最近我经常听你的钢琴曲，很喜欢。想问下你最近练了什么新曲子？",
            "stampId": "s1",
            "created_at": now - 200,
            "status": LETTER_STATUS_REPLIED,
            "unread": True,
            "reply_text": "谢谢你来听我弹琴。最近在练肖邦的夜曲，Op.9 No.2。那是一首很适合雨天的曲子，弹的时候总觉得窗外的雨声能和琴声合在一起。你要是想听，我可以弹给你听。",
            "replied_at": now - 60,
        }
        state["seq"] = 2001
        save_data()


def save_data():
    try:
        to_save = {"letters": state["letters"], "seq": state["seq"]}
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        ctx.log.warn("save_data failed: %s" % e)


def load_memory():
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        memory["history"] = loaded.get("history", [])
        memory["compressed"] = loaded.get("compressed", [])
        memory["overflow"] = loaded.get("overflow", [])
    except Exception:
        pass


def save_memory():
    try:
        to_save = {
            "history": memory["history"],
            "compressed": memory["compressed"],
            "overflow": memory["overflow"],
        }
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        ctx.log.warn("save_memory failed: %s" % e)


def remember(role, content):
    with state["lock"]:
        memory["history"].append({
            "role": role,
            "content": content,
            "ts": current_ts(),
        })
        while len(memory["history"]) > MEMORY_MAX_ENTRIES:
            memory["overflow"].append(memory["history"].pop(0))
        save_memory()


def build_memory_messages():
    msgs = []
    for m in memory["compressed"]:
        msgs.append({"role": "system", "content": "（记忆）%s" % m["content"]})
    for m in memory["history"]:
        msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


def compress_memory():
    reload_config()
    with state["lock"]:
        if not memory["overflow"]:
            return
        overflow = memory["overflow"]
        prev_summaries = [m["content"] for m in memory["compressed"] if m["role"] == "assistant"]
        memory["overflow"] = []
        memory["compressed"] = []
    try:
        text = "\n".join("%s: %s" % (m["role"], m["content"]) for m in overflow)
        if prev_summaries:
            text = "此前摘要：\n" + "\n".join(prev_summaries) + "\n\n新对话：\n" + text
        url = OPENAI["base_url"].rstrip("/") + "/chat/completions"
        payload = {
            "model": OPENAI["model"],
            "temperature": 0.4,
            "max_tokens": 800,
            "messages": [
                {"role": "system", "content": "你是记忆压缩器。把林离与玩家的书信往来内容压缩成简明要点摘要，保留双方说过的话和上下文。用中文，逐条列出。"},
                {"role": "user", "content": "请压缩以下对话为摘要：\n\n" + text},
            ],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % OPENAI["api_key"],
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        summary = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        ctx.log.warn("compress_memory failed: %s" % e)
        with state["lock"]:
            memory["overflow"] = overflow + memory["overflow"]
            memory["compressed"] = [{"role": "assistant", "content": s, "ts": current_ts()} for s in prev_summaries]
            save_memory()
        return
    with state["lock"]:
        memory["compressed"].append({"role": "assistant", "content": "[历史摘要] " + summary, "ts": current_ts()})
        save_memory()


DISPATCH_HOSTS = ("dispatcher.olivia.miyoushe.com",)


def is_letter_flow(flow) -> bool:
    reload_config()
    path = flow.request.path or ""
    if flow.request.pretty_host in DISPATCH_HOSTS:
        return True
    return path.startswith(LISTENER["path_prefix"])


def endpoint(path: str) -> str:
    return path[len(LISTENER["path_prefix"]):].split("?")[0]


def json_response(data, status=200):
    if isinstance(data, dict) and "code" not in data:
        data = {"code": 0, "message": "", "data": data}
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return http.Response.make(
        status,
        body,
        {"Content-Type": "application/json; charset=utf-8"},
    )


def current_ts():
    return int(time.time())


def http_json_request(url, payload, api_key, timeout=180, extra_headers=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % api_key,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_json_get(url, api_key=None, timeout=180):
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_download(url, api_key=None, timeout=300):
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def gen_video_openai(prompt):
    cfg = VIDEO_CFG
    base = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "sora-2")
    timeout = cfg.get("timeout", 600)
    body = {"model": model, "prompt": prompt}
    data = http_json_request(base + "/videos", body, key, timeout=60)
    video_id = data.get("id") or data.get("data", {}).get("id")
    if not video_id:
        raise RuntimeError("openai video create: no id in %r" % (data,))
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(15)
        data = http_json_request(base + "/videos/" + video_id, {}, key, timeout=60)
        status = data.get("status")
        if status == "completed":
            return http_download(base + "/videos/" + video_id + "/content", key, timeout=300)
        if status == "failed":
            raise RuntimeError("openai video failed: %r" % (data,))
    raise RuntimeError("openai video timeout")


def gen_video_minimax(prompt):
    cfg = VIDEO_CFG
    base = cfg.get("base_url", "https://api.minimaxi.com/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "MiniMax-H3")
    timeout = cfg.get("timeout", 600)
    resolution = cfg.get("resolution", "768P")
    duration = int(cfg.get("duration", 5))
    ratio = cfg.get("ratio", "16:9")
    if base.endswith("/v1"):
        base = base[:-3]
    # V2 接口（MiniMax-H3 等新模型）
    if model.lower().startswith("minimax-h") or model.lower() in ("minimax-hailuo-03",):
        body = {
            "model": model,
            "content": [{"type": "text", "text": prompt}],
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }
        data = http_json_request(base + "/v2/video_generation", body, key, timeout=60)
        task_id = data.get("task_id") or data.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError("minimax v2 video create: no task_id in %r" % (data,))
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(10)
            data = http_json_get(base + "/v2/query/video_generation/" + task_id, key, timeout=60)
            task = data.get("task", data)
            status = str(task.get("status", "")).lower()
            if status == "succeeded":
                url = (task.get("content") or {}).get("url")
                if not url:
                    raise RuntimeError("minimax v2 video succeeded but no url: %r" % (task,))
                return http_download(url, None, timeout=300)
            if status in ("failed", "cancelled", "canceled"):
                raise RuntimeError("minimax v2 video failed: %r" % (task,))
        raise RuntimeError("minimax v2 video timeout")
    # 旧 V1 接口（Hailuo 2.x / 02 等历史模型）
    body = {"model": model, "prompt": prompt}
    data = http_json_request(base + "/v1/video_generation", body, key, timeout=60)
    task_id = data.get("task_id") or data.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError("minimax video create: no task_id in %r" % (data,))
    deadline = time.time() + timeout
    file_id = None
    while time.time() < deadline:
        time.sleep(15)
        data = http_json_request(base + "/v1/query/video_generation?task_id=" + task_id, {}, key, timeout=60)
        inner = data.get("data", data)
        status = str(inner.get("status", "")).lower()
        file_id = inner.get("file_id") or inner.get("fileId")
        if status in ("success", "succeeded", "complete", "completed"):
            break
        if status in ("failed", "error"):
            raise RuntimeError("minimax video failed: %r" % (data,))
    if not file_id:
        raise RuntimeError("minimax video: no file_id after polling")
    return http_download(base + "/v1/files/retrieve?file_id=" + file_id, key, timeout=300)


def gen_video_volc(prompt):
    cfg = VIDEO_CFG
    base = cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "doubao-seedance-1-5-pro-251215")
    timeout = cfg.get("timeout", 600)
    body = {"model": model, "content": [{"type": "text", "text": prompt}]}
    data = http_json_request(base + "/contents/generations/tasks", body, key, timeout=60)
    task_id = data.get("id") or data.get("data", {}).get("id")
    if not task_id:
        raise RuntimeError("volc video create: no id in %r" % (data,))
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(15)
        data = http_json_request(base + "/contents/generations/tasks/" + task_id, {}, key, timeout=60)
        status = str(data.get("status", "")).lower()
        if status == "succeeded":
            content = data.get("content", {})
            video_url = content.get("video_url") if isinstance(content, dict) else None
            if not video_url:
                raise RuntimeError("volc video succeeded but no video_url: %r" % (data,))
            return http_download(video_url, key, timeout=300)
        if status in ("failed", "canceled", "cancelled"):
            raise RuntimeError("volc video failed: %r" % (data,))
    raise RuntimeError("volc video timeout")


def gen_video_scnet(prompt):
    cfg = VIDEO_CFG
    base = cfg.get("base_url", "https://api.scnet.cn/api/llm/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "Seedance2.0")
    timeout = cfg.get("timeout", 600)
    resolution = cfg.get("resolution", "720p")
    ratio = cfg.get("ratio", "16:9")
    duration = int(cfg.get("duration", 5))
    params = {"resolution": resolution, "ratio": ratio, "duration": duration}
    if cfg.get("watermark") is not None:
        params["watermark"] = bool(cfg.get("watermark"))
    body = {"model": model, "input": {"prompt": prompt}, "parameters": params}
    headers = {"X-MultiModal-Async": "true"}
    data = http_json_request(base + "/videos/generations", body, key, timeout=60, extra_headers=headers)
    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("scnet video create: no task_id in %r" % (data,))
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(10)
        data = http_json_get(base + "/tasks/" + task_id, key, timeout=60)
        output = data.get("output", data)
        status = str(output.get("task_status", "")).lower()
        if status == "succeeded":
            results = output.get("results") or []
            if not results:
                raise RuntimeError("scnet video succeeded but no results: %r" % (output,))
            return http_download(results[0], None, timeout=300)
        if status in ("failed", "cancelled", "canceled"):
            raise RuntimeError("scnet video failed: %r" % (output,))
    raise RuntimeError("scnet video timeout")


def gen_video(prompt):
    reload_config()
    provider = VIDEO_CFG.get("provider", "minimax").lower()
    if provider == "openai":
        return gen_video_openai(prompt)
    if provider == "volcengine" or provider == "volc":
        return gen_video_volc(prompt)
    if provider == "scnet" or provider == "sc":
        return gen_video_scnet(prompt)
    return gen_video_minimax(prompt)


def tts_openai(text):
    cfg = TTS_CFG
    base = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "gpt-4o-mini-tts")
    voice = cfg.get("voice", "coral")
    body = {"model": model, "input": text, "voice": voice}
    headers = {"Content-Type": "application/json", "Authorization": "Bearer %s" % key}
    req = urllib.request.Request(base + "/audio/speech", data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def tts_minimax(text):
    cfg = TTS_CFG
    base = cfg.get("base_url", "https://api.minimaxi.com/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "speech-2.6-hd")
    voice = cfg.get("voice", "female-tianmei")
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "output_format": "hex",
    }
    data = http_json_request(base + "/t2a_v2", body, key, timeout=180)
    audio = (data.get("data") or {}).get("audio") or data.get("audio_file") or data.get("data", {}).get("audio_file")
    if not audio:
        raise RuntimeError("minimax tts: no audio in %r" % (data,))
    if not isinstance(audio, str):
        return audio
    audio = audio.strip()
    # 兼容 hex 与 base64 两种编码（音频数据不会是纯 ASCII 可读文本）
    try:
        if len(audio) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in audio):
            return bytes.fromhex(audio)
    except Exception:
        pass
    return base64.b64decode(audio)


def tts_volc(text):
    cfg = TTS_CFG
    app_id = cfg.get("app_id", "")
    token = cfg.get("access_token", "")
    model = cfg.get("model", "seed-tts-2.0")
    voice = cfg.get("voice", "zh_female_vv_uranus_bigtts")
    reqid = uuid.uuid4().hex
    payload = {
        "app": {"appid": app_id, "token": token, "cluster": "volcano_tts"},
        "user": {"uid": "olivia_letter"},
        "audio": {"voice_type": voice, "encoding": "mp3", "speed_ratio": 1.0, "volume_ratio": 1.0, "pitch_ratio": 1.0},
        "request": {"reqid": reqid, "text": text, "text_type": "plain", "operation": "query", "with_frontend": 1},
    }
    url = cfg.get("base_url", "https://openspeech.bytedance.com/api/v1/tts").rstrip("/")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer; " + token}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if str(data.get("code")) != "30000000":
        raise RuntimeError("volc tts failed: %r" % (data,))
    audio = data.get("data")
    if not audio:
        raise RuntimeError("volc tts: no data in %r" % (data,))
    return base64.b64decode(audio)


def tts_scnet(text):
    cfg = TTS_CFG
    base = cfg.get("base_url", "https://api.scnet.cn/api/llm/v1").rstrip("/")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "Qwen3-TTS-Instruct-Flash")
    voice = cfg.get("voice", "Cherry")
    body = {"model": model, "input": {"text": text, "voice": voice}}
    data = http_json_request(base + "/audios/generations", body, key, timeout=180)
    output = data.get("output", data)
    results = output.get("results") or []
    if not results:
        raise RuntimeError("scnet tts: no results in %r" % (data,))
    return http_download(results[0], None, timeout=180)


def tts_synthesize(text):
    reload_config()
    provider = TTS_CFG.get("provider", "minimax").lower()
    if provider == "openai":
        return tts_openai(text)
    if provider == "volcengine" or provider == "volc":
        return tts_volc(text)
    if provider == "scnet" or provider == "sc":
        return tts_scnet(text)
    return tts_minimax(text)


def get_ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def merge_audio_into_video(video_bytes, audio_bytes, out_path):
    ffmpeg = get_ffmpeg_exe()
    workdir = os.path.dirname(out_path)
    vp = os.path.join(workdir, "_v" + uuid.uuid4().hex + ".mp4")
    ap = os.path.join(workdir, "_a" + uuid.uuid4().hex + ".mp3")
    with open(vp, "wb") as f:
        f.write(video_bytes)
    with open(ap, "wb") as f:
        f.write(audio_bytes)
    try:
        cmd = [ffmpeg, "-y", "-i", vp, "-i", ap, "-c:v", "copy", "-c:a", "aac",
               "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-movflags", "+faststart", out_path]
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
    finally:
        for p in (vp, ap):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


class _VideoHandler(_http_server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=VIDEO_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass


_video_server_ref = None


def ensure_video_server():
    global _video_server_ref
    if _video_server_ref is not None:
        return
    try:
        if not os.path.isdir(VIDEO_DIR):
            os.makedirs(VIDEO_DIR, exist_ok=True)
        server = _socketserver.ThreadingTCPServer((VIDEO_HOST, VIDEO_PORT), _VideoHandler)
        _video_server_ref = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        ctx.log.info("video server started on %s:%d" % (VIDEO_HOST, VIDEO_PORT))
    except Exception as e:
        ctx.log.warn("video server start failed: %s" % e)


def video_url_for(letter_id):
    return "http://%s:%d/%s.mp4" % (VIDEO_HOST, VIDEO_PORT, letter_id)


def generate_video_reply(letter_id, reply_text):
    try:
        ensure_video_server()
        prompt = reply_text[:500]
        video_bytes = gen_video(prompt)
        out_path = os.path.join(VIDEO_DIR, letter_id + ".mp4")
        if TTS_ENABLED:
            try:
                audio_bytes = tts_synthesize(reply_text[:1000])
                merge_audio_into_video(video_bytes, audio_bytes, out_path)
            except Exception as e:
                ctx.log.warn("video %s tts/merge failed, use silent video: %s" % (letter_id, e))
                with open(out_path, "wb") as f:
                    f.write(video_bytes)
        else:
            with open(out_path, "wb") as f:
                f.write(video_bytes)
        with state["lock"]:
            letter = state["letters"].get(letter_id)
            if letter:
                letter["reply_type"] = REPLY_TYPE_MIX_PLAY
                letter["reply_video_url"] = video_url_for(letter_id)
                letter["video_ready"] = True
                save_data()
        ctx.log.info("video %s generated" % letter_id)
    except Exception as e:
        with state["lock"]:
            letter = state["letters"].get(letter_id)
            if letter:
                letter["video_ready"] = False
                letter["video_fail"] = str(e)[:200]
                save_data()
        ctx.log.warn("video %s generation failed: %s" % (letter_id, e))


def letter_to_detail(letter):
    replied = letter["status"] == LETTER_STATUS_REPLIED
    reply_type = letter.get("reply_type", REPLY_TYPE_TEXT if replied else REPLY_TYPE_NONE)
    result = {
        "letterId": letter["id"],
        "isRead": 0 if letter.get("unread") else 1,
        "letterStatus": letter["status"],
        "auditStatus": AUDIT_PASSED,
        "summary": letter["summary"],
        "createdAt": letter["created_at"],
        "material": {"stampId": letter.get("stampId", "s1"), "paperId": ""},
        "content": letter["content"],
        "replyType": reply_type,
    }
    if replied:
        result["repliedAt"] = letter.get("replied_at") or letter["created_at"]
        result["replyText"] = letter.get("reply_text", "")
        if letter.get("reply_video_url"):
            result["replyVideoUrl"] = letter["reply_video_url"]
    return result


def letter_to_list_item(letter):
    replied = letter["status"] == LETTER_STATUS_REPLIED
    reply_type = letter.get("reply_type", REPLY_TYPE_TEXT if replied else REPLY_TYPE_NONE)
    result = {
        "letterId": letter["id"],
        "isRead": 0 if letter.get("unread") else 1,
        "letterStatus": letter["status"],
        "auditStatus": AUDIT_PASSED,
        "summary": letter["summary"],
        "createdAt": letter["created_at"],
        "replyType": reply_type,
    }
    if replied:
        result["repliedAt"] = letter.get("replied_at") or letter["created_at"]
        if letter.get("reply_video_url"):
            result["replyVideoUrl"] = letter["reply_video_url"]
    return result


def count_unread():
    return sum(1 for L in state["letters"].values() if L.get("unread"))


def call_openai(user_text):
    reload_config()
    url = OPENAI["base_url"].rstrip("/") + "/chat/completions"
    messages = [{"role": "system", "content": PERSONA["system_prompt"]}]
    messages += build_memory_messages()
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": OPENAI["model"],
        "temperature": OPENAI.get("temperature", 0.9),
        "max_tokens": OPENAI.get("max_tokens", 500),
        "messages": messages,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % OPENAI["api_key"],
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def generate_reply(letter_id, content):
    reload_config()
    delay = PERSONA.get("reply_delay_seconds", 20)
    time.sleep(delay)
    try:
        reply = call_openai(content)
        with state["lock"]:
            letter = state["letters"].get(letter_id)
            if not letter:
                return
            letter["status"] = LETTER_STATUS_REPLIED
            letter["replied_at"] = current_ts()
            letter["reply_text"] = reply
            letter["reply_type"] = REPLY_TYPE_TEXT
            save_data()
        remember("assistant", reply)
        compress_memory()
        ctx.log.info("letter %s replied (len=%d)" % (letter_id, len(reply)))
        if VIDEO_ENABLED and random.random() < VIDEO_PROBABILITY:
            ctx.log.info("letter %s triggering video reply" % letter_id)
            threading.Thread(target=generate_video_reply, args=(letter_id, reply), daemon=True).start()
    except Exception as e:
        with state["lock"]:
            letter = state["letters"].get(letter_id)
            if letter:
                letter["status"] = LETTER_STATUS_FAILED
                letter["fail_reason"] = str(e)
                save_data()
        ctx.log.warn("letter %s generation failed: %s" % (letter_id, e))


load_data()
seed_data()
load_memory()


LOGIN_PATHS = ("/signIn", "/login", "/signout")


class OliviaLetterProxy:
    def request(self, flow: http.HTTPFlow) -> None:
        reload_config()
        host = flow.request.pretty_host
        path = flow.request.path or ""
        is_dispatch = (
            host in DISPATCH_HOSTS
            or ("olivia.miyoushe.com" in host and "dispatch" in (path or "").lower())
            or ("dispatcher" in host.lower() and "olivia" in host.lower())
        )
        if is_dispatch:
            if DISPATCH_ENC_CONF:
                data = {"enc_conf": DISPATCH_ENC_CONF}
                resp = {"code": 0, "message": "ok", "data": data}
            else:
                resp = {
                    "code": 0,
                    "message": "",
                    "data": {
                        "features": {},
                        "config": {},
                        "flags": {},
                    },
                }
            flow.response = json_response(resp)
            print("DISPATCH HANDLED %s %s" % (flow.request.method, path), flush=True)
            return

        if any(path.startswith(p) for p in LOGIN_PATHS):
            flow.response = json_response({"code": 0, "message": "", "data": {}})
            print("LOGIN MOCK %s %s" % (flow.request.method, path), flush=True)
            return

        if not is_letter_flow(flow):
            return
        ep = endpoint(flow.request.path)
        method = flow.request.method.upper()
        print("INTERCEPT %s %s path=%r" % (method, ep, flow.request.path), flush=True)

        if method == "POST" and ep == "send":
            try:
                body = json.loads(flow.request.get_text() or "{}")
            except Exception:
                body = {}
            content = (body.get("content") or "").strip()
            if not content:
                flow.response = json_response({"code": 400, "message": "empty content"})
                return
            material = body.get("material") or {}
            stamp_id = (material.get("stampId") or "s1").strip()
            with state["lock"]:
                state["seq"] += 1
                letter_id = str(state["seq"])
                state["letters"][letter_id] = {
                    "id": letter_id,
                    "content": content,
                    "summary": content[:50] + ("..." if len(content) > 50 else ""),
                    "stampId": stamp_id,
                    "created_at": current_ts(),
                    "status": LETTER_STATUS_PENDING,
                    "unread": False,
                    "reply_text": "",
                }
                save_data()
            threading.Thread(target=generate_reply, args=(letter_id, content), daemon=True).start()
            remember("user", content)
            flow.response = json_response({"letterId": letter_id})

        elif method == "GET" and ep == "list":
            page_size = int(flow.request.query.get("pageSize") or flow.request.query.get("page_size") or "20")
            with state["lock"]:
                items = [letter_to_list_item(L) for L in sorted(
                    state["letters"].values(), key=lambda x: x["created_at"], reverse=True)]
                total = len(items)
                today = time.strftime("%Y-%m-%d", time.localtime())
                sent_today = sum(1 for L in state["letters"].values()
                                 if time.strftime("%Y-%m-%d", time.localtime(L["created_at"])) == today)
                remaining = max(0, PERSONA["max_daily_letters"] - sent_today)
                page = items[:page_size]
            resp = {
                "list": page,
                "total": total,
                "remainingToday": remaining,
                "nextCursor": "",
                "hasMore": False,
            }
            with open(os.path.join(BASE_DIR, "debug.log"), "a", encoding="utf-8") as f:
                f.write("LIST RETURNED: %s (query=%s)\n" % (json.dumps(resp, ensure_ascii=False), dict(flow.request.query)))
            flow.response = json_response(resp)

        elif method == "GET" and ep == "detail":
            letter_id = flow.request.query.get("letterId") or flow.request.query.get("letter_id", "")
            with state["lock"]:
                letter = state["letters"].get(letter_id)
                if not letter:
                    flow.response = json_response({"code": 404, "message": "letter not found"})
                    return
                letter["unread"] = False
                save_data()
                detail = letter_to_detail(letter)
            flow.response = json_response(detail)

        elif method == "GET" and ep == "unread_count":
            flow.response = json_response({"unreadCount": count_unread()})

        elif method == "POST" and ep == "share":
            letter_id = flow.request.query.get("letterId") or flow.request.query.get("letter_id", "")
            flow.response = json_response({"shareId": uuid.uuid4().hex})

        elif method == "POST" and ep == "resend":
            try:
                body = json.loads(flow.request.get_text() or "{}")
            except Exception:
                body = {}
            letter_id = body.get("letterId") or body.get("letter_id") or flow.request.query.get("letterId", "")
            with state["lock"]:
                letter = state["letters"].get(letter_id)
                if not letter:
                    flow.response = json_response({"code": 404, "message": "letter not found"})
                    return
                letter["status"] = LETTER_STATUS_PENDING
                letter["reply_text"] = ""
                save_data()
                content = letter["content"]
            threading.Thread(target=generate_reply, args=(letter_id, content), daemon=True).start()
            remember("user", content)
            flow.response = json_response({"ok": True})

        else:
            flow.response = json_response({"code": 404, "message": "no such endpoint"})


addons = [OliviaLetterProxy()]
