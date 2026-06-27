@echo off
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "ORC_CALC_OCR_CACHE_DIR=%%~fI\orc_calc_ocr_cache"
set "HOME=%ORC_CALC_OCR_CACHE_DIR%\home"
set "USERPROFILE=%ORC_CALC_OCR_CACHE_DIR%\home"
set "PADDLE_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddle"
set "PADDLEOCR_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddleocr"
set "PADDLE_PDX_CACHE_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddlex"
set "XDG_CACHE_HOME=%ORC_CALC_OCR_CACHE_DIR%\xdg"
if not exist "%HOME%" mkdir "%HOME%"
if not exist "%PADDLE_PDX_CACHE_HOME%" mkdir "%PADDLE_PDX_CACHE_HOME%"
if not exist ".venv-ocr\Scripts\python.exe" (
  python -m venv .venv-ocr
)
".venv-ocr\Scripts\python.exe" -m pip install --upgrade pip
".venv-ocr\Scripts\python.exe" -m pip install paddlepaddle==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
".venv-ocr\Scripts\python.exe" -m pip install paddleocr
".venv-ocr\Scripts\python.exe" -c "from paddleocr import PaddleOCR; import paddle; print('PaddlePaddle', paddle.__version__); print('PaddleOCR ready')"
