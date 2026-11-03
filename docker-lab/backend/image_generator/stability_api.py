import httpx


class StabilityApiGenerator:
    endpoint = "https://api.stability.ai/v2beta/stable-image/generate/core"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate_image(self, prompt: str, negative_prompt: str) -> bytes:
        # Text fields also need multipart encoding for the current Stability API.
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "image/*",
            },
            files={
                "prompt": (None, prompt),
                "negative_prompt": (None, negative_prompt),
                "aspect_ratio": (None, "1:1"),
                "output_format": (None, "png"),
            },
            timeout=120.0,
        )
        response.raise_for_status()
        if response.headers.get("finish-reason") == "CONTENT_FILTERED":
            raise ValueError("Stability AI filtered the generated image.")
        if not response.content or not response.headers.get("content-type", "").startswith("image/"):
            raise ValueError("Stability AI did not return an image.")
        return response.content
