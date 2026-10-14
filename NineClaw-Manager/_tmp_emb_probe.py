import httpx

r = httpx.post(
    "http://127.0.0.1:8000/v1/providers/embeddings",
    json={
        "provider_id": "2ea999a8-2ffd-45e6-a3d9-de4c97b8e10e",
        "model": "qwen3.7-text-embedding",
        "input": ["hello", "world"],
    },
    timeout=90.0,
)
print("status", r.status_code)
print(r.text[:1000])
