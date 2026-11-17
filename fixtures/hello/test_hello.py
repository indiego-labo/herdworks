import subprocess
import sys
import unittest


class HelloTests(unittest.TestCase):
    def test_greeting(self):
        result = subprocess.run([sys.executable, "hello.py", "Ada"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Hello, Ada!\n")
