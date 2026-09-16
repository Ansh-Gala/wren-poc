import pathlib, sys, yaml
sys.path.insert(0, r"C:\Users\ansh.gala\Desktop\Python\wren-poc")

Q = []
def q(i, cat, question, sql, behavior=None):
    e = {"id": i, "category": cat, "question": question, "expected_sql": " ".join(sql.split())}
    if behavior:
        e["expect_behavior"] = behavior
    Q.append(e)

A = "tms_attachment_flat"
T = "tms_task_issue_flat"

# ---------------- tms_attachment_flat ----------------
q("A01", "Count", "How many attachments are there?", f"SELECT COUNT(*) FROM {A}")
q("A02", "Distinct", "How many initiatives have at least one attachment?", f"SELECT COUNT(DISTINCT initiative_id) FROM {A}")
q("A03", "Basic List", "Show the attachments with their file names and tags", f"SELECT tag_name, file_name, initiative_id, task_id FROM {A}")
q("A04", "Aggregation", "How many attachments are there for each tag?", f"SELECT tag_name, COUNT(*) FROM {A} GROUP BY tag_name ORDER BY COUNT(*) DESC")
q("A05", "Ranking", "Which attachment tag is used most often?", f"SELECT tag_name, COUNT(*) FROM {A} GROUP BY tag_name ORDER BY COUNT(*) DESC LIMIT 1")
q("A06", "Aggregation", "What is the total size of all attached files?", f"SELECT SUM(file_size) FROM {A}")
q("A07", "Sort + Limit", "Which is the largest attached file?", f"SELECT file_name, file_size FROM {A} ORDER BY file_size DESC LIMIT 1")
q("A08", "Aggregation", "How many attachments are in each folder?", f"SELECT folder_path, COUNT(*) FROM {A} GROUP BY folder_path ORDER BY COUNT(*) DESC")
q("A09", "Dimension Filter", "Show attachments filed under ArvindRetail/Suiting", f"SELECT tag_name, file_name FROM {A} WHERE folder_path = 'ArvindRetail/Suiting'")
q("A10", "Join", "How many attachments did each user upload, by user name?", f"SELECT u.user_name, COUNT(*) FROM {A} a JOIN tms_user_flat u ON u.user_id = a.attachment_created_by_user_id GROUP BY u.user_name ORDER BY COUNT(*) DESC")
q("A11", "Join", "How many attachments belong to active initiatives?", f"SELECT COUNT(*) FROM {A} a JOIN tms_initiative_flat i ON i.initiative_id = a.initiative_id WHERE i.initiative_status = 'Active'")
q("A12", "Join", "How many attachments are on AR_YD_Suiting initiatives?", f"SELECT COUNT(*) FROM {A} a JOIN tms_initiative_flat i ON i.initiative_id = a.initiative_id WHERE i.initiative_type = 'AR_YD_Suiting'")
q("A13", "Aggregation", "What is the average attached file size?", f"SELECT AVG(file_size) FROM {A}")
q("A14", "Ranking", "Which four initiatives have the most attachments, by initiative id?", f"SELECT initiative_id, COUNT(*) FROM {A} GROUP BY initiative_id ORDER BY COUNT(*) DESC LIMIT 4")
q("A15", "Distinct", "How many distinct files are attached?", f"SELECT COUNT(DISTINCT file_name) FROM {A}")
q("A16", "Dimension Filter", "Show the attachments tagged EPI PPI Sheet", f"SELECT file_name, initiative_id, task_id FROM {A} WHERE tag_name = 'EPI PPI Sheet'")
q("A17", "Task Filter", "Which attachment is on task 30?", f"SELECT tag_name, file_name FROM {A} WHERE task_id = 30")
q("A18", "Date Filter", "How many attachments were uploaded in 2026?", f"SELECT COUNT(*) FROM {A} WHERE attachment_created_at >= '2026-01-01' AND attachment_created_at < '2027-01-01'")
q("A19", "Sort", "Show the five most recently uploaded attachments", f"SELECT file_name, attachment_created_at FROM {A} ORDER BY attachment_created_at DESC LIMIT 5")
q("A20", "Semantic Rule", "What file size does the tag Costing files from each vendor allow?", f"SELECT DISTINCT max_file_size FROM {A} WHERE tag_name = 'Costing files from each vendor'")
q("A21", "Join", "Which business units have attachments?", f"SELECT DISTINCT i.business_unit FROM {A} a JOIN tms_initiative_flat i ON i.initiative_id = a.initiative_id")
q("A22", "Aggregation", "How many attachments are there for each initiative type the tag applies to?", f"SELECT initiative_name, COUNT(*) FROM {A} GROUP BY initiative_name ORDER BY COUNT(*) DESC")
q("A23", "Null Handling", "Are there any attachments that are not active?", f"SELECT COUNT(*) FROM {A} WHERE status <> 'active'", behavior="zero_or_clarify")

# ---------------- tms_task_issue_flat ----------------
q("I01", "Count", "How many task issues are there?", f"SELECT COUNT(*) FROM {T}")
q("I02", "Status Filter", "How many issues are open?", f"SELECT COUNT(*) FROM {T} WHERE issue_status = 'open'")
q("I03", "Status Filter", "How many issues are resolved?", f"SELECT COUNT(*) FROM {T} WHERE issue_status = 'resolved'")
q("I04", "Status Filter", "How many issues are closed?", f"SELECT COUNT(*) FROM {T} WHERE issue_status = 'closed'")
q("I05", "Aggregation", "Break the issues down by status", f"SELECT issue_status, COUNT(*) FROM {T} GROUP BY issue_status ORDER BY COUNT(*) DESC")
q("I06", "Aggregation", "How many issues are there in each category?", f"SELECT issue_category_name, COUNT(*) FROM {T} GROUP BY issue_category_name ORDER BY COUNT(*) DESC")
q("I07", "Aggregation", "How many issues has each sub-department raised?", f"SELECT issue_sub_department, COUNT(*) FROM {T} GROUP BY issue_sub_department ORDER BY COUNT(*) DESC")
q("I08", "Count", "How many issues have at least one comment?", f"SELECT COUNT(*) FROM {T} WHERE comment_count > 0")
q("I09", "Aggregation", "How many comments are there on issues in total?", f"SELECT SUM(comment_count) FROM {T}")
q("I10", "Sort + Limit", "Which issue has the most comments?", f"SELECT issue_title, comment_count FROM {T} ORDER BY comment_count DESC LIMIT 1")
q("I11", "Distinct", "How many tasks have issues raised against them?", f"SELECT COUNT(DISTINCT task_id) FROM {T}")
q("I12", "Task Filter", "Show the issues raised on task 2", f"SELECT issue_title, issue_status, issue_category_name FROM {T} WHERE task_id = 2")
q("I13", "Null Handling", "How many issues have not been resolved yet?", f"SELECT COUNT(*) FROM {T} WHERE issue_resolved_at IS NULL")
q("I14", "Null Handling", "How many issues have never been commented on?", f"SELECT COUNT(*) FROM {T} WHERE comment_count = 0")
q("I15", "Dimension Filter", "Show the issues caused by a delay from the vendor", f"SELECT issue_title, issue_status FROM {T} WHERE issue_category_name = 'Delay from Vendor'")
q("I16", "Dimension Filter", "Which issues did the Design Team raise?", f"SELECT issue_title, issue_status FROM {T} WHERE issue_sub_department = 'Design Team'")
q("I17", "Aggregation", "How many issues is each user assigned?", f"SELECT issue_assigned_user_id, COUNT(*) FROM {T} GROUP BY issue_assigned_user_id ORDER BY COUNT(*) DESC")
q("I18", "Join", "How many issues are on open tasks?", f"SELECT COUNT(*) FROM {T} i JOIN tms_task_flat t ON t.task_id = i.task_id WHERE t.task_status = 'open'")
q("I19", "Join", "Which initiatives have issues raised against their tasks?", f"SELECT DISTINCT t.initiative_id FROM {T} i JOIN tms_task_flat t ON t.task_id = i.task_id")
q("I20", "Join", "How many issues are on AR_NPD_YD_SHIRTING initiatives?", f"SELECT COUNT(*) FROM {T} i JOIN tms_task_flat t ON t.task_id = i.task_id WHERE t.initiative_type = 'AR_NPD_YD_SHIRTING'")
q("I21", "Sort", "Show the five most recently raised issues", f"SELECT issue_title, issue_created_at FROM {T} ORDER BY issue_created_at DESC LIMIT 5")
q("I22", "Aggregation", "What is the average number of comments per issue?", f"SELECT AVG(comment_count) FROM {T}")
q("I23", "Date Filter", "How many issues were raised in March 2026?", f"SELECT COUNT(*) FROM {T} WHERE issue_created_at >= '2026-03-01' AND issue_created_at < '2026-04-01'")

HEADER = """# Attachments and task issues: a targeted suite for the two views added on
# 16 September 2026.
#
# 23 questions against tms_attachment_flat and 23 against tms_task_issue_flat.
# Every expected result below was executed against the live database before the
# question was accepted; nothing here is assumed.
#
# The suite deliberately carries the confusions these two views invite:
#   A12      initiative_name holds a TYPE and describes the tag, so a question
#            about the Initiative's own type must join tms_initiative_flat
#   A20      max_file_size is the tag's limit, file_size is the file itself
#   A23      status is 'active' in every row, so there are no inactive ones
#   I03      only issues are ever 'resolved'; tms_task_flat has no such status
#   I11      25 issues fall on 8 tasks, so COUNT(*) and COUNT(DISTINCT task_id)
#            answer different questions
#   I19/I20  the issue view carries no Initiative column and must reach one
#            through tms_task_flat
"""

doc = {"version": 1, "questions": Q}
out = pathlib.Path(r"C:\Users\ansh.gala\Desktop\Python\wren-poc\benchmark\new_views_questions.yaml")
out.write_text(HEADER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
print(f"wrote {len(Q)} questions to {out.name}")
