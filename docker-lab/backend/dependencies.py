import os
from pathlib import Path

import redis
from dotenv import load_dotenv
from fastapi import HTTPException
from rq import Queue

from gpt_service import GPTService
from image_generator import ImageGenerator

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / '.env')


def backend_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BACKEND_DIR / path


def required_api_key(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"Configure {name} in backend/.env.")
    return value


def read_prompt_file(prompt_file: str):
    return backend_path(prompt_file).read_text(encoding="utf-8")


def get_profanity_prompt():
    return read_prompt_file(os.getenv('PROFANITY_PROMPT_FILE', 'profanity_prompt.txt'))


def get_gpt_service() -> GPTService:
    return GPTService(openai_api_key=required_api_key("OPENAI_API_KEY"),
                      profanity_prompt=get_profanity_prompt())


def get_profanity_violation() -> str:
    return ("Please refrain from using language or requesting content that may be offensive, discriminatory,"
            " or otherwise inappropriate.")


def get_image_generator():
    return ImageGenerator(required_api_key('STABILITY_KEY'))


def get_redis_connection():
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return redis.from_url(redis_url, socket_connect_timeout=5)


def get_queue():
    return Queue(connection=get_redis_connection())


def get_upload_folder():
    return str(backend_path(os.getenv('UPLOAD_FOLDER', 'images')))
