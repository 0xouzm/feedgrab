优先使用 Git Bash 执行 `D:\Git\bin\bash.exe ./scripts/newup.sh` 进行项目预热读取；若 Git Bash 不可用，再回退执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\newup.ps1`。然后基于输出继续本轮迭代。
