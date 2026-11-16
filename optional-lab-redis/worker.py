import os

from redis import Redis
from rq import Worker


if __name__ == "__main__":
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    # Wait for jobs in the same queue used by enqueue.py and app.py.
    Worker(["reports"], connection=connection).work()
