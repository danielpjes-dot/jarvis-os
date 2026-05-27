import base64, json, urllib.request

with open("/mnt/e/coding/jarvis-os/app/public/Screenshot.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "model": "gemma4",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What do you see?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }
    ]
}

req = urllib.request.Request(
    "http://127.0.0.1:8081/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)

with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.loads(resp.read())
    print(data["choices"][0]["message"]["content"])