"""Build the answer-shape suite for issues and attachments.

These questions are not about whether the rows are right. They are about
whether the answer is worth reading: "show me tasks which have issues"
answered with eight task ids is the correct rows and none of what was asked.

So each turn states a floor rather than an SQL. `expect_columns` is a list of
requirements, each satisfied by any one of its names -- the question does not
care whether the reader is told the department or the person, only that it is
told one of them. Extra columns are always fine.

Questions are written the way people type them: lower case, no punctuation,
the occasional wrong plural. Cleaning them up would test a phrasing nobody
uses.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

Q: list[dict] = []


def q(qid: str, category: str, question: str, columns: list[list[str]],
      note: str | None = None) -> None:
    entry: dict = {
        "id": qid,
        "category": category,
        "question": question,
        "expect_columns": columns,
    }
    if note:
        entry["note"] = note
    Q.append(entry)


# A floor asks for what the question wants to LEARN, never for what it
# filters BY. "Which issues are still open" has already said they are open;
# demanding issue_status back is demanding noise, and four of the first run's
# five failures were this mistake rather than the model's.

# Shorthands for "any column that identifies this thing to a reader".
TASK = ["task_display_name", "task_code", "task_id"]
INITIATIVE = ["initiative_ref_id", "initiative_id", "initiative_type"]
WHO_ISSUE = ["issue_sub_department", "issue_assigned_user_id", "issue_created_by_user_id",
             "user_name", "issue_department"]
FILE = ["file_name", "file_uri"]
COUNT = ["count", "total", "sum", "number"]

# ------------------------------------------------------------- issues --

q("S01", "Issue Listing", "show me task which have issues",
  [TASK, ["issue_title"], ["issue_status"], WHO_ISSUE],
  note="The question that started this. Eight task ids is the right rows and "
       "none of the answer.")
q("S02", "Issue Listing", "which issues are still open",
  [["issue_title"], TASK])
q("S03", "Issue Listing", "show me the open issues and which task they are on",
  [["issue_title"], TASK])
q("S04", "Issue Ranking", "who raises the most issues",
  [WHO_ISSUE, COUNT])
q("S05", "Issue Aggregation", "what are people complaining about the most",
  [["issue_category_name"], COUNT])
q("S06", "Issue Listing", "show issues from the design team",
  [["issue_title"], ["issue_sub_department"]])
q("S07", "Issue Listing", "whats the latest comment on our issues",
  [["last_comment"], ["issue_title"]])
q("S08", "Issue Listing", "issues nobody has commented on",
  [["issue_title"]])
q("S09", "Issue Aggregation", "which department has the most problems",
  [["issue_sub_department"], COUNT])
q("S10", "Issue Listing", "show me resolved issues and who resolved them",
  [["issue_title"], ["resolved_by", "resolver", "user_name"]])
q("S11", "Issue Listing", "what issues came up in march",
  [["issue_title"], ["issue_created_at"]])
q("S12", "Issue Aggregation", "what kind of issues do we get",
  [["issue_category_name"]])
q("S13", "Issue Listing", "issue details for task 278",
  [["issue_title"], ["issue_status"], ["issue_category_name"]])
q("S14", "Issue Join", "which initiatives have issues on their tasks",
  [INITIATIVE, ["issue_title", "issue_status", "issue_category_name"]],
  note="The issue view has no initiative column, so the answer has to travel "
       "through tms_task_flat and bring something about the issue back. This "
       "turn is unstable: it failed, passed and failed again across three runs "
       "of the same suite, so the context rule is followed inconsistently for "
       "this shape of question. Left as written -- the floor matches what was "
       "asked for, and tuning it away would hide the instability.")
q("S15", "Issue Join", "are there issues on any delayed task",
  [TASK, ["issue_title"]])

# -------------------------------------------------------- attachments --

q("T01", "Attachment Listing", "what files are attached to our initiatives",
  [FILE, INITIATIVE])
q("T02", "Attachment Listing", "show me attachments with the task they belong to",
  [FILE, TASK])
q("T03", "Attachment Ranking", "who uploads the most files",
  [["attachment_created_by_user_id", "user_name"], COUNT])
q("T04", "Attachment Listing", "biggest files we have",
  [["file_name"], ["file_size"]])
q("T05", "Attachment Listing", "what documents do we have for suiting",
  [FILE, ["folder_path", "tag_name"]])
q("T06", "Attachment Join", "attachments on active initiatives",
  [FILE, ["initiative_status", "initiative_ref_id", "initiative_id"]])
q("T07", "Attachment Listing", "which tags are actually used",
  [["tag_name"]])
q("T08", "Attachment Listing", "files uploaded recently",
  [["file_name"], ["attachment_created_at"]])
q("T09", "Attachment Listing", "show me the costing documents",
  [FILE, ["tag_name"]])
q("T10", "Attachment Aggregation", "how many files does each initiative have",
  [INITIATIVE, COUNT])
q("T11", "Attachment Join", "attachments for AR_YD_Suiting",
  [FILE, ["initiative_type", "initiative_ref_id", "initiative_id"]],
  note="initiative_name on the attachment is the tag's configuration, so the "
       "honest answer joins tms_initiative_flat.")
q("T12", "Attachment Listing", "what excel files are there",
  [["file_name"]])
q("T13", "Attachment Listing", "whats in the sales folder",
  [FILE, ["tag_name"]])
q("T14", "Attachment Aggregation", "break the attachments down by document type",
  [["tag_name"], COUNT])
q("T15", "Attachment Listing", "show me attachment details for initiative 292",
  [FILE, ["tag_name"]])

HEADER = """# Answer shape: are these answers worth reading?
#
# 30 questions about issues and attachments, phrased the way people type them.
# None of them states an expected SQL, because more than one query is usually
# right and the query is not what is being tested. Each states a floor instead:
# the columns the answer has to carry before it is any use to the person who
# asked.
#
# Written after "show me task which have issues" came back as eight task ids.
# Correct rows. Nothing about the issues, who raised them, or what they were.
# Row comparison cannot see that, so the projection is checked directly.
#
# Each entry in expect_columns is satisfied by ANY of its names: a reader who
# wanted to know where an issue came from is served by the department or by
# the person, and the suite should not insist on which. Extra columns never
# fail a turn -- this is a floor, not a ceiling.
"""

doc = {"version": 1, "questions": Q}
out = pathlib.Path(__file__).resolve().parents[1] / "benchmark" / "answer_shape_questions.yaml"
out.write_text(HEADER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
               encoding="utf-8")
print(f"wrote {len(Q)} questions to {out.name}")
