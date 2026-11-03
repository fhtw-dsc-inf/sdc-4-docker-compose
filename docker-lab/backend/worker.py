from rq import Worker

import dependencies
from image_generator.storage import mark_failed, save_image

listen = ['high', 'default', 'low']


def profanity_violation(user_prompt: str):
    gpt_service = dependencies.get_gpt_service()
    if gpt_service.contains_profanity(user_prompt):
        return {"detail": dependencies.get_profanity_violation()}


def gen_image_task(image_id: str, user_prompt: str):
    upload_dir = dependencies.get_upload_folder()
    try:
        image_generator = dependencies.get_image_generator()
        save_image(image_generator.generate_image(user_prompt), image_id, upload_dir)
    except Exception:
        mark_failed(image_id, upload_dir)
        raise


if __name__ == '__main__':
    conn = dependencies.get_redis_connection()
    Worker(connection=conn, queues=listen).work()
