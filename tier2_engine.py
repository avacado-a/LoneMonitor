import json
import os
import re
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
7. Use forward slashes in relative paths: `--- a/path/to/file` and `+++ b/path/to/file`. Do not use Windows backslashes.
"""

def extract_diff(ai_response: str) -> str:
    # Extract diff block
    match = re.search(r"```(?:diff)?\n(diff --git.*?)```", ai_response, re.DOTALL)
    if match:
        diff_text = match.group(1).strip()
    else:
        match_fallback = re.search(r"(--- a/.*?\n\+\+\+ b/.*?\n@@.*)", ai_response, re.DOTALL)
        if match_fallback:
            diff_text = match_fallback.group(1).strip()
        else:
            diff_text = ai_response.strip()

    # Clean any trailing ``` fence if present
    if diff_text.endswith("```"):
        diff_text = diff_text[:-3].strip()

    # Normalize Windows backslashes to forward slashes in diff headers
    diff_text = re.sub(r"--- a/([^\n\r]+)", lambda m: "--- a/" + m.group(1).replace("\\", "/"), diff_text)
    diff_text = re.sub(r"\+\+\+ b/([^\n\r]+)", lambda m: "+++ b/" + m.group(1).replace("\\", "/"), diff_text)

    return diff_text

def validate_diff_size(diff_text: str) -> bool:
    lines = diff_text.splitlines()
    changed_lines = [l for l in lines if l.startswith('+') or l.startswith('-')]
    # Exclude header lines
    changed_lines = [l for l in changed_lines if not (l.startswith('+++') or l.startswith('---'))]
    return len(changed_lines) <= MAX_DIFF_LINES

def analyze_and_patch(payload: dict) -> dict:
    affected = payload.get("affected_files", ["target_app.py"])
    module = affected[0] if affected else "target_app.py"
    
    # Normalize module key for circuit breaker tracking
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
