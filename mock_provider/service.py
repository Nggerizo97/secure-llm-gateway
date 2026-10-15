"""Stand-in for the company's LLM provider: an OpenAI-compatible API with a token budget.

Returns a real HTTP 429 once the budget is used up, like a real provider, so the gateway's
fallback can be demonstrated over real HTTP without spending real tokens.
Synthetic responses only; listens on 127.0.0.1 only.

    python -m mock_provider.service --port 8900 --tokens-per-minute 120
"""

import argparse
import threading
import time
from typing import Callable, Optional
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse


def create_app(
    tokens_per_minute: int = 120,
    mode: str = "rate_limit",
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """mode="rate_limit": budget resets every minute (429 rate_limit_exceeded).
    mode="quota": budget never resets (429 insufficient_quota, like an exhausted billing budget).
    """
    app = FastAPI(title="Mock company LLM provider")
    state = {"window_start": clock(), "used": 0}
    lock = threading.Lock()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, authorization: Optional[str] = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "invalid_api_key", "message": "Missing or invalid API key"}},
            )

        body = await request.json()
        messages = body.get("messages") or []
        prompt = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
        model = str(body.get("model") or "company-model")
        content = f"[{model}] Synthetic answer from the company provider."
        prompt_tokens = max(1, len(prompt.split()))
        completion_tokens = len(content.split())

        with lock:
            now = clock()
            if mode == "rate_limit" and now - state["window_start"] >= 60:
                state["window_start"], state["used"] = now, 0
            if state["used"] + prompt_tokens + completion_tokens > tokens_per_minute:
                code = "insufficient_quota" if mode == "quota" else "rate_limit_exceeded"
                retry_after = max(1, int(60 - (now - state["window_start"])))
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={
                        "error": {
                            "code": code,
                            "type": code,
                            "message": f"Token budget of {tokens_per_minute} per minute exhausted",
                        }
                    },
                )
            state["used"] += prompt_tokens + completion_tokens
            remaining = tokens_per_minute - state["used"]

        return JSONResponse(
            headers={"x-ratelimit-remaining-tokens": str(remaining)},
            content={
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            },
        )

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Mock company LLM provider with a token budget")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--tokens-per-minute", type=int, default=120)
    parser.add_argument("--mode", choices=["rate_limit", "quota"], default="rate_limit")
    args = parser.parse_args()

    print(
        f"Mock company provider on http://127.0.0.1:{args.port}/v1 "
        f"(budget {args.tokens_per_minute} tokens, mode {args.mode})"
    )
    app = create_app(tokens_per_minute=args.tokens_per_minute, mode=args.mode)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
