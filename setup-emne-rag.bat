@echo off
rem EmneKlar - install the optional local models for Emne-RAG (embedding, reranking, speech-to-text).
rem Downloads several GB (PyTorch). Same as "setup.bat --rag"; update.bat keeps them installed afterwards.
rem Keep this file ASCII-only: cmd.exe reads it with the OEM code page.
call "%~dp0setup.bat" --rag %*
exit /b %ERRORLEVEL%
