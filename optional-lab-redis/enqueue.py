import os
import sys

from redis import Redis
from rq import Queue

from tasks import build_report


if __name__ == "__main__":
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    queue = Queue("reports", connection=connection)
    name = sys.argv[1] if len(sys.argv) > 1 else "Monthly report"

    # Enqueue the function call. The worker, not this script, will run it.
    job = queue.enqueue(build_report, name)
    print("Job queued. Job ID:", job.id)
