#!/usr/bin/env python3
"""Helper to execute code in Inkscape via inkmcp D-Bus bridge."""
import json, os, sys, tempfile, subprocess, time

sys.path.insert(0, os.path.expanduser("~/.config/inkscape/extensions/inkmcp"))
from inkmcpcli import parse_command_string

def run_code(code: str, timeout: int = 30) -> dict:
    parsed = parse_command_string("execute-code code='" + code.replace("'", "\\'") + "'")
    response_file = os.path.join(tempfile.gettempdir(), f'mcp_resp_{os.getpid()}.json')
    parsed['response_file'] = response_file

    params_file = os.path.join(tempfile.gettempdir(), 'mcp_params.json')
    with open(params_file, 'w') as f:
        json.dump(parsed, f)

    cmd = [
        'gdbus', 'call', '--session',
        '--dest', 'org.inkscape.Inkscape',
        '--object-path', '/org/inkscape/Inkscape',
        '--method', 'org.gtk.Actions.Activate',
        'org.khema.inkscape.mcp', '[]', '{}',
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    time.sleep(0.5)

    if os.path.exists(response_file):
        with open(response_file) as f:
            data = json.load(f)
        os.remove(response_file)
        return data
    return {"status": "error", "data": {"error": "No response file"}}

def exec_and_print(code: str):
    result = run_code(code)
    data = result.get("data", {})
    if data.get("output"):
        print(data["output"])
    if data.get("errors"):
        print("ERROR:", data["errors"])
    if data.get("execution_successful") is False:
        print("FAILED")
    else:
        print("OK")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        exec_and_print(sys.argv[1])
