"""Create a docassemble API key for user 1 directly in redis.

Run inside the docassemble container with its venv python. Prints the raw
key as the last line of output.
"""
import json
import docassemble.base.config
docassemble.base.config.load(arguments=["mkkey"])
from docassemble.base.config import daconfig
from docassemble.base.generate_key import random_alphanumeric
from docassemble.webapp.utils.api_key import encrypt_api_key
from docassemble.webapp.daredis import r
api_key = random_alphanumeric(32)
info = {"constraints": [], "method": "none", "name": "e2e-981",
        "permissions": [], "last_four": api_key[-4:]}
r.set("da:apikey:userid:1:key:"
      + encrypt_api_key(api_key, daconfig.get("secretkey")) + ":info",
      json.dumps(info))
print(api_key)
