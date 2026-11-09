import ctypes, os, sys
BIN = r"S:\Crytek\cryengine-57-lts\5.7.1\bin\win_x64"
EP = r"S:\Crytek\cryengine-57-lts\5.7.1\Editor\Python\windows"
os.add_dll_directory(BIN)
py = ctypes.PyDLL(os.path.join(BIN, "python37.dll"))
py.Py_SetPythonHome(ctypes.c_wchar_p(EP))
py.Py_SetPath(ctypes.c_wchar_p(";".join([os.path.join(BIN,"python37.zip"), os.path.join(EP,"Lib"), os.path.join(EP,"DLLs"), BIN])))
py.Py_Initialize()
# mimic: PyRun_SimpleFile(other/startup.py) then PyRun_SimpleFile(qceb/startup.py)
for script in [r"plug\other\startup.py", r"plug\qceb\startup.py"]:
    argv = (ctypes.c_wchar_p * 1)(os.path.abspath(script))
    py.PySys_SetArgvEx(1, argv, 0)
    msvcrt = ctypes.CDLL("msvcrt")
    fp = msvcrt.fopen(os.path.abspath(script).encode(), b"rb")
    py.PyRun_SimpleFile(fp, os.path.abspath(script).encode())
    msvcrt.fclose(fp)
    py.PyErr_Print()
