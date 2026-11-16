import os

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from tasks import build_report

app = FastAPI(title="HTTP Job Queue Tutorial")
connection = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
queue = Queue("reports", connection=connection)


class ReportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    delay: float = Field(default=2, ge=0, le=5)


@app.exception_handler(RedisError)
async def queue_unavailable(request, exc):
    # Never claim that a job was accepted if Redis could not store it.
    return JSONResponse(status_code=503, content={"detail": "The queue is unavailable."})


@app.post("/reports/sync")
def report_sync(request: ReportRequest):
    # The HTTP request stays open until the report is ready.
    return build_report(request.name, request.delay)


@app.post("/reports", status_code=202)
def enqueue_report(request: ReportRequest, response: Response):
    # Store the job and respond immediately. A separate worker does the work.
    job = queue.enqueue(build_report, request.name, request.delay)
    status_url = f"/reports/{job.id}"
    response.headers["Location"] = status_url
    return {"job_id": job.id, "status_url": status_url}


@app.get("/reports/{job_id}")
def report_status(job_id: str):
    try:
        job = Job.fetch(job_id, connection=connection)
    except NoSuchJobError:
        raise HTTPException(status_code=404, detail="Job not found or no longer available.")
    if job.origin != queue.name:
        raise HTTPException(status_code=404, detail="Job not found in this queue.")

    # Give clients simple, consistent job states instead of library-specific names.
    state = job.get_status(refresh=True)
    state = {
        "started": "running",
        "finished": "succeeded",
        "stopped": "failed",
        "canceled": "failed",
    }.get(state, state)
    body = {"job_id": job.id, "status": state}
    if state == "succeeded":
        body["result"] = job.return_value()
    elif state == "failed":
        body["error"] = "The report could not be created."
    return body
