import subprocess, os
from PIL import ImageGrab

# Find 东方财富 window position
ps = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT lpRect);
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$procs = Get-Process | Where-Object { $_.MainWindowTitle -match '东方|财富|dfcf' }
foreach ($p in $procs) {
    $hwnd = $p.MainWindowHandle
    if ($hwnd -ne 0) {
        $rect = New-Object Win+RECT
        [Win]::GetWindowRect($hwnd, [ref]$rect)
        Write-Host "$($p.MainWindowTitle) | Handle=$hwnd | Left=$($rect.Left) Top=$($rect.Top) Right=$($rect.Right) Bottom=$($rect.Bottom)"
    }
}
'''
r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True)
print("Windows found:")
print(r.stdout)
print(r.stderr if r.stderr else "")

# Take a full screenshot and save
img = ImageGrab.grab()
save_path = r"C:\Users\Administrator\Desktop\t_trader\screen_full.png"
img.save(save_path)
print(f"Full screenshot saved: {save_path} ({img.size})")
