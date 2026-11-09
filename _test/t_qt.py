import sys, os
print("start", flush=True)
sys.path.insert(0, r"S:\Crytek\cryengine-57-lts\5.7.1\bin\win_x64")
try:
    import PySide2; print(PySide2.__file__, flush=True)
    from PySide2 import QtWidgets; print("qt ok", flush=True)
except BaseException as e:
    import traceback; traceback.print_exc()
