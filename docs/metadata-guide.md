# How to write the chatbot metadata

This guide tells you how to write the metadata for a new product.

The chatbot code stays the same for each product. Most of the change is in the metadata files.
The metadata tells the AI model about your database and your business words.

A new product also needs these changes outside the metadata:

- **The views.** Each view that the metadata names must exist in the database. In Drupal, the view SQL is in `sql/views/`.
- **The freshness notice.** In Drupal, set `freshness_tables` and `freshness_message` in `vf_sql_chatbot.settings.yml`. Today they name the TMS tables.
- **The popups.** A popup that `product.yaml` names must exist in the frontend app.

Read this guide one time from start to end. Then use the checklist in section 11.

All the examples use one sample product, **Service Desk**. Change the names to the names of your product.

---

## 1. The six files

The files are in the `metadata/` folder.

| File | What it tells | Who reads it |
| --- | --- | --- |
| `schema_description.yaml` | The tables, the columns, and what each column means | The AI model |
| `business_rules.yaml` | What your business words mean in SQL | The AI model |
| `question_sql_pairs.yaml` | Sample questions, each with its correct SQL | The AI model |
| `column_hierarchy.yaml` | The order of the columns on the screen, and the columns that start hidden | The screen, and the follow-up suggestions |
| `product.yaml` | The things people ask about, the links, the signed-in user, and the product words | The code, the screen, and part of the AI prompt |
| `product.schema.json` | The rules for `product.yaml` | Nobody edits it. Do not change it. |

There are two copies of these files:

- Python repo: `metadata/`
- Drupal module: `web/modules/custom/vf_sql_chatbot/metadata/`

The two copies must be the same, byte for byte. Save the files with LF line endings, not CRLF.

---

## 2. Before you write

Get these facts from the people who know the product. Write them down first.

1. **The views.** The list of database views the chatbot can read. Use flat views: one view for each thing people ask about.
2. **One row.** For each view, what one row is. Example: "one row for each ticket".
3. **The words.** The words people use for each thing. Example: people say "ticket" and "case" for the same thing.
4. **The statuses.** Each status value and what it means.
5. **The defaults.** What a short question means. Example: "show my tickets" means the open tickets only.
6. **The traps.** Data that can cause a wrong answer. Examples: a column is always empty; the text `NA` is used in place of NULL; a join makes rows repeat.
7. **Real questions.** 10 to 20 questions that real users ask.

Write the files in this order:

```
schema_description  →  business_rules  →  question_sql_pairs  →  column_hierarchy  →  product.yaml
```

Each file uses names from the files before it.

---

## 3. The sample product

Service Desk has two views.

| View | One row is |
| --- | --- |
| `sd_ticket_flat` | One support ticket |
| `sd_user_flat` | One user (a support agent) |

---

## 4. File 1: `schema_description.yaml`

This file tells the model which tables and columns exist, and what they mean.

### Shape

```yaml
tables:
  <view name>:
    description: <what one row is, and what the view holds>
    primary_key: <column>
    columns:
      <column name>:
        type: <database type>
        description: <what the value means>

relationships:
  - name: <short name>
    from: <view.column>
    to: <view.column>
    join_type: MANY_TO_ONE

terminology:
  <business word>: <its meaning>
```

### Example

```yaml
tables:
  sd_ticket_flat:
    description: One row for each support ticket, open and closed. Also called a case.
    primary_key: ticket_id
    columns:
      ticket_id:
        type: INTEGER
        description: 'Unique id of the ticket. A bare number after "ticket" or "case" means
          this column: "ticket 1042" is ticket_id = 1042. INTEGER, so write the number
          without quotes.'
      ticket_ref:
        type: VARCHAR
        description: 'Reference number that users see, such as SD-1042. Use it only when the
          question asks for a reference number.'
      ticket_title:
        type: VARCHAR
        description: Short title of the ticket.
      ticket_status:
        type: VARCHAR
        description: 'Status of the ticket, lowercase: open or closed. Use this column for
          every status filter and every status count.'
      sla_status:
        type: VARCHAR
        description: 'On time or Late. Late means the ticket passed its due time. This is
          not a status: a Late ticket can be open or closed.'
      priority:
        type: VARCHAR
        description: Priority of the ticket, P1 (highest) to P4 (lowest).
      team:
        type: VARCHAR
        description: Team that owns the ticket, such as Network or Billing.
      assigned_user_id:
        type: INTEGER
        description: User id of the agent who has the ticket. NULL means nobody has it.
      created_at:
        type: TIMESTAMP
        description: Date and time when the ticket was opened.
      closed_at:
        type: TIMESTAMP
        description: Date and time when the ticket was closed. NULL while it is open.
      old_category:
        type: VARCHAR
        description: 'Empty in this database: NULL in every row, so a filter on it returns
          nothing and an aggregate over it returns NULL. Do not use it to answer a question;
          say the data is not held instead.'

  sd_user_flat:
    description: One row for each user of Service Desk.
    primary_key: user_id
    columns:
      user_id:
        type: INTEGER
        description: Unique id of the user.
      user_name:
        type: VARCHAR
        description: Full name of the user.
      team:
        type: VARCHAR
        description: Team of the user. Same spelling as sd_ticket_flat.team.

relationships:
  - name: ticket_agent
    from: sd_ticket_flat.assigned_user_id
    to: sd_user_flat.user_id
    join_type: MANY_TO_ONE

terminology:
  ticket: A support request from a customer. Also called a case.
  late ticket: A ticket that passed its due time.
```

### Rules for this file

1. **Write every column that the chatbot can use.** The model uses only the columns it sees. If you do not write a column, the model cannot use it.
2. **Copy the names and the types from the database.** Do not type them from memory. A wrong name gives a SQL error. In the Python repo, `scripts/build_schema_description.py` reads the names and the types from the database for you. It keeps the descriptions that are already in the file. First change its `TABLES` and `PRIMARY_KEYS` lists to your views.
3. **Start each table description with what one row is.**
4. **In each column description, tell:**
   - what the value means;
   - the unit, if the name does not tell it (days, KB, rupees);
   - what NULL means;
   - what a special value means (example: `NA` means nobody);
   - which column to use, if two columns look the same.
5. **Tell the model about empty columns.** Use the same words as `old_category` in the example. These words are `EMPTY_NOTE` in `scripts/build_schema_description.py`. The script adds them to each empty column, and it finds them again on the next run. If you use different words, the script adds its note a second time.
6. **Tell the model how to write an id.** For a number id, write "INTEGER, so write the number without quotes".
7. **Do not add a `values:` list.** Keep the file to names, types and descriptions. Long lists make the prompt big, and they go out of date.
8. **Put join advice in a business rule.** The model sees only `from`, `to` and `join_type` of a relationship. It does not see the relationship `name` or a relationship `description`.
9. **Do not use an `ambiguities:` section.** The chatbot does not read it. Use `terminology` or a business rule.

### Good and bad descriptions

| Bad | Good | Why |
| --- | --- | --- |
| `Status.` | `Status of the ticket, lowercase: open or closed. Use this column for every status filter.` | The model must know the values and the case. |
| `Assigned user.` | `User id of the agent who has the ticket. NULL means nobody has it.` | The model must know what NULL means. |
| `Size.` | `Size of the file in KB.` | The model must know the unit. |
| (column not written) | `Empty in this database: NULL in every row, ...` (the full note from rule 5) | Without this, the model can use an empty column and return no rows. |

---

## 5. File 2: `business_rules.yaml`

This file tells the model what your business words mean in SQL.

### Shape

```yaml
rules:
  - name: <short_name_with_underscores>
    definition: <what the word means>
    sql_fragment: <the SQL for it>                       # optional
    scope: <when the rule applies, and when it does not>  # optional
```

### The kinds of rule

| Kind | It tells | Example |
| --- | --- | --- |
| Meaning | What a word means | "Open ticket" means `ticket_status = 'open'` |
| Default | What to do when the question does not say | "Show tickets" means the open tickets only |
| Identity | What "my" means | "My tickets" means the tickets of the signed-in user |
| Routing | Which table to use, and how to join | "Late" comes from `sla_status`, not from `ticket_status` |
| Listing | Which columns to show in a list | Each ticket list shows `ticket_ref` and `ticket_title` |
| Order | The sort order when the question gives none | Newest ticket first |

### Example

```yaml
rules:
  - name: open_ticket
    definition: An open ticket is one where ticket_status = 'open'.
    sql_fragment: sd_ticket_flat.ticket_status = 'open'

  - name: closed_ticket
    definition: A closed ticket is one where ticket_status = 'closed'.
    sql_fragment: sd_ticket_flat.ticket_status = 'closed'

  - name: late_ticket
    definition: A late ticket is one where sla_status = 'Late'.
    sql_fragment: sd_ticket_flat.sla_status = 'Late'
    scope: 'Late is not a status. "How many tickets are late" still means open tickets
      only: sla_status = ''Late'' AND ticket_status = ''open''.'

  - name: default_to_open
    definition: 'When a question asks for tickets and names no status, show the open
      tickets only.'
    scope: 'Do not add this filter when the question names a status ("closed tickets"),
      asks for every status ("whatever the status", "including closed"), asks for a
      count by status ("tickets by status"), or names one ticket by its id or reference
      ("ticket 1042").'

  - name: my_tickets
    definition: 'My tickets means open tickets where assigned_user_id is the id in the
      SIGNED-IN USER block. Write the id as a number in the query. If there is no such
      block, do not guess a user: ask who is asking.'
    sql_fragment: sd_ticket_flat.assigned_user_id = <the id in the SIGNED-IN USER block>
      AND sd_ticket_flat.ticket_status = 'open'
    scope: 'When the question names its own status ("my closed tickets"), use that status
      in place of open.'

  - name: unassigned_ticket
    definition: 'A ticket that nobody has is one where assigned_user_id IS NULL.
      "Unassigned", "not assigned" and "nobody" all mean this.'

  - name: tickets_list_columns
    definition: 'When a query lists tickets, always show ticket_ref and ticket_title.'
    scope: A count or a total does not need them.

  - name: latest_first
    definition: 'When a question lists tickets and asks for no order, sort by created_at
      DESC.'
    scope: An order in the question ("oldest first", "by priority") replaces this one.
```

### Rules for this file

1. **One rule, one idea.**
2. **Give each rule a unique name.** Use lowercase and underscores. `product.yaml` uses these names.
3. **Write the full column name in `sql_fragment`:** `sd_ticket_flat.ticket_status = 'open'`.
4. **For a filter button, keep `sql_fragment` simple.** The screen makes a filter button (a chip) only from one `table.column = 'value'`. Do not use AND, IN, a number value, or a semicolon in it. If you do not want a button, put the SQL in the `definition`.
5. **Always write a `scope` for a default.** Tell when the default applies and when it does not.
6. **Point "my" rules to the SIGNED-IN USER block.** The chatbot puts this block above each question. It holds the user id, the name and the departments. Tell the model what to do when the block is not there: ask, do not guess.
7. **Make the rules agree with the schema descriptions and with the examples.** If two texts do not agree, the model makes mistakes.
8. **Do not use rules for security.** A rule is text for the model. It does not stop a user from seeing data. The database role controls what a user can see.

---

## 6. File 3: `question_sql_pairs.yaml`

This file gives the model sample questions with the correct SQL.

### Shape

```yaml
version: 1

pairs:
  - nl: <the question, as a user writes it>
    source: <a note for people; the model does not see it>
    sql: |
      <the correct SQL>
```

### Example

```yaml
version: 1

pairs:
  - nl: Show me ticket 1042
    source: product-team
    sql: |
      SELECT ticket_id, ticket_ref, ticket_title, ticket_status, priority
      FROM sd_ticket_flat
      WHERE ticket_id = 1042

  - nl: Show tickets
    source: product-team
    sql: |
      SELECT ticket_ref, ticket_title, priority, team
      FROM sd_ticket_flat
      WHERE ticket_status = 'open'
      ORDER BY created_at DESC

  - nl: What are my tickets?  (with a SIGNED-IN USER block giving id 501)
    source: product-team
    sql: |
      SELECT ticket_ref, ticket_title, priority
      FROM sd_ticket_flat
      WHERE assigned_user_id = 501
        AND ticket_status = 'open'
      ORDER BY created_at DESC

  - nl: How many tickets are late?
    source: product-team
    sql: |
      SELECT COUNT(*) AS late_tickets
      FROM sd_ticket_flat
      WHERE sla_status = 'Late' AND ticket_status = 'open'

  - nl: Open tickets for each agent
    source: product-team
    sql: |
      SELECT u.user_name, COUNT(*) AS open_tickets
      FROM sd_ticket_flat t
      JOIN sd_user_flat u ON u.user_id = t.assigned_user_id
      WHERE t.ticket_status = 'open'
      GROUP BY u.user_name
      ORDER BY open_tickets DESC
```

### Rules for this file

1. **Write 5 to 15 pairs.** Each pair goes into the prompt of every question. Too many pairs make each answer slow and costly.
2. **Each pair teaches one thing.** Examples: a default, a join, a count trap, a date, a "my" question.
3. **Run each SQL on the real database.** Make sure that the result is correct.
4. **Obey your rules.** If a rule says "open only by default", the SQL must have that filter.
5. **For a "my" question, write the user id in the question.** Example: `(with a SIGNED-IN USER block giving id 501)`.
6. **Do not copy every real question here.** Use the other real questions to test the chatbot (section 11).

---

## 7. File 4: `column_hierarchy.yaml`

This file controls the result table on the screen. The model does not see it.

One effect goes past the screen: the chatbot never suggests a `hidden` column for "group by" or "sort by". When a user clicks a suggestion, it becomes the next question. So if you hide a column, users also lose those suggestions for it.

### Shape

```yaml
version: 1
tables:
  <view name>:
    priority: [<columns to show first, in this order>]
    hidden: [<columns that start hidden>]
    row_groups: [<column to group rows by>]     # optional
    value_columns:                              # optional
      - column: <column>
        aggFunc: <sum | avg | min | max | count | first | last>
```

### Example

```yaml
version: 1
tables:
  sd_ticket_flat:
    priority: [ticket_ref, ticket_title, ticket_status, priority, team, sla_status, created_at]
    hidden: [ticket_id, assigned_user_id, old_category]
    row_groups: [team]
    value_columns:
      - column: ticket_id
        aggFunc: count
  sd_user_flat:
    priority: [user_name, team]
    hidden: [user_id]
```

### Rules for this file

1. **Put the most useful columns first in `priority`.** Columns that are not in the list come after it.
2. **`hidden` is not security.** A hidden column is still in the result and in the CSV download. The user can show it.
3. **`row_groups` and `value_columns` are optional.** A table without them is never grouped.
4. **Use only these `aggFunc` names:** `sum`, `avg`, `min`, `max`, `count`, `first`, `last`. Upper or lower case is fine. With a wrong name, the chatbot removes that value column and shows no error.
5. **Do not sum a snapshot.** Example: a weekly "open count" must not be added across weeks.
6. **Use only columns that exist in `schema_description.yaml`.**

---

## 8. File 5: `product.yaml`

This file tells the code about your product: the things people ask about, what a click opens, who the user is, and the product words.

Keep this first line. It lets the editor check the file as you type:

```yaml
# yaml-language-server: $schema=./product.schema.json
```

### The sections

| Section | Needed? | It tells |
| --- | --- | --- |
| `version` | Yes | Always `2` |
| `entities` | Yes | The things people ask about, one block each |
| `id_column_endings` | No | Column name endings that mean "id", such as `_id` |
| `columns` | No | A unit for a column, or "never group by it" |
| `headings` | No | How column names become headings (`sla` → `SLA`) |
| `suggestions` | No | Column name parts that are good to sort by |
| `spelling` | No | Words that the spell fix must never change |
| `colours` | No | Colours that have a meaning in your data |
| `users` | No | The table of users |
| `messages` | No | Product words in error messages |
| `welcome` | No | The text and the sample questions in an empty chat |
| `prompt` | Yes | Product words inside the fixed AI prompt |

### The keys of one entity

| Key | Needed? | It tells |
| --- | --- | --- |
| `words` | Yes | Every word a person uses for it, singular and plural |
| `table` | No | The view with one row for each of it |
| `id` | No | The id column |
| `title` | No | The readable column that a person clicks |
| `reference` | No | The column with the business reference number |
| `same_id_as` | No | Other names of the same id column, such as an old name |
| `kind` | No | The column that holds its type. One entity at most. |
| `colour` | No | The column that holds its colour code. One entity at most. Needs `table` and `id`. |
| `default_rule` | No | The rule name to apply when the question does not say. It must be a simple `table.column = 'value'` rule. |
| `open` | No | What a click does. Use exactly one of `url`, `download` or `popup`. Needs `id`. See the `open` keys below. |

### The keys of `open`

| Key | It tells |
| --- | --- |
| `url` | A page that opens in a new tab. `{id}` becomes the value of the `id` column. |
| `encode` | How `{id}` goes into the url: `plain` (the default) or `base64`. |
| `download` | The column that holds the address of a stored file. A click downloads the file. |
| `popup` | The name of a popup that the app already has. Needs `param`. |
| `param` | The name under which the popup gets the id. Needed with `popup`. |
| `button` | Show a button with this text in its own column, in place of a clickable cell. Works with `url` or `popup`, not with `download`. |

### Example

```yaml
# yaml-language-server: $schema=./product.schema.json
version: 2

entities:
  ticket:
    table: sd_ticket_flat
    words: [ticket, tickets, case, cases]
    id: ticket_id
    reference: ticket_ref
    title: ticket_title
    default_rule: open_ticket
    open: {url: '/ticket/{id}'}
  user:
    table: sd_user_flat
    words: [user, users, agent, agents]
    id: user_id

id_column_endings: [_id]

columns:
  ticket_title: {group: false}

headings:
  words:
    sla: SLA
    ref: Reference

suggestions:
  sort_by: [created, closed, priority]

spelling:
  never_correct: [email, phone]

users:
  table: sd_user_flat
  id: user_id
  name: user_name

messages:
  narrow_hint: a single team, or a shorter date range
  subjects: tickets, agents or teams

welcome:
  text: Ask about your tickets, your team or your agents.
  starters:
    - {question: Show me my late tickets, hint: Past their due time, icon: delayed}
    - {question: Show me my open tickets, hint: Still to do, icon: pending}

prompt:
  database: Service Desk
  rule_terms: '"open", "late" and "my tickets"'
  two_level_example: '"each team with its agent count, and for each agent the ticket count"'
  chart_scope: person, team, priority, status, date range
  explanation_example: 'Write "the open tickets of the Network team this week, with the
    priority of each", not "ticket_status = ''open'' AND team = ''Network''".'
  clarify_example: 'Write "which team did you mean?", not "team is ambiguous"; write "I
    could not find a ticket with that number", not "ticket_ref does not match".'
  other_subject: agents
```

### The `prompt` section

Each value goes into a fixed sentence of the AI prompt. Read the full sentence with your value in it. Make sure that it reads well.

| Key | The sentence it goes into |
| --- | --- |
| `database` | "You generate read-only SQL for a PostgreSQL **\<database\>** analytics database." |
| `rule_terms` | "...the business rules -- they define what terms like **\<rule_terms\>** mean in SQL." |
| `two_level_example` | "...when a question asks for counts at two levels at once -- **\<two_level_example\>**." |
| `colour_note` | Optional. One sentence about colours. Leave it out when colours mean nothing. |
| `chart_scope` | "...keep every filter, **\<chart_scope\>** and rule the main query applies..." |
| `explanation_example` | A good explanation, then the SQL-like one to avoid. |
| `clarify_example` | A good question back to the user, then the bad one to avoid. |
| `other_subject` | "...same thing but for **\<other_subject\>**." |

### Rules for this file

1. **`users.id` must be the Drupal user id.** The chatbot uses the Drupal user id as the product user id.
2. **Each name must exist.** Each table, column and rule name must exist in the other files. For most names, the chatbot checks this when it loads: if a name does not exist, it stops and shows a message with that name. The check does not cover `same_id_as`, popup names, or the column names in `column_hierarchy.yaml`. Check those by hand. A wrong one fails with no message.
3. **Use only these starter icons:** `delayed`, `issues`, `pending`.
4. **In `url`, `{id}` becomes the value of the `id` column.** Add `encode: base64` if your page needs the id in base64.
5. **Leave out a section that your product does not need.** Example: leave out `colours` when colours mean nothing.

---

## 9. Extra tables from a Drupal site module (optional)

A Drupal site module can add tables without a change to the main files. Use these hooks:

| Hook | It changes |
| --- | --- |
| `hook_vf_sql_chatbot_schema_alter()` | `schema_description.yaml` |
| `hook_vf_sql_chatbot_rules_alter()` | `business_rules.yaml` |
| `hook_vf_sql_chatbot_column_hierarchy_alter()` | `column_hierarchy.yaml` |
| `hook_vf_sql_chatbot_product_alter()` | `product.yaml` |

`vf_sql_chatbot.api.php` shows how to write each hook. For a real example, see the Arvind Retail site module: `web/sites/site-arvind-retail/modules/custom/vf_arvind_retail_chatbot`. It adds the `tms_initiative_attributes_flat` table with the hooks and its own `metadata/` folder. Its files use the same shapes as the main files.

There is no hook for `question_sql_pairs.yaml`.

**In the Python repo,** the site tables are in `metadata/site/`. Python reads only these three file names:

- `attributes_schema_description.yaml`
- `attributes_business_rules.yaml`
- `attributes_column_hierarchy.yaml`

It reads them only after `enable_site_metadata()`. The server calls it at start. Python has no site file for `product.yaml`.

---

## 10. When an answer is wrong

1. Read the SQL that the chatbot made.
2. Find the text that gave the model the wrong idea.
3. Change that text in the correct file. Use this table:

   | Problem | File to change |
   | --- | --- |
   | Wrong column | `schema_description.yaml`: make the column description clear |
   | Wrong meaning of a word | `business_rules.yaml`: add or fix a meaning rule |
   | A filter was added or not added | `business_rules.yaml`: fix the `scope` of the default |
   | Wrong join, or a count that is too big | `business_rules.yaml` and one example in `question_sql_pairs.yaml` |
   | Wrong column order on the screen | `column_hierarchy.yaml` |
   | Wrong link, or a wrong heading | `product.yaml` |

4. **Do not put data values in the prompt to fix one answer.** Do not add lists of names or values. Find the text that is not clear and make it clear.
5. Ask the question again in a new chat.
6. Ask your other test questions again. A fix for one question can break a different question.

---

## 11. Checklist

Do these steps before you give the files to the live system.

- [ ] Each YAML file opens without an error. Test it:
  ```
  python -c "import yaml,glob; [yaml.safe_load(open(f, encoding='utf-8')) for f in glob.glob('metadata/**/*.yaml', recursive=True)]; print('ok')"
  ```
  This works in PowerShell and in bash. It also tests the files in `metadata/site/`.
- [ ] Each table and column name is the same as in the database.
- [ ] Each table description tells what one row is.
- [ ] Each status, each special value, each unit and each NULL meaning is in a description.
- [ ] Each default rule has a `scope`.
- [ ] Each example SQL runs on the real database and gives the correct result.
- [ ] The rules, the descriptions and the examples agree.
- [ ] In Drupal, `php scripts/check_product.php` (in the module folder) shows `product.yaml is sound.`
- [ ] The files are the same in the Python repo and in the Drupal module.
- [ ] You asked your 10 to 20 real questions in a new chat. You read each answer and each SQL.

A change shows only after a reload:

- **Python:** restart the server. The server keeps the files in memory, so a new chat alone is not enough.
- **Drupal:** clear the caches at `/admin/config/development/performance`.

Then start a new chat.

---

## 12. Common mistakes

| Mistake | What happens | Correct action |
| --- | --- | --- |
| A column is not in the schema file | The model cannot use it, or it says that it cannot answer | Write every column that the chatbot can use |
| A column name is typed from memory | The SQL fails | Copy the names from the database |
| A default rule has no `scope` | "Closed tickets" also gets the "open" filter, and the answer is empty | Tell when the default does not apply |
| A rule and an example do not agree | The model makes different SQL each time | Make them agree |
| A list of values is put in the prompt | The prompt gets big and goes out of date | Write the meaning, not the list |
| `hidden` is used to hide private data | The user can still see it and download it | Remove the column from the view, or limit the database role |
| `default_rule` points to a rule with AND or IN | The chatbot stops with a message | Use a rule with one `table.column = 'value'` |
| A "my" rule does not tell what to do with no user | The model guesses a user | Tell the model to ask |
| The two copies of a file are not the same | Python and Drupal give different answers | Copy the file, then compare the two copies |
