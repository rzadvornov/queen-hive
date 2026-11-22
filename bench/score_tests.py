"""Run one test folder of a scored copy and print the result as JSON: {"run", "passed", "failed": [...]}.

    python3 score_tests.py hidden_tests      # from the copy's root
"""

import io
import json
import sys
import unittest

sys.path.insert(0, ".")
suite = unittest.defaultTestLoader.discover(sys.argv[1], top_level_dir=".")
result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
failed = [test.id() for test, _ in result.failures + result.errors]
print(json.dumps({"run": result.testsRun, "passed": result.testsRun - len(failed), "failed": failed}))
