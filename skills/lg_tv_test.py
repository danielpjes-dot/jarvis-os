import unittest
import requests
import time

class TestLgTvReload(unittest.TestCase):
    def setUp(self):
        self.base_url = "http://localhost:8000"
        
    def test_skill_reload(self):
        """Test that skills can be reloaded via API endpoint"""
        # First, check that the skill exists
        response = requests.get(f"{self.base_url}/api/skills")
        self.assertEqual(response.status_code, 200)
        
        # Test reload endpoint
        response = requests.post(f"{self.base_url}/api/skills/reload")
        self.assertEqual(response.status_code, 200)
        
        # Verify reload was successful
        response = requests.get(f"{self.base_url}/api/skills")
        self.assertEqual(response.status_code, 200)
        
        # Check that the lg_tv skill is still present
        skills = response.json()
        lg_tv_exists = any(skill['name'] == 'lg_tv' for skill in skills)
        self.assertTrue(lg_tv_exists)

if __name__ == '__main__':
    unittest.main()