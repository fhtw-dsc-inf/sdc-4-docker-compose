import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue, Worker

import dependencies
from app import app

pytestmark = pytest.mark.skipif(not os.getenv('REDIS_TEST_URL'), reason='Set REDIS_TEST_URL to a test Redis instance')


@pytest.mark.parametrize('fail', [False, True])
def test_queued_image_with_real_worker(monkeypatch, tmp_path, fail):
    import io
    from PIL import Image

    output = io.BytesIO()
    Image.new('RGBA', (8, 8), (0, 255, 0, 128)).save(output, 'PNG')

    class Generator:
        def generate_image(self, prompt):
            if fail:
                raise ValueError('simulated provider failure')
            return output.getvalue()

    connection = Redis.from_url(os.environ['REDIS_TEST_URL'])
    queue = Queue('backend-test-' + uuid4().hex, connection=connection)
    monkeypatch.setenv('UPLOAD_FOLDER', str(tmp_path / 'images'))
    monkeypatch.setattr(dependencies, 'get_image_generator', Generator)
    app.dependency_overrides[dependencies.get_queue] = lambda: queue
    try:
        with TestClient(app) as client:
            response = client.post('/v3/images', json={'userPrompt': 'a lighthouse'})
            assert response.status_code == 200
            image_id = response.json()['img_id']
            assert client.get(f'/images/{image_id}').status_code == 202
            job = queue.jobs[0]
        # Close TestClient's thread before starting the actual forking worker.
        Worker([queue], connection=connection).work(burst=True)
        job.refresh()
        assert job.is_failed if fail else job.is_finished
        with TestClient(app) as client:
            assert client.get(f'/images/{image_id}').status_code == (502 if fail else 200)
        job.delete()
    finally:
        app.dependency_overrides.clear()
        queue.delete()
        connection.close()
