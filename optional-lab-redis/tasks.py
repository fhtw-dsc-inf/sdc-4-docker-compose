import time


def build_report(name: str, delay: float = 2) -> dict:
    # Stand in for slow work, such as creating a report or generating an image.
    time.sleep(delay)
    if name == "FAIL":
        raise ValueError("Intentional demo error")
    return {"title": name, "message": "Your report is ready."}
