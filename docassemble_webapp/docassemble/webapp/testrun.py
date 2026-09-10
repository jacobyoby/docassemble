# from werkzeug.contrib.profiler import ProfilerMiddleware
import os

from docassemble.webapp.server import app
# app.wsgi_app = ProfilerMiddleware(app.wsgi_app)
# NB: the Werkzeug debugger can execute arbitrary code, so it stays off
# unless explicitly requested. Dev use: DOCASSEMBLE_TESTRUN_DEBUG=1
app.run(debug=os.environ.get('DOCASSEMBLE_TESTRUN_DEBUG', '').lower() in ('1', 'true', 'yes'), port=4041)
