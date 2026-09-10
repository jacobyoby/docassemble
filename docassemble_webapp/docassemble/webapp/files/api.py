import os
import re
import werkzeug
from flask import request
from flask_cors import cross_origin
from flask_login import current_user
from docassemble.webapp.api.helpers import api_verify
from docassemble.webapp.config import daconfig
from docassemble.webapp.utils.helpers import jsonify_with_status, custom_send_file
from docassemble.webapp.sessions import get_session_uids
from docassemble.webapp.utils.filenames import (
    get_ext_and_mimetype,
    secure_filename_unicode_ok,
)
from .file_access import get_info_from_file_number
from .blueprint import files_bp

# NB: honors the admin-configured 'cross site domains' like the other API
# decorators (#52); '*' is only the unconfigured fallback.
CORS_ORIGINS = daconfig.get('cross site domains', '*')


@files_bp.route('/api/file/<int:file_number>', methods=['GET'])
@cross_origin(origins=CORS_ORIGINS, methods=['GET', 'HEAD'], automatic_options=True)
def api_file(file_number):
    if not api_verify():
        return jsonify_with_status("Access denied.", 403)
    # yaml_filename = request.args.get('i', None)
    # session_id = request.args.get('session', None)
    number = re.sub(r'[^0-9]', '', str(file_number))
    # NB: least-privilege follow-through from #57. Advocates use granular
    # per-file grants via get_info_from_file_number, not a blanket bypass.
    privileged = bool(current_user.is_authenticated and current_user.has_role('admin'))
    try:
        file_info = get_info_from_file_number(number, privileged=privileged, uids=get_session_uids())
    except:
        return ('File not found', 404)
    if 'path' not in file_info:
        return ('File not found', 404)
    # NB: both user-controlled selectors below are confined with realpath to
    # the upload's own directory. The sanitizers already strip separators,
    # but isfile() follows symlinks, so only a resolved-path containment
    # check keeps a planted symlink from escaping the directory (M-13).
    base_dir = os.path.realpath(os.path.dirname(file_info['path']))
    if 'extension' in request.args:
        extension = werkzeug.utils.secure_filename(request.args['extension'])
        the_path = os.path.realpath(file_info['path'] + '.' + extension)
        if os.path.dirname(the_path) != base_dir or not os.path.isfile(the_path):
            return ('File not found', 404)
        extension, mimetype = get_ext_and_mimetype(file_info['path'] + '.' + extension)
    elif 'filename' in request.args:
        the_filename = secure_filename_unicode_ok(request.args['filename'])
        the_path = os.path.realpath(os.path.join(base_dir, the_filename))
        if os.path.dirname(the_path) != base_dir or not os.path.isfile(the_path):
            return ('File not found', 404)
        extension, mimetype = get_ext_and_mimetype(the_filename)
    else:
        the_path = file_info['path']
        mimetype = file_info['mimetype']
    if not os.path.isfile(the_path):
        return ('File not found', 404)
    response = custom_send_file(the_path, mimetype=mimetype)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    return response
