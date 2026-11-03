import io
from pathlib import Path

from PIL import Image


def save_image(image_binary: bytes, image_id: str, upload_folder: str):
    folder = Path(upload_folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{image_id}.jpeg"
    temporary = folder / f"{image_id}.tmp"
    with Image.open(io.BytesIO(image_binary)) as image:
        image.convert("RGB").save(temporary, "JPEG")
    # Polling clients must never receive a partially written image.
    temporary.replace(target)
    (folder / f"{image_id}.failed").unlink(missing_ok=True)


def mark_failed(image_id: str, upload_folder: str):
    folder = Path(upload_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{image_id}.failed").touch()
