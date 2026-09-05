import base64
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from app.api.routes.auth import router
from app.core.config import settings
from app.core.auth import hash_password
from app.db import sqlite as db


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[2] / 'tmp' / 'tests' / 'registration'
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.old_path, self.old_dir, self.old_local = settings.sqlite_path, settings.data_dir, db._thread_local
        settings.sqlite_path = str(Path(self.temp.name) / 'test.db')
        settings.data_dir = self.temp.name
        db._thread_local = threading.local()
        self.connections = {}
        original_get_conn = db.get_conn
        def tracked_get_conn():
            connection = original_get_conn()
            self.connections[id(connection)] = connection
            return connection
        self.connection_patch = patch.object(db, 'get_conn', side_effect=tracked_get_conn)
        self.connection_patch.start()
        db.init_db()
        app = FastAPI()
        app.include_router(router, prefix='/auth')
        self.client = TestClient(app, base_url='https://testserver')

    def tearDown(self):
        self.client.close()
        for connection in self.connections.values():
            connection.close()
        self.connection_patch.stop()
        db._thread_local = self.old_local
        settings.sqlite_path, settings.data_dir = self.old_path, self.old_dir
        assert Path(self.temp.name).resolve().is_relative_to(self.temp_root.resolve())
        self.temp.cleanup()

    def challenge(self):
        with patch('app.services.registration_captcha.secrets.choice', return_value='A'):
            response = self.client.get('/auth/captcha')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        data = response.json()
        self.assertNotIn('answer', data)
        image = Image.open(io.BytesIO(base64.b64decode(data['image'].split(',')[1])))
        self.assertEqual(image.format, 'PNG')
        self.assertEqual(image.size, (144, 48))
        return data['captcha_id']

    def payload(self, captcha_id, **extra):
        return dict(username='demo_student', password='unchanged-password', captcha_id=captcha_id, captcha='aaaa', **extra)

    def test_registration_login_and_role(self):
        cap = self.challenge()
        response = self.client.post('/auth/register', json=self.payload(cap, role='admin'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['role'], 'student')
        self.assertEqual(self.client.get('/auth/me').json()['user']['username'], 'demo_student')
        self.client.post('/auth/logout')
        self.assertEqual(self.client.post('/auth/login', json={'username':'demo_student', 'password':'unchanged-password'}).status_code, 200)
        self.assertEqual(self.client.post('/auth/login', json={'username':'demo_student', 'password':'incorrect'}).status_code, 401)

    def test_missing_wrong_and_replayed_captcha(self):
        response = self.client.post('/auth/register', json={'username':'demo_student','password':'unchanged-password'})
        self.assertEqual(response.json()['detail'], 'captcha_required')
        cap = self.challenge()
        payload = self.payload(cap)
        payload['captcha'] = 'BBBB'
        self.assertEqual(self.client.post('/auth/register', json=payload).json()['detail'], 'captcha_invalid')
        self.assertEqual(self.client.post('/auth/register', json=self.payload(cap)).json()['detail'], 'captcha_invalid')
        cap = self.challenge()
        self.assertEqual(self.client.post('/auth/register', json=self.payload(cap)).status_code, 200)
        payload = self.payload(cap)
        payload['username'] = 'another_student'
        self.assertEqual(self.client.post('/auth/register', json=payload).json()['detail'], 'captcha_invalid')

    def test_expired_captcha(self):
        cap = self.challenge()
        with db.get_conn() as conn:
            conn.execute('UPDATE registration_captchas SET expires_at=? WHERE captcha_id=?', (int(time.time())-1,cap))
        self.assertEqual(self.client.post('/auth/register', json=self.payload(cap)).json()['detail'], 'captcha_expired')

    def test_username_collision_and_password_rule(self):
        cap = self.challenge()
        self.assertEqual(self.client.post('/auth/register', json=self.payload(cap)).status_code, 200)
        cap = self.challenge()
        self.assertEqual(self.client.post('/auth/register', json=self.payload(cap)).status_code, 409)
        cap = self.challenge()
        payload = self.payload(cap)
        payload.update(username='second_student', password='123')
        self.assertEqual(self.client.post('/auth/register', json=payload).json()['detail'], 'password_too_short')

    def test_existing_short_password_is_unchanged(self):
        db.create_user(dict(user_id='legacy-user', username='existing', password_hash=hash_password('123'),
                            display_name=None, role='admin', is_active=1, created_at='test', updated_at='test'))
        response = self.client.post('/auth/login', json={'username':'existing','password':'123'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['role'], 'admin')

if __name__ == '__main__':
    unittest.main()
