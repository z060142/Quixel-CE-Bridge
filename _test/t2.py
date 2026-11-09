import os, sys, types, faulthandler
faulthandler.enable()
print("a", flush=True)
HERE = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.insert(0, r"S:\Crytek\cryengine-57-lts\5.7.1\bin\win_x64")
from PySide2 import QtWidgets
print("b", flush=True)
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
print("c", flush=True)
