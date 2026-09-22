"""Call the Claude CLI exactly as the chatbot does, and keep the raw stream.

    python ask_cli.py "your question here"

Writes three files next to itself:
    _out/system_prompt.txt   what the CLI is given as its system prompt
    _out/raw_stdout.jsonl    every event line, untouched
    _out/result.json         just the final result event
"""
import json, pathlib, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent / "scripts"))
import _bootstrap  # noqa
from claude.prompts import build_lean_system_prompt, build_user_prompt

question = " ".join(sys.argv[1:]) or "Which workflow has the most tasks?"
out = pathlib.Path(__file__).parent / "_out"
out.mkdir(exist_ok=True)

sys_file = out / "system_prompt.txt"
sys_file.write_text(build_lean_system_prompt(), encoding="utf-8")
user_prompt = build_user_prompt(question, None, context=None, lean=True)

argv = [
    "claude", "-p", user_prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--system-prompt-file", str(sys_file),
    "--tools", "",
    "--permission-mode", "bypassPermissions",
]

print(f"question    : {question}")
print(f"system chars: {len(sys_file.read_text(encoding='utf-8'))}")
print(f"user prompt : {user_prompt!r}")
print("calling claude ...")

start = time.time()
proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=180)
elapsed = time.time() - start

(out / "raw_stdout.jsonl").write_text(proc.stdout, encoding="utf-8")
lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip().startswith("{")]

print(f"\nexit {proc.returncode} in {elapsed:.1f}s | {len(proc.stdout)} bytes | {len(lines)} events")
print(f"{'#':>3} | {'bytes':>6} | type / subtype")
for i, e in enumerate(lines, 1):
    tag = e.get("type", "?")
    if e.get("subtype"):
        tag += "/" + e["subtype"]
    if tag == "assistant":
        tag += " [" + ",".join(b.get("type", "?") for b in e["message"]["content"]) + "]"
    print(f"{i:>3} | {len(json.dumps(e)):>6} | {tag}")

result = next((e for e in lines if e.get("type") == "result"), None)
if result:
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\ncost ${result.get('total_cost_usd')} | ttft {result.get('ttft_ms')}ms | stop {result.get('stop_reason')}")
    print(f"\n--- result_text ({len(result.get('result',''))} chars) — this is what the pipeline parses ---")
    print(result.get("result", ""))
if proc.stderr.strip():
    print(f"\n--- stderr ---\n{proc.stderr.strip()[:2000]}")
