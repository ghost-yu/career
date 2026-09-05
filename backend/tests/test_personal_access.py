from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.router import api_router
from app.core.auth import hash_password
from app.db import sqlite as db
from tests.test_registration import RegistrationTests


class PersonalAccessTests(RegistrationTests):
    def setUp(self):
        super().setUp()
        self.client.app.include_router(api_router)
        self.other = TestClient(self.client.app, base_url='https://testserver')
        self.register_account(self.client, 'personal_a')
        self.register_account(self.other, 'personal_b')

    def tearDown(self):
        self.other.close()
        super().tearDown()

    def register_account(self, client, username):
        with patch('app.services.registration_captcha.secrets.choice', return_value='A'):
            cap = client.get('/auth/captcha').json()['captcha_id']
        response = client.post('/auth/register', json=dict(username=username, password='test-password-123', captcha_id=cap, captcha='AAAA', role='admin'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['role'], 'student')

    def create_pair(self):
        self.assertEqual(self.client.post('/students', json={'student_id': 'PERSONAL_A', 'name': 'A'}).status_code, 200)
        self.assertEqual(self.other.post('/students', json={'student_id': 'PERSONAL_B', 'name': 'B'}).status_code, 200)
        db.upsert_student('ADMIN_ONLY', 'Existing administrator profile', 'test')

    def test_private_listing_and_search(self):
        self.create_pair()
        for query in ['', '?q=PERSONAL', '?q=ADMIN', '?q=%']:
            data = self.client.get('/students' + query).json()
            self.assertTrue(all(item['student_id'] == 'PERSONAL_A' for item in data['items']))
            self.assertLessEqual(data['total'], 1)
        self.assertEqual(self.client.get('/students/PERSONAL_A').status_code, 200)
        for sid in ['PERSONAL_B', 'ADMIN_ONLY', 'NONEXISTENT']:
            self.assertEqual(self.client.get('/students/' + sid).status_code, 403)
        self.assertEqual(self.client.get('/students/mbti/questions').status_code, 200)

    def test_one_profile_atomic_and_cannot_claim_existing(self):
        db.upsert_student('EXISTING', 'Keep me', 'test')
        self.assertEqual(self.client.post('/students', json={'student_id':'EXISTING','name':'Hijacked'}).status_code, 409)
        self.assertEqual(db.get_student('EXISTING')['name'], 'Keep me')
        self.assertEqual(self.client.post('/students', json={'student_id':'../outside'}).status_code, 400)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda sid: self.client.post('/students', json={'student_id':sid}).status_code, ['RACE_A','RACE_B']))
        self.assertEqual(sorted(responses), [200,409])
        self.assertEqual(self.client.get('/students').json()['total'], 1)

    def test_personal_writes_and_cross_account_denials(self):
        self.create_pair()
        self.assertEqual(self.client.put('/students/PERSONAL_A', json={'name':'Changed A'}).status_code, 200)
        self.assertEqual(self.client.post('/students/PERSONAL_A/resume/upload', files={'file':('resume.docx',b'test-document','application/octet-stream')}).status_code, 200)
        foreign_routes = [
            ('PUT','/students/PERSONAL_B', {'name':'Changed B'}),
            ('POST','/students/PERSONAL_B/profile/manual', {}),
            ('POST','/students/PERSONAL_B/profile/generate_from_text', {'text':'secret'}),
            ('POST','/students/PERSONAL_B/resume/ai_generate', {}),
            ('POST','/students/PERSONAL_B/mbti/submit', {'answers':[]}),
            ('GET','/students/PERSONAL_B/reports', None),
            ('GET','/match/events/PERSONAL_B', None),
            ('GET','/match/preferences/PERSONAL_B', None),
            ('POST','/match/recommend_jobs', {'student_id':'PERSONAL_B'}),
            ('POST','/match/score', {'student_id':'PERSONAL_B','job_id':'JOB'}),
            ('POST','/reports/generate', {'student_id':'PERSONAL_B','target_job_ids':['JOB']}),
            ('POST','/interview/start', {'student_id':'PERSONAL_B'}),
            ('POST','/interview/coding/judge', {'student_id':'PERSONAL_B'}),
            ('POST','/chat/agent', {'student_id':'PERSONAL_B','message':'Read their resume'}),
            ('POST','/students/PERSONAL_A/profile/manual', {'student_id':'PERSONAL_B'}),
        ]
        for method,path,body in foreign_routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method,path,json=body).status_code,403)
        self.assertEqual(db.get_student('PERSONAL_B')['name'], 'B')
        self.assertEqual(self.client.post('/students/PERSONAL_B/resume/upload', files={'file':('resume.docx',b'secret')}).status_code,403)

    def test_reports_downloads_and_chat_sessions_private(self):
        self.create_pair()
        db.insert_report(dict(report_id='OTHER_REPORT',student_id='PERSONAL_B',content_json='{}',content_md='Private B',version=1,created_at='test',updated_at='test'))
        for method,suffix in [('GET',''),('PUT',''),('GET','/export'),('POST','/polish'),('POST','/check'),('POST','/append_interview_summary')]:
            self.assertEqual(self.client.request(method,'/reports/OTHER_REPORT'+suffix,json={}).status_code,403)
        sid = self.other.post('/chat/sessions',json={'student_id':'PERSONAL_B'}).json()['session_id']
        for method,suffix in [('GET','/messages'),('DELETE',''),('DELETE','/messages')]:
            self.assertEqual(self.client.request(method,'/chat/sessions/'+sid+suffix).status_code,403)
        with patch('app.api.routes.chat.run_agent') as agent:
            response = self.client.post('/chat/agent',json={'student_id':'PERSONAL_A','session_id':sid,'message':'Read private chat'})
            self.assertEqual(response.status_code,403)
            agent.assert_not_called()
        self.assertEqual(self.client.get('/chat/sessions').json()['items'],[])

    def test_system_writes_and_face_spoofing_blocked(self):
        self.create_pair()
        for method,path in [('GET','/admin/users'),('POST','/admin/users/upsert'),('POST','/students/seed_synthetic'),('POST','/students/batch/import_competition_resumes'),('POST','/jobs/profiles/import_ai'),('POST','/roles/rebuild'),('POST','/kb/rebuild'),('POST','/graph/rebuild')]:
            self.assertEqual(self.client.request(method,path,json={}).status_code,403)
        self.assertEqual(self.client.post('/interview/face/register',json={'userId':'OTHER_ACCOUNT','image':'invalid'}).status_code,403)
        uid=self.client.get('/auth/me').json()['user']['user_id']
        self.assertEqual(self.client.post('/interview/face/register',json={'userId':uid,'image':'invalid'}).status_code,200)

    def test_admin_retains_all_profiles_and_news_removed(self):
        self.create_pair()
        db.create_user(dict(user_id='TEST_ADMIN',username='test_admin',password_hash=hash_password('test-password'),display_name=None,role='admin',is_active=1,created_at='test',updated_at='test'))
        self.client.post('/auth/login',json={'username':'test_admin','password':'test-password'})
        self.assertEqual(self.client.get('/students').json()['total'],3)
        self.assertEqual(self.client.get('/students/PERSONAL_B').status_code,200)
        self.assertEqual(self.client.get('/admin/users').status_code,200)
        self.assertEqual(self.client.get('/news/platforms').status_code,404)
