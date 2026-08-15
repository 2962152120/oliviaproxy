import json
import threading
import time
import urllib.request
import uuid

from mitmproxy import http, ctx

CONFIG_PATH = r"D:\OliviaProxy\config.json"
DATA_PATH = r"D:\OliviaProxy\letters.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

OPENAI = CONFIG["openai"]
PERSONA = CONFIG["persona"]
LISTENER = CONFIG["listener"]

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


def is_letter_flow(flow) -> bool:
    path = flow.request.path or ""
    with open(r"D:\OliviaProxy\debug.log", "a", encoding="utf-8") as f:
        f.write("probe host=%r pretty=%r path=%r\n" % (flow.request.host, flow.request.pretty_host, path))
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
    payload = {
        "model": OPENAI["model"],
        "temperature": OPENAI.get("temperature", 0.9),
        "max_tokens": OPENAI.get("max_tokens", 500),
        "messages": [
            {"role": "system", "content": PERSONA["system_prompt"]},
            {"role": "user", "content": user_text},
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


class OliviaLetterProxy:
    def request(self, flow: http.HTTPFlow) -> None:
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
            flow.response = json_response({"letterId": letter_id})

        elif method == "GET" and ep == "list":
            page_size = int(flow.request.query.get("pageSize") or flow.request.query.get("page_size") or "20")
            with state["lock"]:
                items = [letter_to_list_item(L) for L in sorted(
                    state["letters"].values(), key=lambda x: x["created_at"], reverse=True)]
                total = len(items)
                remaining = max(0, PERSONA["max_daily_letters"] - len(state["letters"]))
                page = items[:page_size]
            resp = {
                "list": page,
                "total": total,
                "remainingToday": remaining,
                "nextCursor": "",
                "hasMore": False,
            }
            with open(r"D:\OliviaProxy\debug.log", "a", encoding="utf-8") as f:
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
            letter_id = body.get("letterId", "")
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
            flow.response = json_response({"ok": True})

        else:
            flow.response = json_response({"code": 404, "message": "no such endpoint"})


addons = [OliviaLetterProxy()]
