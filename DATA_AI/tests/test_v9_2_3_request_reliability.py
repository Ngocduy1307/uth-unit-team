from uuid import UUID
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_request_id_generated_for_request():
    response = client.get('/health')
    assert response.status_code == 200
    UUID(response.headers['x-request-id'])

def test_valid_request_id_is_propagated():
    request_id = '5b4fdb5c-73f5-4a62-9f4c-0c8f3d2c9d11'
    response = client.get('/health', headers={'X-Request-ID': request_id})
    assert response.headers['x-request-id'] == request_id

def test_invalid_request_id_is_replaced():
    response = client.get('/health', headers={'X-Request-ID': 'bad\r\nforged: yes'})
    generated = response.headers['x-request-id']
    UUID(generated)
    assert generated != 'bad\r\nforged: yes'

def test_request_id_present_on_not_found():
    response = client.get('/does-not-exist')
    assert response.status_code == 404
    UUID(response.headers['x-request-id'])
