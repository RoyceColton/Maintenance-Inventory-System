import unittest
from app import app, db, Part
from flask import json
from datetime import datetime, date

# Integration & End-to-End Tests
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        # Use an in-memory SQLite database for testing.
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_full_workflow(self):
        # Add a new part.
        response = self.client.post('/add', data={
            'name': 'Integration Part',
            'model_number': 'INT001',
            'count': '10',
            'cost': '50.00',
            'room': 'Kitchen',
            'threshold': '5',
            'order_link': 'http://example.com/order'
        }, follow_redirects=True)
        self.assertIn(b'Added part: Integration Part', response.data)

        # Mark the part as purchased.
        with app.app_context():
            part = Part.query.filter_by(model_number='INT001').first()
            self.assertIsNotNone(part)
            part_id = part.id

        response = self.client.post(f'/purchase/update/{part_id}', data={
            'quantity': '4',
            'total_cost': '200.00',
            'tracking_number': 'TRACKINT',
            'estimated_delivery': '2025-01-01'
        }, follow_redirects=True)
        self.assertIn(b'Purchase for part Integration Part recorded', response.data)

        # Verify that the dashboard displays our part.
        response = self.client.get('/')
        self.assertIn(b'Integration Part', response.data)

        # Verify that the purchases page shows the purchase details.
        response = self.client.get('/purchases')
        self.assertIn(b'Integration Part', response.data)
        self.assertIn(b'200.0', response.data)

# Security Tests
class SecurityTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()
            part = Part(name='Secure Part', model_number='SEC001', count=10, cost=100.0, room='Kitchen')
            db.session.add(part)
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_sql_injection_search(self):
        payload = "' OR '1'='1"
        response = self.client.get(f'/?search={payload}')
        # Our safe parameterization should prevent injection. Adjust the assertion as needed.
        self.assertNotIn(b'Secure Part', response.data)

    def test_xss_injection(self):
        xss_payload = "<script>alert('XSS')</script>"
        self.client.post('/add', data={
            'name': xss_payload,
            'model_number': 'XSS001',
            'count': '5',
            'cost': '20.00',
            'room': 'Living',
            'threshold': '3',
            'order_link': 'http://example.com/order'
        }, follow_redirects=True)
        response = self.client.get('/')
        self.assertNotIn(xss_payload.encode(), response.data)
        self.assertIn(b"&lt;script&gt;", response.data)

# API Contract Tests
class APITests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()
            part = Part(name='API Part', model_number='API001', count=5, cost=10.0, room='Other')
            db.session.add(part)
            db.session.commit()
            self.part_id = part.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_api_increment(self):
        response = self.client.post(f'/api/increment/{self.part_id}')
        data = json.loads(response.data)
        self.assertTrue(data.get('success'))
        self.assertEqual(response.status_code, 200)

    def test_api_decrement(self):
        for _ in range(5):
            self.client.post(f'/api/decrement/{self.part_id}')
        response = self.client.post(f'/api/decrement/{self.part_id}')
        data = json.loads(response.data)
        self.assertFalse(data.get('success'))
        self.assertEqual(response.status_code, 400)

    def test_api_deliver_nonexistent(self):
        response = self.client.post('/api/deliver/9999')
        data = json.loads(response.data)
        self.assertFalse(data.get('success'))
        self.assertEqual(response.status_code, 404)

# Edge Case & Validation Tests
class EdgeCaseTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_invalid_estimated_delivery(self):
        with app.app_context():
            part = Part(name='Invalid Date Part', model_number='IDP001', count=5, cost=15.0, room='Kitchen')
            db.session.add(part)
            db.session.commit()
            part_id = part.id
        response = self.client.post(f'/purchase/update/{part_id}', data={
            'quantity': '3',
            'total_cost': '45.00',
            'tracking_number': 'TRACK123',
            'estimated_delivery': 'invalid-date'
        }, follow_redirects=True)
        self.assertIn(b'Invalid estimated delivery date', response.data)

    def test_search_no_results(self):
        response = self.client.get('/?search=NO_SUCH_PART')
        # Assuming index.html shows "No parts found." when no parts match.
        self.assertIn(b'No parts found.', response.data)

    def test_update_nonexistent_part(self):
        response = self.client.post('/update/9999', data={
            'name': 'Nonexistent',
            'model_number': 'NONEXIST',
            'count': '10',
            'cost': '10.00',
            'room': 'Kitchen',
            'threshold': '5',
            'order_link': 'http://example.com/order'
        }, follow_redirects=True)
        self.assertIn(b'Part not found.', response.data)

# History Tests
class HistoryTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        # Use an in-memory DB for history tests.
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        with app.app_context():
            db.create_all()
            # Create parts that are delivered with specific delivered_date values.
            part1 = Part(
                name='Delivered Part January', 
                model_number='DELJAN', 
                count=10, 
                cost=20.0, 
                room='Kitchen',
                order_status='Delivered',
                purchase_total_cost=100.00,
                purchased_quantity=5,
                delivered_date=date(2025, 1, 15)
            )
            part2 = Part(
                name='Delivered Part February', 
                model_number='DELFEB', 
                count=8, 
                cost=15.0, 
                room='Bathroom',
                order_status='Delivered',
                purchase_total_cost=80.00,
                purchased_quantity=4,
                delivered_date=date(2025, 2, 10)
            )
            db.session.add(part1)
            db.session.add(part2)
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_history_route(self):
        response = self.client.get('/history?year=2025')
        self.assertIn(b'January', response.data)
        self.assertIn(b'February', response.data)
        self.assertIn(b'2025 Total: 180.0', response.data)

if __name__ == '__main__':
    unittest.main()
