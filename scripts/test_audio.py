import base64, json, urllib.request

with open("/tmp/test.wav", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "prompt": "What is being said?",
    "audio_data": b64,
    "n_predict": 200,
}

req = urllib.request.Request(
    "http://127.0.0.1:8081/completion",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)

with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.loads(resp.read())
    print(data.get("content", data))