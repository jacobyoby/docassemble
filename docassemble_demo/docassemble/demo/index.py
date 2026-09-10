# do not pre-load
import re
from docassemble.base.util import (
    store_variables_snapshot,
    DAObject,
    current_context,
    start_time,
    variables_snapshot_connection,
)

__all__ = ['MyIndex']

# Allowed operators for structured report() filters. Field names are
# restricted to plain identifiers and every value travels as a bound
# parameter, so filter/order input can never become SQL.
_ALLOWED_FILTER_OPERATORS = frozenset({'=', '!=', '<>', '<', '<=', '>', '>=', 'LIKE', 'ILIKE'})
_ALLOWED_ORDER_DIRECTIONS = frozenset({'ASC', 'DESC'})
_FIELD_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def build_report_query(key, filter_by=None, order_by=None):
    clauses = []
    params = [key]
    for item in filter_by or []:
        try:
            field, operator, value = item
        except (TypeError, ValueError):
            raise ValueError("MyIndex.report: each filter must be a (field, operator, value) triple")
        if not isinstance(field, str) or not _FIELD_NAME_RE.match(field):
            raise ValueError("MyIndex.report: invalid filter field name")
        if not isinstance(operator, str) or operator.upper() not in _ALLOWED_FILTER_OPERATORS:
            raise ValueError("MyIndex.report: invalid filter operator")
        clauses.append("(data->>%s) " + operator.upper() + " %s")
        params.extend([field, value])
    order_clause = ''
    if order_by is not None:
        try:
            order_field, direction = order_by
        except (TypeError, ValueError):
            raise ValueError("MyIndex.report: order_by must be a (field, direction) pair")
        if not isinstance(order_field, str) or not _FIELD_NAME_RE.match(order_field):
            raise ValueError("MyIndex.report: invalid order field name")
        if not isinstance(direction, str) or direction.upper() not in _ALLOWED_ORDER_DIRECTIONS:
            raise ValueError("MyIndex.report: order direction must be ASC or DESC")
        order_clause = ' ORDER BY (data->>%s) ' + direction.upper()
        params.append(order_field)
    return ("SELECT data FROM jsonstorage WHERE tags=%s" + ''.join(' AND ' + clause for clause in clauses) + order_clause, params)


class MyIndex(DAObject):

    def init(self, *pargs, **kwargs):
        super().init(*pargs, **kwargs)
        if not hasattr(self, 'data'):
            self.data = {}
        if not hasattr(self, 'key'):
            self.key = 'myindex'

    def save(self):
        data = dict(self.data)
        data['session'] = current_context().session
        data['filename'] = current_context().filename
        data['start_time'] = start_time().astimezone()
        store_variables_snapshot(data, key=self.key)

    def set(self, data):
        if not isinstance(data, dict):
            raise RuntimeError("MyIndex.set: data parameter must be a dictionary")
        self.data = data
        self.save()

    def update(self, new_data):
        self.data.update(new_data)
        self.save()

    def report(self, filter_by=None, order_by=None):
        # filter_by is a list of (field, operator, value) triples and
        # order_by is a (field, direction) pair. Raw SQL fragments are
        # rejected by build_report_query, so caller input can never
        # become SQL. Values travel as bound parameters.
        query, params = build_report_query(self.key, filter_by=filter_by, order_by=order_by)
        conn = variables_snapshot_connection()
        with conn.cursor() as cur:
            cur.execute(query, params)
            results = [record[0] for record in cur.fetchall()]
        conn.close()
        return results
