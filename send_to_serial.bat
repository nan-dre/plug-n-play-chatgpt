setlocal enabledelayedexpansion
set /a chunk_size=200
set "filename=text.txt"

powershell.exe -command "Get-Clipboard > %filename%"
pause

for /F "usebackq delims=" %%A in (`powershell -Command "Get-Content -Raw -Path '%filename%' | foreach { $chunk = $_.ToCharArray(); $i = 0; while ($i -lt $chunk.Length) { $start = $i; $end = $i + %chunk_size% - 1; if ($end -ge $chunk.Length) { $end = $chunk.Length - 1 }; $chunk[$start..$end] -join ''; $i += %chunk_size% } }"`) do (
    mode COM7: baud=115200 data=8 parity=n stop=1 xon=on to=off 
    echo %%A >COM7
    mode COM7: baud=115200 data=8 parity=n stop=1 xon=off to=off 
    mode COM7: baud=115200 data=8 parity=n stop=1 xon=off to=off 
)