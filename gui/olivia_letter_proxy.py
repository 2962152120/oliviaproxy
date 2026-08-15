import json
import os
import threading
import time
import urllib.request
import uuid

from mitmproxy import http, ctx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_PATH = os.path.join(BASE_DIR, "letters.json")
MEMORY_PATH = os.path.join(BASE_DIR, "memory.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

OPENAI = CONFIG["openai"]
PERSONA = CONFIG["persona"]
LISTENER = CONFIG["listener"]
MEMORY = CONFIG.get("memory", {})
MEMORY_MAX_ENTRIES = MEMORY.get("max_entries", 30)
MEMORY_MAX_CHARS = MEMORY.get("max_chars", 3000)
DISPATCH_ENC_CONF = CONFIG.get("dispatch", {}).get("enc_conf", "")

LETTER_STATUS_PENDING = 1
LETTER_STATUS_AUDITING = 2
LETTER_STATUS_LLM_PROCESSING = 3
LETTER_STATUS_REPLIED = 4
LETTER_STATUS_FAILED = 5

AUDIT_PASSED = 2
REPLY_TYPE_NONE = 0
REPLY_TYPE_TEXT = 1

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


def letter_to_detail(letter):
    replied = letter["status"] == LETTER_STATUS_REPLIED
    result = {
        "letterId": letter["id"],
        "isRead": 0 if letter.get("unread") else 1,
        "letterStatus": letter["status"],
        "auditStatus": AUDIT_PASSED,
        "summary": letter["summary"],
        "createdAt": letter["created_at"],
        "material": {"stampId": letter.get("stampId", "s1"), "paperId": ""},
        "content": letter["content"],
        "replyType": REPLY_TYPE_TEXT if replied else REPLY_TYPE_NONE,
    }
    if replied:
        result["repliedAt"] = letter.get("replied_at") or letter["created_at"]
        result["replyText"] = letter.get("reply_text", "")
    return result


def letter_to_list_item(letter):
    replied = letter["status"] == LETTER_STATUS_REPLIED
    result = {
        "letterId": letter["id"],
        "isRead": 0 if letter.get("unread") else 1,
        "letterStatus": letter["status"],
        "auditStatus": AUDIT_PASSED,
        "summary": letter["summary"],
        "createdAt": letter["created_at"],
        "replyType": REPLY_TYPE_TEXT if replied else REPLY_TYPE_NONE,
    }
    if replied:
        result["repliedAt"] = letter.get("replied_at") or letter["created_at"]
    return result


def count_unread():
    return sum(1 for L in state["letters"].values() if L.get("unread"))


def call_openai(user_text):
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
            save_data()
        remember("assistant", reply)
        compress_memory()
        ctx.log.info("letter %s replied (len=%d)" % (letter_id, len(reply)))
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
        host = flow.request.pretty_host
        path = flow.request.path or ""
        if host in DISPATCH_HOSTS:
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
