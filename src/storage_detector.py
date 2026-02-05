import os
import json
import subprocess

def get_drive_letter(path: str) -> str:
    return os.path.splitdrive(os.path.abspath(path))[0].upper()

def get_media_type(path: str) -> str:
    """
    return: 'SSD' | 'HDD' | 'UNKNOWN'
    """
    drive = get_drive_letter(path).replace(":", "")

    ps = f"""
    $p = Get-Partition -DriveLetter {drive} -ErrorAction SilentlyContinue
    if ($null -eq $p) {{
        @{{type="UNKNOWN"}} | ConvertTo-Json
        exit
    }}
    $disk = Get-Disk -Number $p.DiskNumber
    @{{type=$disk.MediaType.ToString()}} | ConvertTo-Json
    """

    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True
        )
        t = json.loads(out).get("type", "").upper()
        if "SSD" in t:
            return "SSD"
        if "HDD" in t:
            return "HDD"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"
