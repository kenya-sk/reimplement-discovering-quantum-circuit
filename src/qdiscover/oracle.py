"""Classical reference query process for model providers."""

import json
import sys

from qdiscover.catalog import load_task_module, task_dir


def main() -> None:
    task, function, arguments = sys.argv[1:]
    if function.startswith("_"):
        raise ValueError("Only public reference functions may be queried")
    module = load_task_module(task_dir(task), "reference")
    fn = getattr(module, function)
    result = fn(*json.loads(arguments))
    print(json.dumps(result, default=lambda value: value.tolist()))


if __name__ == "__main__":
    main()
