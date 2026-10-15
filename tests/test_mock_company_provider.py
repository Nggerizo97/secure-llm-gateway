from fastapi.testclient import TestClient
from app.providers.base import QuotaExhaustedError, RateLimitError, classify_http_error
from mock_provider.service import create_app

AUTH = {"Authorization": "Bearer demo-company-key"}
BODY = {"model": "company-model", "messages": [{"role": "user", "content": "one two three"}]}
# 3 prompt tokens + 7 completion tokens ("[company-model] Synthetic answer from the company provider.")
TOKENS_PER_CALL = 10


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_requires_an_api_key():
    client = TestClient(create_app())
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401
    assert client.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer "}).status_code == 401


def test_returns_openai_shaped_completion_with_usage():
    resp = TestClient(create_app()).post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"].startswith("[company-model]")
    assert data["usage"] == {"prompt_tokens": 3, "completion_tokens": 7}


def test_rate_limit_after_budget_then_resets_next_minute():
    clock = FakeClock()
    client = TestClient(create_app(tokens_per_minute=3 * TOKENS_PER_CALL, clock=clock))
    codes = [client.post("/v1/chat/completions", json=BODY, headers=AUTH).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]

    limited = client.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert limited.headers["Retry-After"]
    assert isinstance(classify_http_error("openai_compat", 429, limited.text), RateLimitError)

    clock.now += 61
    assert client.post("/v1/chat/completions", json=BODY, headers=AUTH).status_code == 200


def test_quota_mode_never_resets_and_maps_to_quota_exhausted():
    clock = FakeClock()
    client = TestClient(create_app(tokens_per_minute=TOKENS_PER_CALL, mode="quota", clock=clock))
    assert client.post("/v1/chat/completions", json=BODY, headers=AUTH).status_code == 200

    clock.now += 3600
    exhausted = client.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert exhausted.status_code == 429
    assert isinstance(classify_http_error("openai_compat", 429, exhausted.text), QuotaExhaustedError)
