"""All 64 basis input pairs, with eight independent measurement records per pair."""

from typing import Any

from uncompute.evalcore.task import RegSpec, Task, TestCase

from qdiscover.toy_task.reference import inverse


class InverseTask(Task):
    name = "toy-gf-inverse"
    seed_domain = b"qdiscover/toy-gf-inverse/v1"
    num_tests = 512

    def schema(self) -> list[RegSpec]:
        return [RegSpec(width=3), RegSpec(width=3)]

    def gen_test_indexed(self, shot: int, xof: Any) -> TestCase:
        x, y = shot % 8, (shot // 8) % 8
        return TestCase(inputs=[x, y], expected=[x, y ^ inverse(x)])


TASK = InverseTask()
