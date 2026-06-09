import subprocess

# List window titles
ps = '''
Get-Process | Where-Object { $_.MainWindowTitle -ne "" } | Select-Object MainWindowTitle | Sort-Object MainWindowTitle
'''
r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True)
print(r.stdout)
