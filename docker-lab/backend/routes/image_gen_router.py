import logging
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, Response
from openai import OpenAIError
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from rq import Queue

import worker
from dependencies import (
    get_gpt_service, get_image_generator, get_profanity_violation,
    get_queue, get_upload_folder,
)
from gpt_service import GPTService
from image_generator import ImageGenerator
from image_generator.storage import mark_failed, save_image

router = APIRouter()
logger = logging.getLogger(__name__)
GENERATION_ERROR = "Image generation failed. Check the API keys, credits and backend/worker logs."


class ImageModel(BaseModel):
    userPrompt: str = Field(min_length=1, max_length=9000)


@router.get('/images/{image_id}')
def get_image(image_id: UUID, upload_folder: str = Depends(get_upload_folder)):
    folder = Path(upload_folder)
    file_path = folder / f'{image_id}.jpeg'
    if file_path.is_file():
        return FileResponse(file_path, media_type="image/jpeg")
    if (folder / f'{image_id}.failed').exists():
        raise HTTPException(status_code=502, detail=GENERATION_ERROR)
    return JSONResponse({"status": "processing"}, status_code=status.HTTP_202_ACCEPTED)


@router.post('/images')
def post_image(
    request: ImageModel,
    gpt_service: GPTService = Depends(get_gpt_service),
    profanity_violation: str = Depends(get_profanity_violation),
    image_generator: ImageGenerator = Depends(get_image_generator),
):
    try:
        if gpt_service.contains_profanity(request.userPrompt):
            raise HTTPException(status_code=400, detail=profanity_violation)
        image_binary = image_generator.generate_image(request.userPrompt)
    except (OpenAIError, httpx.HTTPError, ValueError):
        logger.exception("Image generation failed")
        raise HTTPException(status_code=502, detail=GENERATION_ERROR)
    return Response(content=image_binary, media_type="image/png")


@router.post('/v2/images')
def post_background_image(
    request: ImageModel,
    background_tasks: BackgroundTasks,
    image_generator: ImageGenerator = Depends(get_image_generator),
    upload_folder: str = Depends(get_upload_folder),
):
    image_id = str(uuid4())
    background_tasks.add_task(
        gen_image_task, image_generator, image_id, request.userPrompt, upload_folder,
    )
    return {"img_id": image_id}


def gen_image_task(image_generator: ImageGenerator, image_id: str, user_prompt: str,
                   upload_folder: str):
    try:
        save_image(image_generator.generate_image(user_prompt), image_id, upload_folder)
    except Exception:
        mark_failed(image_id, upload_folder)
        logger.exception("Background image generation failed for %s", image_id)


@router.post('/v3/images')
def post_queued_image(request: ImageModel, queue: Queue = Depends(get_queue)):
    image_id = str(uuid4())
    try:
        queue.enqueue(worker.gen_image_task, image_id, request.userPrompt, job_timeout=180)
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis is unavailable. Start Redis and the worker.")
    return {"img_id": image_id}
