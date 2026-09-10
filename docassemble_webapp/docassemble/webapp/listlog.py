import os
import subprocess
import time
from packaging import version

from flask import Flask, abort, make_response, render_template, request
app = Flask(__name__)

LOG_DIRECTORY = '/var/www/html/log'

VERSION_FILE = '/usr/share/docassemble/webapp/VERSION'
if os.path.isfile(VERSION_FILE) and os.access(VERSION_FILE, os.R_OK):
    with open(VERSION_FILE, 'r', encoding='utf-8') as fp:
        SYSTEM_VERSION = fp.read().strip()
else:
    SYSTEM_VERSION = '0.1.12'

if version.parse(SYSTEM_VERSION) < version.parse('1.4.0'):
    READY_FILE = '/usr/share/docassemble/webapp/ready'
else:
    READY_FILE = '/var/run/docassemble/ready'


@app.route('/listlog')
def list_log_files():
    # Argument lists throughout: environment values travel as single
    # argv elements and are never interpreted by a shell.
    auth_args = []
    if os.getenv('DASUPERVISORUSERNAME', None):
        auth_args = ['--username', os.getenv('DASUPERVISORUSERNAME'), '--password', os.getenv('DASUPERVISORPASSWORD')]
    server_args = ['--serverurl', 'http://localhost:9001']
    result = subprocess.run(['supervisorctl'] + auth_args + server_args + ['start', 'sync'], stdout=subprocess.DEVNULL, check=False).returncode
    if result != 0:
        return "There was an error."
    while True:
        status = subprocess.run(['supervisorctl'] + auth_args + server_args + ['status', 'sync'], stdout=subprocess.PIPE, check=False)
        if status.returncode == 0 and b'RUNNING' in status.stdout:
            break
        time.sleep(1)
    file_listing = [f for f in os.listdir(LOG_DIRECTORY) if os.path.isfile(os.path.join(LOG_DIRECTORY, f))]
    if len(file_listing) == 0:
        time.sleep(2)
        file_listing = [f for f in os.listdir(LOG_DIRECTORY) if os.path.isfile(os.path.join(LOG_DIRECTORY, f))]
    return "\n".join(sorted(file_listing))


@app.route("/listlog/health_check", methods=['GET'])
def health_check():
    if request.args.get('ready', False):
        if not os.path.isfile(READY_FILE):
            abort(400)
    response = make_response(render_template('pages/health_check.html', content="OK"), 200)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    return response
