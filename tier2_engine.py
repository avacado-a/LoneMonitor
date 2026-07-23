import os
import re
import sys
import time
import json
import shutil
import tempfile
import py_compile  # FIXED: Corrected standard library module name
import subprocess
import ai

CIRCUIT_BREAKER = {}
MAX_PATCH_ATTEMPTS = 2
MAX_DIFF_LINES = 50

SYSTEM_PROMPT = """SYSTEM INSTRUCTION: You are an autonomous software engineering and security agent.
Your objective is to fix a production issue using the minimum necessary code changes.

RULES:
1. Output ONLY a valid Unified Git Diff inside a ```diff code block.
2. Ensure every unchanged line in the diff starts with a single space ' '.
3. Include valid chunk headers (e.g., @@ -15,8 +15,9 @@).
4. Do NOT rewrite unrelated code, refactor existing structures, or add new features.
5. Modify at most 50 lines of code across all files.
6. Ensure the patch handles edge cases, null inputs, or state cleanup safely.
7. Use forward slashes in relative paths: `--- a/path/to/file` and `+++ b/path/to/file`.
"""

def build_payload(error_type: str, stack_trace: str, recent_logs: list, affected_files: list = None, pid: int = None) -> dict:
    """Packages runtime error context into a diagnostic JSON payload."""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "error_type": error_type,
        "stack_trace": stack_trace,
        "recent_logs": recent_logs[-30:] if recent_logs else [],
        "affected_files": affected_files or ["target_app.py"],
        "process_id": pid
    }

def fix_diff_chunk_headers(diff_text: str) -> str:
    """Recalculates unified diff hunk line counts (@@ -old,count +new,count @@)."""
    lines = diff_text.splitlines()
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@ "):
            header_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$", line)
            if header_match:
                old_start = int(header_match.group(1))
                new_start = int(header_match.group(2))
                suffix = header_match.group(3)
                
                hunk_lines = []
                j = i + 1
                while j < len(lines) and not lines[j].startswith("@@ ") and not lines[j].startswith("diff --git"):
                    hunk_lines.append(lines[j])
                    j += 1
                
                old_count = sum(1 for hl in hunk_lines if hl.startswith(" ") or hl.startswith("-"))
                new_count = sum(1 for hl in hunk_lines if hl.startswith(" ") or hl.startswith("+"))
                
                fixed_lines.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}")
                fixed_lines.extend(hunk_lines)
                i = j
                continue
        fixed_lines.append(line)
        i += 1
    return "\n".join(fixed_lines) + ("\n" if diff_text.endswith("\n") else "")

def extract_diff(ai_response: str) -> str:
    """Extracts unified diff block from LLM markdown response."""
    match = re.search(r"```(?:diff)?\n(diff --git.*?)```", ai_response, re.DOTALL)
    if match:
        diff_text = match.group(1).strip()
    else:
        match_fallback = re.search(r"(--- a/.*?\n\+\+\+ b/.*?\n@@.*)", ai_response, re.DOTALL)
        if match_fallback:
            diff_text = match_fallback.group(1).strip()
        else:
            diff_text = ai_response.strip()

    if diff_text.endswith("```"):
        diff_text = diff_text[:-3].strip()

    diff_text = re.sub(r"--- a/([^\n\r]+)", lambda m: "--- a/" + m.group(1).replace("\\", "/"), diff_text)
    diff_text = re.sub(r"\+\+\+ b/([^\n\r]+)", lambda m: "+++ b/" + m.group(1).replace("\\", "/"), diff_text)

    return diff_text

def validate_diff_size(diff_text: str) -> bool:
    lines = diff_text.splitlines()
    changed_lines = [l for l in lines if (l.startswith('+') or l.startswith('-')) and not (l.startswith('+++') or l.startswith('---'))]
    return len(changed_lines) <= MAX_DIFF_LINES

def test_and_apply_patch(diff_text: str, repo_dir: str = ".") -> bool:
    """Verifies patch in an isolated temporary sandbox before merging into production."""
    fixed_diff = fix_diff_chunk_headers(diff_text)
    temp_dir = tempfile.mkdtemp(prefix="lone_sandbox_")
    
    try:
        for item in os.listdir(repo_dir):
            if item in [".git", "__pycache__", "logs", "scratch", ".venv"]:
                continue
            s = os.path.join(repo_dir, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        
        diff_file = os.path.join(temp_dir, "patch.diff")
        with open(diff_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(fixed_diff)

        # Attempt git apply
        res = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "--recount", "patch.diff"],
            cwd=temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if res.returncode != 0:
            print(f"[Sandbox Runner] Git apply failed:\n{res.stderr}")
            return False

        # Compile check using py_compile
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    try:
                        py_compile.compile(full_path, doraise=True)
                    except Exception as err:
                        print(f"[Sandbox Runner] Syntax compilation check failed for {file}: {err}")
                        return False

        prod_patch = os.path.join(repo_dir, "temp_patch.diff")
        with open(prod_patch, "w", encoding="utf-8", newline="\n") as f:
            f.write(fixed_diff)
            
        prod_apply = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "--recount", "temp_patch.diff"],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if os.path.exists(prod_patch):
            os.remove(prod_patch)

        return prod_apply.returncode == 0

    except Exception as e:
        print(f"[Sandbox Runner] Exception during verification: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def analyze_and_patch(payload: dict) -> dict:
    """Dispatches payload to Tier 2 AI engine and verifies patches."""
    affected = payload.get("affected_files", ["target_app.py"])
    module = affected[0] if affected else "target_app.py"
    
    norm_module = os.path.normpath(module).replace("\\", "/").lower()
    attempts = CIRCUIT_BREAKER.get(norm_module, 0)
    
    if attempts >= MAX_PATCH_ATTEMPTS:
        print(f"[Tier 2 Circuit Breaker] Max patch attempts ({MAX_PATCH_ATTEMPTS}) reached for module '{module}'. Freezing auto-remediation.")
        return {"status": "circuit_breaker_tripped", "module": module}

    CIRCUIT_BREAKER[norm_module] = attempts + 1

    file_content = ""
    if os.path.exists(module):
        with open(module, "r", encoding="utf-8") as f:
            file_content = f.read()

    prompt_content = f"DIAGNOSTIC PAYLOAD:\n{json.dumps(payload, indent=2)}\n\nFILE CONTENT OF {module}:\n```python\n{file_content}\n```"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt_content}
    ]

    print(f"[Tier 2 Engine] Invoking AI model via ai.py (Attempt {CIRCUIT_BREAKER[norm_module]}/{MAX_PATCH_ATTEMPTS})...")
    ai_response = ai.request(messages, temperature=0.1)
    diff = extract_diff(ai_response)

    if not validate_diff_size(diff):
        print(f"[Tier 2 Engine] Generated patch exceeded {MAX_DIFF_LINES} changed lines limit.")
        return {"status": "failed", "reason": "diff_too_large"}

    return {
        "status": "patch_generated",
        "diff": diff,
        "module": module,
        "attempt": CIRCUIT_BREAKER[norm_module]
    }
