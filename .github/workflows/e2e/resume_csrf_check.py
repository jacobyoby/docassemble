"""Resume CSRF check for docassemble#45 (H-13).

Run inside the docassemble container venv after installing this branch's
main/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/main/views.py da:<site-packages>/docassemble/webapp/main/views.py
    docker exec da <venv-python> /tmp/resume_csrf_check.py

/resume binds an arbitrary caller-supplied uid into the Flask session,
so it must not be CSRF-exempt: a forged cross-site POST would plant an
attacker's session into the victim's browser.
"""
from flask import Flask

import docassemble.webapp.main.views as main_views
from docassemble.webapp.extensions import csrf

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def resume_not_exempt():
    exempt = getattr(csrf, '_exempt_views', set())
    assert 'docassemble.webapp.main.views.resume' not in exempt, "main.resume still CSRF-exempt"


def forged_post_rejected():
    app = Flask('resume_csrf_check')
    app.secret_key = 'check-secret-0123456789abcdef'
    app.register_blueprint(main_views.main_bp)
    csrf.init_app(app)
    client = app.test_client()
    response = client.post('/resume', data={'session': 'ATTACKERUID', 'i': 'sometest'})
    assert response.status_code == 400, response.status_code


check("resume not CSRF-exempt", resume_not_exempt)
check("forged POST rejected", forged_post_rejected)

if failures:
    raise SystemExit("resume_csrf_check FAILED: " + ", ".join(failures))
print("resume_csrf_check: all checks passed")
