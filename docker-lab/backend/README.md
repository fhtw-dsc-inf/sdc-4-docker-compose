# Image backend

Use Python 3.11 or newer (tested with Python 3.12). The pinned dependencies are
updated to the versions available on 2026-11-03. The Dockerfiles and Compose
configuration remain exercises; this guide runs the backend locally.

## Start the API

From this directory:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure `OPENAI_API_KEY` and `STABILITY_KEY` in `backend/.env`. If there is no
`.env` yet, copy `.env.example` to `.env`. Existing environment variables take
precedence over the file. Both provider accounts need access and sufficient
credits for generation; v1 uses OpenAI for the prompt filter, while v2 and v3
only require Stability AI, as in the original lab.

```sh
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000/docs> to try the API. `GET /health` checks that the
application is running; it does not call the external providers or Redis.
The existing Streamlit frontend can continue using `API_URL=http://localhost:8000`.

```sh
curl --fail-with-body http://localhost:8000/images \
  -H 'Content-Type: application/json' \
  -d '{"userPrompt":"A lighthouse on a quiet hill"}' \
  --output lighthouse.png
```

## Background tasks and Redis

- `POST /images` runs the prompt filter and returns PNG bytes.
- `POST /v2/images` schedules a FastAPI background task and returns `{"img_id":"..."}`.
- `POST /v3/images` enqueues an RQ job and returns the same response shape.
- `GET /images/{img_id}` returns `202` while pending, JPEG bytes on success, or
  `502` when a background task recorded a failure.

For v3, start Redis and then the worker in another terminal with the same Python
environment and configuration as the API:

```sh
docker run --rm --name sdc4-redis -p 127.0.0.1:6379:6379 redis:7.4-alpine
```

```sh
python worker.py
```

`REDIS_URL` defaults to `redis://localhost:6379/0`. When completing the Docker
exercise, point it at the Redis service name and run a separate worker service.
The API and worker must share the same `UPLOAD_FOLDER`, backed by a shared volume
when containerized. Without a running worker, v3 jobs remain queued.

Relative `UPLOAD_FOLDER` and `PROFANITY_PROMPT_FILE` paths resolve from the backend
directory, regardless of the shell's working directory. Image folders are created
on demand, transparent images are converted to RGB for JPEG storage, and image
files become visible to polling clients only after writing finishes.

## API updates

The OpenAI filter follows the current Lab 2 implementation using typed
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
with `gpt-4o-mini` as the default. Set `OPENAI_MODEL` to another model that supports
structured outputs if needed. Refusals block generation; invalid filter responses
surface an error rather than silently permitting the request.

Image generation uses the current
[Stable Image Core REST API](https://docs.stability.ai/api-reference/generate/stable-image-core)
instead of the legacy gRPC SDK. This keeps the prompt and negative-prompt behavior,
with PNG responses for v1 and JPEG storage for v2/v3. The new image model may
produce different images and uses the provider's current pricing.

Missing API keys return `503`; provider failures return `502`; unavailable Redis
returns `503`. Check the API or worker logs for the provider's HTTP status, such as
`401` for invalid credentials or `402` for insufficient Stability credits.

## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests use dummy credentials and mock provider responses; they do not use paid APIs.
To also test real Redis queueing and a forking worker on Linux/macOS, start a
separate Redis container and opt in:

```sh
docker run --rm --name sdc4-test-redis -p 127.0.0.1:16379:6379 redis:7.4-alpine
REDIS_TEST_URL=redis://localhost:16379/0 python -m pytest tests -q
```
