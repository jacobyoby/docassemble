# ruff: noqa: E402
# pylint: disable=wrong-import-position
import datetime
import email
import json
import mimetypes
import re
import sys
from email.utils import parseaddr, parsedate, getaddresses
from time import mktime
from sqlalchemy import select
from sqlalchemy.orm import joinedload
import docassemble.base.config
if __name__ == "__main__":
    docassemble.base.config.load(arguments=sys.argv)
from docassemble.webapp.db import session_scope
from docassemble.webapp.emailserver.models import Shortener, Email, EmailAttachment
from docassemble.webapp.files.file_number import get_new_file_number
from docassemble.webapp.files.savedfile import SavedFile
from docassemble.webapp.users.models import UserModel
from docassemble.webapp.tasks.app import celery_app


def main():
    try:
        with open(sys.argv[1], 'r', encoding="utf-8") as email_fp:
            msg = email.message_from_file(email_fp)
    except BaseException:
        sys.exit("Failed to read e-mail message")
    raw_date = msg.get('Date', msg.get('Resent-Date', None))
    addr_return_path = msg.get('Return-path', None)
    addr_reply_to = msg.get('Reply-to', None)
    addr_to = msg.get('Envelope-to', None)
    addr_from = msg.get('From', msg.get('Sender', None))
    subject = msg.get('Subject', None)
    to_recipients = []
    for recipient in getaddresses(msg.get_all('to', []) + msg.get_all('resent-to', [])):
        to_recipients.append({'name': recipient[0], 'address': recipient[1]})
    cc_recipients = []
    for recipient in getaddresses(msg.get_all('cc', []) + msg.get_all('resent-cc', [])):
        cc_recipients.append({'name': recipient[0], 'address': recipient[1]})
    recipients = []
    for recipient in getaddresses(msg.get_all('to', []) + msg.get_all('cc', []) + msg.get_all('resent-to', []) + msg.get_all('resent-cc', [])):
        recipients.append({'name': recipient[0], 'address': recipient[1]})
    if addr_to is None and len(recipients) > 0:
        addr_to = recipients[0]['address']
    if addr_to is not None:
        short_code = re.sub(r'@.*', '', parseaddr(addr_to)[1])
    else:
        short_code = None
    with session_scope() as session:
        record = session.execute(select(Shortener).filter_by(short=short_code)).scalar()
        if record is None:
            sys.exit("short code not found")
        # file_number = get_new_file_number(record.uid, 'email', record.filename)
        # saved_file_email = SavedFile(file_number, fix=True)
        if addr_from is not None:
            addr_from = {'name': parseaddr(addr_from)[0], 'address': parseaddr(addr_from)[1]}
        else:
            addr_from = {'empty': True}
        if addr_return_path is not None:
            addr_return_path = {'name': parseaddr(addr_return_path)[0], 'address': parseaddr(addr_return_path)[1]}
        else:
            addr_return_path = {'empty': True}
        if addr_reply_to is not None:
            addr_reply_to = {'name': parseaddr(addr_reply_to)[0], 'address': parseaddr(addr_reply_to)[1]}
        else:
            addr_reply_to = {'empty': True}
        msg_current_time = datetime.datetime.now()
        if raw_date is not None:
            msg_date = datetime.datetime.fromtimestamp(mktime(parsedate(raw_date)))
        else:
            msg_date = msg_current_time
        headers = []
        for item in msg.items():
            headers.append([item[0], item[1]])

        email_record = Email(short=short_code, to_addr=json.dumps(to_recipients), cc_addr=json.dumps(cc_recipients), from_addr=json.dumps(addr_from), reply_to_addr=json.dumps(addr_reply_to), return_path_addr=json.dumps(addr_return_path), subject=subject, datetime_message=msg_date, datetime_received=msg_current_time)
        session.add(email_record)
        save_attachment(session, record.uid, record.filename, 'headers.json', email_record.id, 0, 'application/json', 'json', json.dumps(headers))

        counter = 1
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            filename = part.get_filename()
            if part.get_content_type() == 'text/plain':
                ext = '.txt'
            else:
                ext = mimetypes.guess_extension(part.get_content_type())
            if not ext:
                ext = '.bin'
            if filename:
                filename = '%03d-%s' % (counter, safe_filename(filename))
            else:
                filename = '%03d-attachment%s' % (counter, ext)

            real_filename = re.sub(r'[0-9][0-9][0-9]-', r'', filename)
            real_ext = re.sub(r'^\.', r'', ext)
            save_attachment(session, record.uid, record.filename, real_filename, email_record.id, counter, part.get_content_type(), real_ext, part.get_payload(decode=True))
            counter += 1
        user = None
        if record.user_id is not None:
            user = session.execute(select(UserModel).options(joinedload(UserModel.roles)).filter_by(id=record.user_id)).scalar()
        if user is None:
            user_info = {'email': None, 'the_user_id': 't' + str(record.temp_user_id), 'theid': record.temp_user_id, 'roles': []}
        else:
            role_list = [role.name for role in user.roles]
            if len(role_list) == 0:
                role_list = ['user']
            user_info = {'email': user.email, 'roles': role_list, 'the_user_id': user.id, 'theid': user.id, 'firstname': user.first_name, 'lastname': user.last_name, 'nickname': user.nickname, 'country': user.country, 'subdivisionfirst': user.subdivisionfirst, 'subdivisionsecond': user.subdivisionsecond, 'subdivisionthird': user.subdivisionthird, 'organization': user.organization}
        celery_app.signature('tasks.background_action', args=[record.filename, user_info, record.uid, None, None, None, {'action': 'incoming_email', 'arguments': {'id': email_record.id}}], kwargs={"extra": None}).delay()


def save_attachment(session, uid, yaml_filename, filename, email_id, index, content_type, extension, content):
    att_file_number = get_new_file_number(uid, filename, yaml_filename)
    attachment_record = EmailAttachment(email_id=email_id, index=index, content_type=content_type, extension=extension, upload=att_file_number)
    session.add(attachment_record)
    saved_file_attachment = SavedFile(att_file_number, extension=extension, fix=True, should_not_exist=True)
    saved_file_attachment.write_content(content)
    saved_file_attachment.finalize()


def safe_filename(filename):
    filename = re.sub(r'[^A-Za-z0-9\_\-\. ]+', r'_', filename)
    return filename.strip('_')

main()
