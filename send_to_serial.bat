powershell.exe -command "Get-Clipboard > ./text.txt"
mode COM7: baud=115200 data=8 parity=n stop=1 xon=on to=off 
type text.txt >COM7
mode COM7: baud=115200 data=8 parity=n stop=1 xon=off to=off 
mode COM7: baud=115200 data=8 parity=n stop=1 xon=off to=off 