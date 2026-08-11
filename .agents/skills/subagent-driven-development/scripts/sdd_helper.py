import sys
import os
import re
import subprocess

def get_workspace_dir(plan_file):
    root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip()
    slug = os.path.splitext(os.path.basename(plan_file))[0]
    workspace = os.path.join(root, ".superpowers", "sdd", slug)
    os.makedirs(workspace, exist_ok=True)
    
    # write gitignore in .superpowers/sdd
    sdd_base = os.path.join(root, ".superpowers", "sdd")
    with open(os.path.join(sdd_base, ".gitignore"), "w") as f:
        f.write("*\n")
        
    return workspace

def extract_task_brief(plan_file, task_number):
    workspace = get_workspace_dir(plan_file)
    outfile = os.path.join(workspace, f"task-{task_number}-brief.md")
    
    with open(plan_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    infence = False
    intask = False
    task_lines = []
    
    # Matching headings like ### Task N: or # Task N or ## Task N
    task_pattern = re.compile(rf"^#+\s+Task\s+{task_number}(?![0-9])")
    next_task_pattern = re.compile(r"^#+\s+Task\s+\d+")
    
    for line in lines:
        if line.startswith("```"):
            infence = not infence
            
        if not infence:
            if next_task_pattern.match(line):
                if task_pattern.match(line):
                    intask = True
                else:
                    intask = False
                    
        if intask:
            task_lines.append(line)
            
    if not task_lines:
        print(f"Error: Task {task_number} not found in {plan_file}", file=sys.stderr)
        sys.exit(3)
        
    with open(outfile, "w", encoding="utf-8") as f:
        f.writelines(task_lines)
        
    print(f"wrote {outfile}: {len(task_lines)} lines")
    return outfile

def generate_review_package(plan_file, base, head):
    workspace = get_workspace_dir(plan_file)
    outfile = os.path.join(workspace, f"review-{base[:7]}-{head[:7]}.md")
    
    commits = subprocess.check_output(["git", "log", "--oneline", f"{base}..{head}"]).decode(errors="ignore")
    stat = subprocess.check_output(["git", "diff", "--stat", f"{base}..{head}"]).decode(errors="ignore")
    diff = subprocess.check_output(["git", "diff", "-U10", f"{base}..{head}"]).decode(errors="ignore")
    
    content = f"# Review Package\n\n## Commits\n```\n{commits}```\n\n## Stat Summary\n```\n{stat}```\n\n## Full Diff\n```diff\n{diff}```\n"
    
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(outfile)
    return outfile

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python sdd_helper.py [workspace|brief|review] PLAN_FILE ...")
        sys.exit(1)
        
    cmd = sys.argv[1]
    plan_file = sys.argv[2]
    
    if cmd == "workspace":
        print(get_workspace_dir(plan_file))
    elif cmd == "brief":
        if len(sys.argv) < 4:
            print("Usage: python sdd_helper.py brief PLAN_FILE TASK_NUMBER")
            sys.exit(1)
        extract_task_brief(plan_file, int(sys.argv[3]))
    elif cmd == "review":
        if len(sys.argv) < 5:
            print("Usage: python sdd_helper.py review PLAN_FILE BASE HEAD")
            sys.exit(1)
        generate_review_package(plan_file, sys.argv[3], sys.argv[4])
