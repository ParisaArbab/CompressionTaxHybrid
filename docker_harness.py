"""
WP1 - Task 1: local agent framework connected to a subset of SWE-bench repos.

This uses the official `swebench` docker images (one per instance) so the
captured stdout/stderr is the *real* terminal output a coding agent would see
-- not a simulation. Requires Docker and non-trivial disk space (each image
is a full pinned environment for the target repo/commit).

We capture two raw artifacts per instance, matching what an FL agent
typically runs:
  1. the FAIL_TO_PASS test run against the *buggy* base_commit (this is what
     Work Package 1 evaluates: "can the agent localize the bug from this
     terminal output alone").
  2. exit code / duration, for bookkeeping.

If Docker is not available in the current environment, `--offline` falls
back to writing a clearly-marked placeholder so the rest of the pipeline
(compression + agent + report) can still be exercised end to end.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

try:
    from swebench.harness.constants import KEY_INSTANCE_ID
    from swebench.harness.utils import get_test_directives
    from swebench.harness.docker_build import build_env_images, build_instance_images
    from swebench.harness.test_spec.test_spec import make_test_spec
    HAVE_SWEBENCH = True
except Exception:
    HAVE_SWEBENCH = False


def run_in_docker(instance: dict, timeout: int = 900) -> dict:
    """Build (if needed) and run the instance's official docker image,
    executing the FAIL_TO_PASS tests at base_commit, returning raw stdout."""
    test_spec = make_test_spec(instance)
    image_name = test_spec.instance_image_key

    subprocess.run(["docker", "pull", image_name], check=False,
                    capture_output=True, text=True)

    run_cmd = test_spec.eval_script  # official pre/post/run script for this instance
    proc = subprocess.run(
        ["docker", "run", "--rm", image_name, "bash", "-c", run_cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return {
        "instance_id": instance["instance_id"],
        "returncode": proc.returncode,
        "raw_stdout": proc.stdout,
        "raw_stderr": proc.stderr,
    }


def offline_placeholder(instance: dict) -> dict:
    return {
        "instance_id": instance["instance_id"],
        "returncode": None,
        "raw_stdout": "[OFFLINE PLACEHOLDER — no docker runtime available in this "
                       "environment. Re-run docker_harness.py on a machine with Docker "
                       "to capture the genuine pytest/unittest terminal output for "
                       f"{instance['instance_id']}. Expected FAIL_TO_PASS tests: "
                       f"{instance['FAIL_TO_PASS']}]",
        "raw_stderr": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="data/instances.jsonl")
    ap.add_argument("--out", default="data/raw_logs.jsonl")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    recs = [json.loads(l) for l in Path(args.instances).open()]
    if args.limit:
        recs = recs[: args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w") as f:
        for inst in recs:
            t0 = time.time()
            if args.offline or not HAVE_SWEBENCH:
                result = offline_placeholder(inst)
            else:
                try:
                    result = run_in_docker(inst)
                except Exception as e:
                    result = offline_placeholder(inst)
                    result["raw_stderr"] = f"docker run failed: {e}"
            result["duration_s"] = round(time.time() - t0, 1)
            f.write(json.dumps(result) + "\n")
            print(f"{inst['instance_id']}: {len(result['raw_stdout'])} chars raw stdout "
                  f"({result['duration_s']}s)")


if __name__ == "__main__":
    main()
