
import os
import ctypes

cuda_bin = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\bin"
cudnn_bin = r"C:\Users\2002r\miniconda3\envs\whisper_cuda\Library\bin"

os.add_dll_directory(cuda_bin)
os.add_dll_directory(cudnn_bin)

print("Chargement de cuBLAS...")

ctypes.WinDLL(os.path.join(cuda_bin, "cublas64_12.dll"))

print("cuBLAS OK !")
