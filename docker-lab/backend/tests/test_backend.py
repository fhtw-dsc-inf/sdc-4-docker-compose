import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from PIL import Image
from redis.exceptions import ConnectionError

import dependencies
import worker
from app import app
from gpt_service import GPTService
from image_generator import ImageGenerator
from image_generator.stability_api import StabilityApiGenerator
from image_generator.storage import mark_failed


@pytest.fixture
def png():
    data = io.BytesIO()
    Image.new('RGBA', (8, 8), (255, 0, 0, 128)).save(data, 'PNG')
    return data.getvalue()


@pytest.fixture
def api(tmp_path, png):
    generator = Mock(spec=ImageGenerator)
    generator.generate_image.return_value = png
    gpt = Mock(spec=GPTService)
    gpt.contains_profanity.return_value = False
    queue = Mock()
    folder = tmp_path / 'new' / 'images'
    app.dependency_overrides.update({
        dependencies.get_image_generator: lambda: generator,
        dependencies.get_gpt_service: lambda: gpt,
        dependencies.get_queue: lambda: queue,
        dependencies.get_upload_folder: lambda: str(folder),
    })
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, generator=generator, gpt=gpt, queue=queue, folder=folder)
    app.dependency_overrides.clear()


def test_health_and_openapi(api):
    assert api.client.get('/health').json() == {'status': 'ok'}
    assert api.client.get('/openapi.json').status_code == 200


def test_synchronous_image(api, png):
    response = api.client.post('/images', json={'userPrompt': 'a lighthouse'})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    assert response.content == png


def test_flagged_prompt_does_not_generate_image(api):
    api.gpt.contains_profanity.return_value = True
    assert api.client.post('/images', json={'userPrompt': 'flagged'}).status_code == 400
    api.generator.generate_image.assert_not_called()


def test_provider_failure_is_reported(api):
    api.generator.generate_image.side_effect = httpx.ConnectError('provider unavailable')
    assert api.client.post('/images', json={'userPrompt': 'a lighthouse'}).status_code == 502


def test_background_image_creates_folder_and_converts_rgba(api):
    response = api.client.post('/v2/images', json={'userPrompt': 'a lighthouse'})
    assert response.status_code == 200
    image_id = response.json()['img_id']
    image = api.client.get(f'/images/{image_id}')
    assert image.status_code == 200
    assert image.headers['content-type'] == 'image/jpeg'
    with Image.open(io.BytesIO(image.content)) as result:
        assert result.mode == 'RGB'
    assert (api.folder / f'{image_id}.jpeg').is_file()


def test_background_failure_stops_polling(api):
    api.generator.generate_image.side_effect = ValueError('no image returned')
    response = api.client.post('/v2/images', json={'userPrompt': 'a lighthouse'})
    assert response.status_code == 200
    assert api.client.get('/images/' + response.json()['img_id']).status_code == 502


def test_pending_image(api):
    assert api.client.get(f'/images/{uuid4()}').status_code == 202


def test_invalid_image_id(api):
    assert api.client.get('/images/not-a-uuid').status_code == 422


@pytest.mark.parametrize('route', ['/images', '/v2/images', '/v3/images'])
def test_empty_prompt_is_rejected(api, route):
    assert api.client.post(route, json={'userPrompt': ''}).status_code == 422
    api.generator.generate_image.assert_not_called()
    api.queue.enqueue.assert_not_called()


def test_queued_image_uses_importable_worker_function(api):
    response = api.client.post('/v3/images', json={'userPrompt': 'a lighthouse'})
    assert response.status_code == 200
    api.queue.enqueue.assert_called_once_with(
        worker.gen_image_task, response.json()['img_id'], 'a lighthouse', job_timeout=180,
    )


def test_redis_unavailable(api):
    api.queue.enqueue.side_effect = ConnectionError('Redis not running')
    assert api.client.post('/v3/images', json={'userPrompt': 'a lighthouse'}).status_code == 503


def test_worker_creates_image_and_clears_failure_marker(monkeypatch, tmp_path, png):
    image_id = str(uuid4())
    folder = tmp_path / 'worker-images'
    mark_failed(image_id, str(folder))
    monkeypatch.setattr(dependencies, 'get_upload_folder', lambda: str(folder))
    monkeypatch.setattr(dependencies, 'get_image_generator', lambda: Mock(generate_image=lambda _: png))
    worker.gen_image_task(image_id, 'a lighthouse')
    assert (folder / f'{image_id}.jpeg').is_file()
    assert not (folder / f'{image_id}.failed').exists()


def test_worker_failure_is_recorded(monkeypatch, tmp_path):
    image_id = str(uuid4())
    monkeypatch.setattr(dependencies, 'get_upload_folder', lambda: str(tmp_path))
    monkeypatch.setattr(dependencies, 'get_image_generator', Mock(side_effect=ValueError('missing key')))
    with pytest.raises(ValueError):
        worker.gen_image_task(image_id, 'a lighthouse')
    assert (tmp_path / f'{image_id}.failed').exists()


def test_paths_do_not_depend_on_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PROFANITY_PROMPT_FILE', raising=False)
    monkeypatch.setenv('UPLOAD_FOLDER', 'images')
    assert 'input filter' in dependencies.get_profanity_prompt()
    assert dependencies.get_upload_folder() == str(dependencies.BACKEND_DIR / 'images')


def test_missing_key_gives_configuration_error(api, monkeypatch):
    del app.dependency_overrides[dependencies.get_image_generator]
    monkeypatch.setenv('STABILITY_KEY', '')
    response = api.client.post('/v2/images', json={'userPrompt': 'a lighthouse'})
    assert response.status_code == 503
    assert 'STABILITY_KEY' in response.json()['detail']


@pytest.mark.parametrize('flagged', [False, True])
def test_openai_structured_output_with_real_sdk(monkeypatch, flagged):
    def handler(request):
        payload = json.loads(request.content)
        assert payload['model'] == 'gpt-4o-mini'
        assert payload['response_format']['type'] == 'json_schema'
        return httpx2.Response(200, json={
            'id': 'chatcmpl-test', 'object': 'chat.completion', 'created': 0,
            'model': 'gpt-4o-mini',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps({'flagged': flagged}),
            }}],
        })
    service = GPTService('test-key', 'Return a flagged boolean.')
    service.client.close()
    with OpenAI(api_key='test-key', http_client=httpx2.Client(transport=httpx2.MockTransport(handler))) as client:
        service.client = client
        assert service.contains_profanity('a lighthouse') is flagged


def test_openai_refusal_is_not_treated_as_safe():
    service = GPTService('test-key', 'Return a flagged boolean.')
    service.client.chat.completions.parse = Mock(return_value=SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(refusal='Cannot comply', parsed=None)),
    ]))
    assert service.contains_profanity('test') is True
    service.client.close()


def test_stability_rest_multipart_contract(monkeypatch, png):
    def handler(request):
        assert request.url.path == '/v2beta/stable-image/generate/core'
        assert request.headers['authorization'] == 'Bearer test-key'
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        assert b'name="output_format"\r\n\r\npng' in request.content
        assert b'name="negative_prompt"' in request.content
        return httpx.Response(200, content=png, headers={'content-type': 'image/png'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(httpx, 'post', client.post)
        assert StabilityApiGenerator('test-key').generate_image('a lighthouse', 'blurry') == png


@pytest.mark.parametrize('status_code', [401, 402, 403, 429, 500])
def test_stability_errors_do_not_return_empty_images(monkeypatch, status_code):
    response = httpx.Response(status_code, request=httpx.Request('POST', StabilityApiGenerator.endpoint))
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: response)
    with pytest.raises(httpx.HTTPStatusError):
        StabilityApiGenerator('test-key').generate_image('a lighthouse', '')


@pytest.mark.parametrize('headers,content', [
    ({'content-type': 'application/json'}, b'{}'),
    ({'content-type': 'image/png'}, b''),
    ({'content-type': 'image/png', 'finish-reason': 'CONTENT_FILTERED'}, b'filtered'),
])
def test_stability_invalid_outputs(monkeypatch, headers, content):
    response = httpx.Response(200, content=content, headers=headers,
                              request=httpx.Request('POST', StabilityApiGenerator.endpoint))
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: response)
    with pytest.raises(ValueError):
        StabilityApiGenerator('test-key').generate_image('a lighthouse', '')
