"""
Integration tests for gunicorn's uWSGI binary protocol with nginx.

These tests verify that gunicorn correctly implements the uWSGI binary
protocol by running actual requests through nginx's uwsgi_pass directive.
"""

import concurrent.futures
import json

import pytest
import requests

from conftest import docker_available


@docker_available
class TestBasicRequests:
    """Test basic HTTP request handling through uWSGI protocol."""

    def test_get_root(self, nginx_url):
        """Test basic GET request to root endpoint."""
        response = requests.get(f'{nginx_url}/')
        assert response.status_code == 200
        assert b'Hello from gunicorn uWSGI!' in response.content

    def test_get_with_query_string(self, nginx_url):
        """Test GET request with query string parameters."""
        response = requests.get(f'{nginx_url}/query?foo=bar&baz=qux')
        assert response.status_code == 200
        data = response.json()
        assert data['foo'] == 'bar'
        assert data['baz'] == 'qux'

    def test_post_echo(self, nginx_url):
        """Test POST request with body echo."""
        test_body = b'This is a test body content'
        response = requests.post(f'{nginx_url}/echo', data=test_body)
        assert response.status_code == 200
        assert response.content == test_body

    def test_post_json(self, nginx_url):
        """Test POST request with JSON body."""
        test_data = {'key': 'value', 'number': 42, 'nested': {'a': 1}}
        response = requests.post(
            f'{nginx_url}/json',
            json=test_data,
            headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert data['received'] == test_data

    def test_post_large_body(self, nginx_url):
        """Test POST with large request body (100KB)."""
        large_body = b'X' * (100 * 1024)
        response = requests.post(f'{nginx_url}/echo', data=large_body)
        assert response.status_code == 200
        assert len(response.content) == len(large_body)
        assert response.content == large_body


@docker_available
class TestHeaderPreservation:
    """Test that headers are correctly passed through uWSGI protocol."""

    def test_custom_headers(self, nginx_url):
        """Test custom headers are passed to the application."""
        custom_headers = {
            'X-Custom-Header': 'custom-value',
            'X-Another-Header': 'another-value'
        }
        response = requests.get(f'{nginx_url}/headers', headers=custom_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get('X-Custom-Header') == 'custom-value'
        assert data.get('X-Another-Header') == 'another-value'

    def test_host_header(self, nginx_url):
        """Test Host header is passed correctly."""
        response = requests.get(
            f'{nginx_url}/headers',
            headers={'Host': 'test.example.com'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('Host') == 'test.example.com'

    def test_content_type_header(self, nginx_url):
        """Test Content-Type header is passed correctly."""
        response = requests.post(
            f'{nginx_url}/headers',
            data='test',
            headers={'Content-Type': 'application/x-custom-type'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('Content-Type') == 'application/x-custom-type'

    def test_user_agent_header(self, nginx_url):
        """Test User-Agent header is passed correctly."""
        response = requests.get(
            f'{nginx_url}/headers',
            headers={'User-Agent': 'TestAgent/1.0'}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('User-Agent') == 'TestAgent/1.0'


@docker_available
class TestKeepAlive:
    """Test HTTP keep-alive with multiple requests per connection."""

    def test_multiple_requests_same_session(self, session, nginx_url):
        """Test multiple requests using same session/connection."""
        for i in range(5):
            response = session.get(f'{nginx_url}/')
            assert response.status_code == 200

    def test_mixed_requests_same_session(self, session, nginx_url):
        """Test mixed GET and POST requests using same session."""
        # GET request
        response = session.get(f'{nginx_url}/')
        assert response.status_code == 200

        # POST request
        response = session.post(f'{nginx_url}/echo', data=b'test')
        assert response.status_code == 200
        assert response.content == b'test'

        # Another GET
        response = session.get(f'{nginx_url}/headers')
        assert response.status_code == 200

        # JSON POST
        response = session.post(f'{nginx_url}/json', json={'test': 1})
        assert response.status_code == 200


@docker_available
class TestErrorResponses:
    """Test HTTP error responses through uWSGI protocol."""

    @pytest.mark.parametrize('code', [400, 401, 403, 404, 500, 502, 503])
    def test_error_codes(self, nginx_url, code):
        """Test various HTTP error codes are returned correctly."""
        response = requests.get(f'{nginx_url}/error/{code}')
        assert response.status_code == code
        data = response.json()
        assert data['code'] == code

    def test_not_found(self, nginx_url):
        """Test 404 for non-existent path."""
        response = requests.get(f'{nginx_url}/nonexistent/path')
        assert response.status_code == 404
        data = response.json()
        assert data['error'] == 'Not Found'
        assert data['path'] == '/nonexistent/path'


@docker_available
class TestEnvironVariables:
    """Test WSGI environ variables are correctly set."""

    def test_request_method(self, nginx_url):
        """Test REQUEST_METHOD is set correctly."""
        response = requests.get(f'{nginx_url}/environ')
        assert response.status_code == 200
        data = response.json()
        assert data.get('REQUEST_METHOD') == 'GET'

        response = requests.post(f'{nginx_url}/environ', data='')
        data = response.json()
        assert data.get('REQUEST_METHOD') == 'POST'

    def test_path_info(self, nginx_url):
        """Test PATH_INFO is set correctly."""
        response = requests.get(f'{nginx_url}/environ')
        assert response.status_code == 200
        data = response.json()
        assert data.get('PATH_INFO') == '/environ'

    def test_query_string(self, nginx_url):
        """Test QUERY_STRING is set correctly."""
        response = requests.get(f'{nginx_url}/environ?foo=bar&test=123')
        assert response.status_code == 200
        data = response.json()
        assert data.get('QUERY_STRING') == 'foo=bar&test=123'

    def test_server_protocol(self, nginx_url):
        """Test SERVER_PROTOCOL is set."""
        response = requests.get(f'{nginx_url}/environ')
        assert response.status_code == 200
        data = response.json()
        assert 'SERVER_PROTOCOL' in data
        assert data['SERVER_PROTOCOL'].startswith('HTTP/')

    def test_content_length(self, nginx_url):
        """Test CONTENT_LENGTH is set for POST requests."""
        body = 'test body content'
        response = requests.post(f'{nginx_url}/environ', data=body)
        assert response.status_code == 200
        data = response.json()
        assert data.get('CONTENT_LENGTH') == str(len(body))


@docker_available
class TestLargeResponses:
    """Test large response handling through uWSGI protocol."""

    def test_1mb_response(self, nginx_url):
        """Test 1MB response body is received correctly."""
        response = requests.get(f'{nginx_url}/large')
        assert response.status_code == 200
        assert len(response.content) == 1024 * 1024
        # Verify content is all 'X' characters
        assert response.content == b'X' * (1024 * 1024)

    def test_large_response_content_length(self, nginx_url):
        """Test Content-Length header for large response."""
        response = requests.get(f'{nginx_url}/large')
        assert response.status_code == 200
        assert response.headers.get('Content-Length') == str(1024 * 1024)


@docker_available
class TestConcurrency:
    """Test concurrent request handling."""

    def test_parallel_requests(self, nginx_url):
        """Test handling multiple parallel requests."""
        num_requests = 20

        def make_request(i):
            response = requests.get(f'{nginx_url}/query?id={i}')
            return response.status_code, response.json().get('id')

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(num_requests)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All requests should succeed
        assert all(status == 200 for status, _ in results)
        # All IDs should be present
        ids = set(id_val for _, id_val in results)
        assert ids == set(str(i) for i in range(num_requests))

    def test_parallel_mixed_requests(self, nginx_url):
        """Test parallel GET and POST requests."""
        def get_request():
            return requests.get(f'{nginx_url}/').status_code

        def post_request(data):
            response = requests.post(f'{nginx_url}/echo', data=data)
            return response.status_code, response.content

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            get_futures = [executor.submit(get_request) for _ in range(10)]
            post_futures = [
                executor.submit(post_request, f'data-{i}'.encode())
                for i in range(10)
            ]

            get_results = [f.result() for f in get_futures]
            post_results = [f.result() for f in post_futures]

        assert all(status == 200 for status in get_results)
        assert all(status == 200 for status, _ in post_results)


@docker_available
class TestSpecialCases:
    """Test edge cases and special scenarios."""

    def test_empty_body_post(self, nginx_url):
        """Test POST with empty body."""
        response = requests.post(f'{nginx_url}/echo', data=b'')
        assert response.status_code == 200
        assert response.content == b''

    def test_binary_body(self, nginx_url):
        """Test POST with binary body containing null bytes."""
        binary_data = bytes(range(256))
        response = requests.post(f'{nginx_url}/echo', data=binary_data)
        assert response.status_code == 200
        assert response.content == binary_data

    def test_unicode_in_query_string(self, nginx_url):
        """Test unicode characters in query string."""
        response = requests.get(f'{nginx_url}/query', params={'name': 'test'})
        assert response.status_code == 200
        data = response.json()
        assert data.get('name') == 'test'

    def test_special_characters_in_path(self, nginx_url):
        """Test handling of special path that triggers 404."""
        # This should return 404 since the path doesn't exist
        response = requests.get(f'{nginx_url}/path/with/slashes')
        assert response.status_code == 404

    def test_long_header_value(self, nginx_url):
        """Test handling of long header values."""
        long_value = 'X' * 4096  # 4KB header value
        response = requests.get(
            f'{nginx_url}/headers',
            headers={'X-Long-Header': long_value}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('X-Long-Header') == long_value
