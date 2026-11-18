"""Source fixture: actual parser/handler; no board, credentials or dispatch."""
from copy import deepcopy
import json

from shantytown.cli import build_parser
from shantytown.sd import SdTracker
from shantytown.work_item import command


class Fixture(SdTracker):
    def __init__(self):
        self.rows = {name: dict(id=name, revision=1, assignee="author",
                               labels=["blocked:external"], comments=[])
                     for name in ("task-1", "task-2")}

    def stranded_read(self, name):
        return deepcopy(self.rows[name])

    def update(self, name, **fields):
        row = self.rows[name]
        assert fields["if_revision"] == row["revision"]
        row["labels"] = fields["set_labels"].split(",")
        row["revision"] += 1
        row["comments"].append({"text": fields["transition_comment"]})


fixture = Fixture()
for words in (["task-1", "--reviewer", "peer"],
              ["task-2", "--inherit-from", "task-1"],
              ["task-2", "--reviewer", "second-peer"], ["task-2"]):
    print("st work item review-reservation " + " ".join(words))
    try:
        result = command(build_parser().parse_args(
            ["work", "item", "review-reservation", *words]), fixture)
        print(json.dumps(result, sort_keys=True))
    except ValueError as error:
        print("REFUSED: " + str(error))
print("Preserved gate: " + json.dumps(fixture.rows["task-2"]["labels"]))
