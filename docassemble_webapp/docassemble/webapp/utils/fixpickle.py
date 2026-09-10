import datetime
import io
import pickle
from docassemble.webapp.utils.logger import logmessage
from docassemble.webapp.utils.constants import TypeType, NoneType
from docassemble.webapp.hooks.impl import hookimpl

# Defense in depth for #32: every GLOBAL resolved while unpickling stored
# session/database data passes through this denylist. It blocks the classic
# remote-code-execution primitives; it is NOT a substitute for the planned
# migration to JSON with HMAC integrity verification, which must still happen.
# Note: copyreg stays allowed because protocol-2 pickles of ordinary classes
# need it, so exotic bypass chains remain possible. Treat this as a speed
# bump for naive payloads, not a sandbox.
_BLOCKED_UNPICKLE_MODULE_ROOTS = frozenset({
    'os', 'posix', 'nt', 'subprocess', 'sys', 'socket', 'shutil',
    'runpy', 'importlib', 'ctypes', 'code', 'pty', 'tty', 'webbrowser',
    'ensurepip', 'venv', 'pydoc',
})
_BLOCKED_UNPICKLE_NAMES = frozenset({
    'builtins:eval', 'builtins:exec', 'builtins:__import__',
    'builtins:compile', 'builtins:open', 'builtins:input',
    'builtins:exit', 'builtins:quit', 'builtins:globals',
    'builtins:locals', 'builtins:vars', 'builtins:getattr',
    'builtins:setattr', 'builtins:delattr', 'builtins:__build_class__',
})


# Python-2-era module names still show up in stored pickles (and in
# attacker payloads using fix_imports-era aliases). Normalize before checking.
_PY2_MODULE_ALIASES = {
    '__builtin__': 'builtins',
    'copy_reg': 'copyreg',
}


def _is_blocked_global(module, name):
    module = _PY2_MODULE_ALIASES.get(module, module)
    root = module.split('.')[0]
    return root in _BLOCKED_UNPICKLE_MODULE_ROOTS or module + ':' + name in _BLOCKED_UNPICKLE_NAMES


class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if _is_blocked_global(module, name):
            logmessage("fixpickle: refusing to unpickle blocked global " + module + "." + name)
            raise pickle.UnpicklingError("forbidden GLOBAL " + module + "." + name)
        resolved = super().find_class(module, name)
        # GLOBALs can name an object through an aliased module (observed:
        # subprocess.Popen pickled as commands.Popen), so re-check the
        # resolved object's true home. Resolving only imports the module;
        # nothing is called.
        true_module = getattr(resolved, '__module__', None) or ''
        true_name = getattr(resolved, '__name__', name)
        if _is_blocked_global(true_module, true_name):
            logmessage("fixpickle: refusing to unpickle blocked global " + module + "." + name + " (resolves to " + true_module + "." + str(true_name) + ")")
            raise pickle.UnpicklingError("forbidden GLOBAL " + module + "." + name)
        return resolved


def restricted_loads(data, **kwargs):
    return RestrictedUnpickler(io.BytesIO(data), **kwargs).load()


@hookimpl
def fix_pickle_obj(data):
    try:
        return recursive_fix_pickle(restricted_loads(data, encoding="bytes", fix_imports=True), seen=set())
    except:
        return recursive_fix_pickle(restricted_loads(data, encoding="latin1", fix_imports=True), seen=set())


def fix_pickle_dict(the_dict):
    try:
        obj = restricted_loads(the_dict)
        assert '_internal' in obj
        return obj
    except:
        try:
            obj = restricted_loads(the_dict, encoding="bytes", fix_imports=True)
        except:
            obj = restricted_loads(the_dict, encoding="latin1", fix_imports=True)
        return recursive_fix_pickle(obj, seen=set())


def recursive_fix_pickle(the_object, seen):
    if isinstance(the_object, (str, bool, int, float, complex, NoneType, datetime.datetime, TypeType)):
        return the_object
    if isinstance(the_object, bytes):
        try:
            return the_object.decode()
        except:
            logmessage("Could not decode bytes " + repr(the_object))
            return the_object
    object_id = id(the_object)
    if object_id in seen:
        return the_object
    seen.add(object_id)
    if isinstance(the_object, dict):
        new_dict = type(the_object)()
        for key, val in the_object.items():
            new_dict[recursive_fix_pickle(key, seen=seen)] = recursive_fix_pickle(val, seen=seen)
        # seen.add(object_id)
        return new_dict
    if isinstance(the_object, list):
        new_list = type(the_object)()
        for item in the_object:
            new_list.append(recursive_fix_pickle(item, seen=seen))
        # seen.add(object_id)
        return new_list
    if isinstance(the_object, set):
        new_set = type(the_object)()
        for item in the_object:
            new_set.add(recursive_fix_pickle(item, seen=seen))
        # seen.add(object_id)
        return new_set
    if isinstance(the_object, tuple):
        new_list = []
        for item in the_object:
            new_list.append(recursive_fix_pickle(item, seen=seen))
        # seen.add(object_id)
        return type(the_object)(new_list)
    if hasattr(the_object, '__dict__'):
        try:
            the_object.__dict__ = dict((recursive_fix_pickle(k, seen=seen), recursive_fix_pickle(v, seen=seen)) for k, v in the_object.__dict__.items())
        except:
            pass
    # seen.add(object_id)
    return the_object
