import os
import re
import shutil
import tempfile
import subprocess

def fix_diff_chunk_headers(diff_text: str) -> str:
    """Auto-recalculate unified diff @@ -old_start,old_count +new_start,new_count @@ line counts."""
    lines = diff_text.splitlines()
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            header_match = re.match(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$", line)
            if header_match:
                old_start = header_match.group(1)
                new_start = header_match.group(2)
                rest = header_match.group(3)

                # Count hunk lines until next @@ or EOF
                j = i + 1
                old_count = 0
                new_count = 0
                while j < len(lines) and not lines[j].startswith("@@") and not lines[j].startswith("---") and not lines[j].startswith("diff --git"):
                    hline = lines[j]
                    if hline.startswith("-"):
                        old_count += 1
                    elif hline.startswith("+"):
                        new_count += 1
                    else:  # Context line (starts with space or empty)
                        old_count += 1
                        new_count += 1
                    j += 1
                
                new_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{rest}"
                fixed_lines.append(new_header)
                i += 1
                continue
        fixed_lines.append(line)
        i += 1
    return "\n".join(fixed_lines) + "\n"

def test_and_apply_patch(diff_text: str, target_repo_dir: str = ".") -> bool:
    print("[Sandbox Runner] Spinning up isolated sandbox environment...")
    temp_dir = tempfile.mkdtemp(prefix="tier2_sandbox_")
    
    # Auto-fix chunk header counts in case LLM output line counts were slightly off
    fixed_diff = fix_diff_chunk_headers(diff_text)

    try:
        # Copy repository files to sandbox
        for item in os.listdir(target_repo_dir):
            if item in [".git", "__pycache__", "venv", ".vscode"]:
                continue
            s = os.path.join(target_repo_dir, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        patch_file = os.path.join(temp_dir, "patch.diff")
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(fixed_diff)

        print("[Sandbox Runner] Applying diff in sandbox...")
        apply_res = subprocess.run(["git", "apply", "--ignore-whitespace", "--recount", "patch.diff"], cwd=temp_dir, capture_output=True, text=True)

        if apply_res.returncode != 0:
            print(f"[Sandbox Runner] Git apply failed:\n{apply_res.stderr}")
            return False

        print("[Sandbox Runner] Verifying syntax and basic compilation in sandbox...")
        py_check = subprocess.run(["python", "-m", "py_compile", os.path.join("TestProject", "app.py")], cwd=temp_dir, capture_output=True, text=True)
        if py_check.returncode != 0:
            print(f"[Sandbox Runner] Python syntax compilation failed:\n{py_check.stderr}")
            return False

        print("[Sandbox Runner] Patch verification passed! Applying patch to main repository...")
        main_patch_file = os.path.join(target_repo_dir, "patch.diff")
        with open(main_patch_file, "w", encoding="utf-8") as f:
            f.write(fixed_diff)
        
        apply_main = subprocess.run(["git", "apply", "--ignore-whitespace", "--recount", "patch.diff"], cwd=target_repo_dir, capture_output=True, text=True)
        if os.path.exists(main_patch_file):
            os.remove(main_patch_file)

        if apply_main.returncode == 0:
            print("[Sandbox Runner] Patch successfully merged into target application!")
            return True
        else:
            print(f"[Sandbox Runner] Merging patch to target repository failed:\n{apply_main.stderr}")
            return False

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
