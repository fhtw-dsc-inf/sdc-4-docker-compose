import os
import sys
from pathlib import Path

# Never load committed credentials or call paid APIs in the automated tests.
os.environ['OPENAI_API_KEY'] = 'test-openai-key'
os.environ['STABILITY_KEY'] = 'test-stability-key'
os.environ['OPENAI_MODEL'] = 'gpt-4o-mini'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
