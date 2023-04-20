<^<+1:: ; by pressing left control, left shift and arrow key up
clipboard = ; Start off empty to allow ClipWait to detect when the text has arrived.
Send ^c
ClipWait ; Wait for the clipboard to contain text.
selection := clipboard
port := FileOpen("COM7", "w") ; Open for writing only, not reading/appending.
port.Write(selection) ; Write the selection to port
port.__Handle ; This flushes the write buffer.
port.Close() ; and close the Port
return
