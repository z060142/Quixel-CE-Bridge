# Run a script on CRYENGINE's embedded CPython 3.7 via ctypes (host: any 64-bit Python).
import ctypes, os, sys
BIN = r"S:\Crytek\cryengine-57-lts\5.7.1\bin\win_x64"
EDITOR_PY = r"S:\Crytek\cryengine-57-lts\5.7.1\Editor\Python\windows"
script = os.path.abspath(sys.argv[1])
os.add_dll_directory(BIN)
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]
py = ctypes.PyDLL(os.path.join(BIN, "python37.dll"))
home = ctypes.c_wchar_p(EDITOR_PY)
py.Py_SetPythonHome(home)
paths = ";".join([os.path.join(BIN, "python37.zip"), os.path.join(EDITOR_PY, "Lib"), os.path.join(EDITOR_PY, "DLLs"), BIN])
py.Py_SetPath(ctypes.c_wchar_p(paths))
py.Py_Initialize()
argv = (ctypes.c_wchar_p * 1)(script)
py.PySys_SetArgvEx(1, argv, 0)
code = "exec(compile(open(%r, encoding='utf-8').read(), %r, 'exec'), {'__name__': '__main__'})" % (script, script)
rc = py.PyRun_SimpleString(code.encode("utf-8"))
sys.stdout.flush()
os._exit(rc)
