import sys
import os

# Obtain project root path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# For finding modules to test
sys.path.insert(0, project_root)
sys.path.insert(0, project_root + '/examples')
