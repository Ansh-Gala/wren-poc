-- Deterministic synthetic seed data. Fixed ids, literal rows, no randomness:
-- re-running produces a byte-identical dataset.
--
-- DATES ARE RELATIVE TO CURRENT_DATE. Category L of the benchmark asks about
-- "overdue", "due today" and "completed this month"; absolute dates would make
-- those questions drift into vacuity as the calendar moves. The consequence is
-- that ground-truth *results* must be computed at benchmark time rather than
-- cached -- benchmark/runner.py executes expected and generated SQL in the same
-- moment so the comparison is always fair.
--
-- "This month" anchors on date_trunc('month', CURRENT_DATE) rather than
-- CURRENT_DATE - n, so the counts stay correct on the 1st of a month.
--
-- All names and addresses are obviously synthetic. The .invalid TLD is
-- reserved by RFC 2606 and can never resolve to a real mailbox.

TRUNCATE tasks, workflows, users RESTART IDENTITY CASCADE;

-- ---------------------------------------------------------------- users (15)
-- 12 ACTIVE / 3 INACTIVE. Departments: Engineering 4, Product 3, Design 3,
-- Operations 3, Finance 2. Roles: MANAGER, MEMBER, VIEWER.
INSERT INTO users (id, full_name, email, department, role, status) VALUES
 (1,  'Alice Anderson', 'alice.anderson@example.invalid', 'Engineering', 'MANAGER', 'ACTIVE'),
 (2,  'Bob Brown',      'bob.brown@example.invalid',      'Engineering', 'MEMBER',  'ACTIVE'),
 (3,  'Carol Chen',     'carol.chen@example.invalid',     'Engineering', 'MEMBER',  'ACTIVE'),
 (4,  'David Diaz',     'david.diaz@example.invalid',     'Engineering', 'MEMBER',  'INACTIVE'),
 (5,  'Erin Evans',     'erin.evans@example.invalid',     'Product',     'MANAGER', 'ACTIVE'),
 (6,  'Frank Foster',   'frank.foster@example.invalid',   'Product',     'MEMBER',  'ACTIVE'),
 (7,  'Grace Gupta',    'grace.gupta@example.invalid',    'Product',     'MEMBER',  'ACTIVE'),
 (8,  'Henry Hughes',   'henry.hughes@example.invalid',   'Design',      'MANAGER', 'ACTIVE'),
 (9,  'Irene Ibrahim',  'irene.ibrahim@example.invalid',  'Design',      'MEMBER',  'ACTIVE'),
 (10, 'Jack Jensen',    'jack.jensen@example.invalid',    'Design',      'MEMBER',  'INACTIVE'),
 (11, 'Karen Kim',      'karen.kim@example.invalid',      'Operations',  'MANAGER', 'ACTIVE'),
 (12, 'Liam Lopez',     'liam.lopez@example.invalid',     'Operations',  'MEMBER',  'ACTIVE'),
 (13, 'Mia Morris',     'mia.morris@example.invalid',     'Operations',  'VIEWER',  'ACTIVE'),
 (14, 'Noah Novak',     'noah.novak@example.invalid',     'Finance',     'MANAGER', 'ACTIVE'),
 (15, 'Olivia Osei',    'olivia.osei@example.invalid',    'Finance',     'VIEWER',  'INACTIVE');

-- ------------------------------------------------------------ workflows (8)
-- Alice (1) owns three, Erin (5) owns two -> "multiple workflows per owner".
-- Noah (14) owns one but is assigned no tasks -> owner-without-assignments.
-- Workflows 7 and 8 deliberately have zero tasks.
-- Workflows 5, 6 and 8 were created within the last 30 days -> "recent".
INSERT INTO workflows (id, name, description, category, status, owner_user_id, created_at, updated_at) VALUES
 (1, 'Employee Onboarding', 'End-to-end setup for a newly hired employee.',            'HR',          'ACTIVE',   1,  NOW() - INTERVAL '120 days', NOW() - INTERVAL '3 days'),
 (2, 'Invoice Processing',  'Receipt, approval and payment of supplier invoices.',     'FINANCE',     'ACTIVE',   14, NOW() - INTERVAL '95 days',  NOW() - INTERVAL '1 day'),
 (3, 'Hiring Pipeline',     'Sourcing through offer for an open requisition.',         'HR',          'ACTIVE',   1,  NOW() - INTERVAL '60 days',  NOW() - INTERVAL '2 days'),
 (4, 'QA Regression Suite', 'Maintenance of the automated regression test suite.',     'QUALITY',     'ACTIVE',   5,  NOW() - INTERVAL '40 days',  NOW() - INTERVAL '4 days'),
 (5, 'Release Management',  'Cutting, validating and shipping a production release.',  'ENGINEERING', 'ACTIVE',   5,  NOW() - INTERVAL '20 days',  NOW() - INTERVAL '1 day'),
 (6, 'Campaign Launch',     'Planning and launch of a new marketing campaign.',        'MARKETING',   'DRAFT',    8,  NOW() - INTERVAL '10 days',  NOW() - INTERVAL '6 days'),
 (7, 'Vendor Renewal',      'Annual review and renewal of supplier contracts.',        'FINANCE',     'ARCHIVED', 11, NOW() - INTERVAL '200 days', NOW() - INTERVAL '150 days'),
 (8, 'Security Audit',      'Scheduled internal review of access and controls.',       'ENGINEERING', 'DRAFT',    1,  NOW() - INTERVAL '5 days',   NOW() - INTERVAL '5 days');

-- ---------------------------------------------------------------- tasks (50)
-- Distribution per workflow: 12, 10, 9, 8, 7, 4 (workflows 7 and 8 have none).
--   Workflow task counts are tie-free: 12 > 10 > 9 > 8 > 7 > 4.
--   Assignee task counts are tie-free at the top: Bob 8 > Carol 7 > Frank 6.
-- Status totals: COMPLETED 18, TODO 16, IN_PROGRESS 9, BLOCKED 7.
-- completed_at IS NOT NULL exactly when status = 'COMPLETED'.
-- 10 tasks are overdue, 3 are due today, 1 task is unassigned.
INSERT INTO tasks (id, workflow_id, name, description, status, priority, assigned_user_id, due_date, completed_at, created_at) VALUES
 -- Workflow 1: Employee Onboarding (12)
 (1,  1, 'Collect signed offer letter',   'Obtain the countersigned offer from the candidate.',   'COMPLETED',   'HIGH',     2,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '1 day',  NOW() - INTERVAL '40 days'),
 (2,  1, 'Create email account',          'Provision the corporate mailbox and aliases.',         'COMPLETED',   'MEDIUM',   3,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '2 days', NOW() - INTERVAL '39 days'),
 (3,  1, 'Provision laptop',              'Image and ship the standard developer laptop.',        'COMPLETED',   'HIGH',     2,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '3 days', NOW() - INTERVAL '38 days'),
 (4,  1, 'Assign onboarding buddy',       'Pair the new joiner with an experienced colleague.',   'COMPLETED',   'LOW',      9,    NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '25 days', NOW() - INTERVAL '55 days'),
 (5,  1, 'Schedule orientation session',  'Book the first-day company orientation.',              'COMPLETED',   'MEDIUM',   1,    NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '22 days', NOW() - INTERVAL '54 days'),
 (6,  1, 'Grant repository access',       'Add the new joiner to the required source repos.',     'IN_PROGRESS', 'HIGH',     2,    CURRENT_DATE + INTERVAL '4 days',  NULL, NOW() - INTERVAL '12 days'),
 (7,  1, 'Set up payroll record',         'Create the payroll entry and tax details.',            'BLOCKED',     'CRITICAL', 3,    CURRENT_DATE - INTERVAL '6 days',  NULL, NOW() - INTERVAL '20 days'),
 (8,  1, 'Complete security training',    'Finish the mandatory security awareness course.',      'TODO',        'MEDIUM',   9,    CURRENT_DATE + INTERVAL '10 days', NULL, NOW() - INTERVAL '9 days'),
 (9,  1, 'Register for benefits',         'Enrol in health and pension schemes.',                 'TODO',        'LOW',      12,   CURRENT_DATE + INTERVAL '14 days', NULL, NOW() - INTERVAL '8 days'),
 (10, 1, 'Review employee handbook',      'Read and acknowledge the company handbook.',           'TODO',        'LOW',      4,    CURRENT_DATE,                      NULL, NOW() - INTERVAL '7 days'),
 (11, 1, 'First-week check-in',           'Manager review at the end of the first week.',         'IN_PROGRESS', 'MEDIUM',   2,    CURRENT_DATE - INTERVAL '2 days',  NULL, NOW() - INTERVAL '11 days'),
 (12, 1, 'Order desk equipment',          'Order monitor, dock and peripherals.',                 'TODO',        'MEDIUM',   NULL, CURRENT_DATE + INTERVAL '7 days',  NULL, NOW() - INTERVAL '6 days'),

 -- Workflow 2: Invoice Processing (10)
 (13, 2, 'Receive vendor invoice',        'Log the incoming invoice against the supplier.',       'COMPLETED',   'MEDIUM',   6,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '1 day',  NOW() - INTERVAL '30 days'),
 (14, 2, 'Validate purchase order',       'Confirm the invoice matches an approved PO.',          'COMPLETED',   'HIGH',     7,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '4 days', NOW() - INTERVAL '29 days'),
 (15, 2, 'Match invoice to receipt',      'Three-way match of PO, receipt and invoice.',          'COMPLETED',   'MEDIUM',   6,    NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '20 days', NOW() - INTERVAL '50 days'),
 (16, 2, 'Route for manager approval',    'Send the invoice to the budget holder.',               'IN_PROGRESS', 'HIGH',     12,   CURRENT_DATE - INTERVAL '1 day',   NULL, NOW() - INTERVAL '10 days'),
 (17, 2, 'Escalate disputed line items',  'Raise a dispute for mismatched charges.',              'BLOCKED',     'CRITICAL', 6,    CURRENT_DATE - INTERVAL '9 days',  NULL, NOW() - INTERVAL '25 days'),
 (18, 2, 'Schedule payment run',          'Add the invoice to the next payment batch.',           'TODO',        'HIGH',     7,    CURRENT_DATE + INTERVAL '3 days',  NULL, NOW() - INTERVAL '5 days'),
 (19, 2, 'Reconcile bank statement',      'Match cleared payments to the ledger.',                'TODO',        'MEDIUM',   12,   CURRENT_DATE + INTERVAL '21 days', NULL, NOW() - INTERVAL '4 days'),
 (20, 2, 'Archive invoice documents',     'File the invoice and approvals for audit.',            'TODO',        'LOW',      6,    CURRENT_DATE + INTERVAL '30 days', NULL, NOW() - INTERVAL '3 days'),
 (21, 2, 'Notify vendor of payment',      'Send the remittance advice to the supplier.',          'IN_PROGRESS', 'MEDIUM',   7,    CURRENT_DATE,                      NULL, NOW() - INTERVAL '6 days'),
 (22, 2, 'Update supplier ledger',        'Post the payment against the supplier account.',       'COMPLETED',   'LOW',      11,   NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '5 days', NOW() - INTERVAL '28 days'),

 -- Workflow 3: Hiring Pipeline (9)
 (23, 3, 'Publish job description',       'Post the approved role to the careers site.',          'COMPLETED',   'MEDIUM',   2,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '2 days', NOW() - INTERVAL '45 days'),
 (24, 3, 'Screen inbound applications',   'First-pass review of submitted applications.',         'COMPLETED',   'MEDIUM',   3,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '6 days', NOW() - INTERVAL '44 days'),
 (25, 3, 'Schedule phone screens',        'Arrange initial calls with shortlisted candidates.',   'IN_PROGRESS', 'HIGH',     2,    CURRENT_DATE - INTERVAL '3 days',  NULL, NOW() - INTERVAL '18 days'),
 (26, 3, 'Run technical interview',       'Conduct the structured technical assessment.',         'IN_PROGRESS', 'HIGH',     9,    CURRENT_DATE + INTERVAL '2 days',  NULL, NOW() - INTERVAL '15 days'),
 (27, 3, 'Collect interview feedback',    'Gather scorecards from every interviewer.',            'BLOCKED',     'MEDIUM',   3,    CURRENT_DATE - INTERVAL '4 days',  NULL, NOW() - INTERVAL '14 days'),
 (28, 3, 'Prepare compensation package',  'Model the offer against the salary band.',             'TODO',        'CRITICAL', 2,    CURRENT_DATE + INTERVAL '5 days',  NULL, NOW() - INTERVAL '7 days'),
 (29, 3, 'Send offer letter',             'Issue the formal written offer.',                      'TODO',        'HIGH',     9,    CURRENT_DATE + INTERVAL '9 days',  NULL, NOW() - INTERVAL '6 days'),
 (30, 3, 'Conduct reference checks',      'Contact the referees supplied by the candidate.',      'COMPLETED',   'LOW',      1,    NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '18 days', NOW() - INTERVAL '48 days'),
 (31, 3, 'Close requisition',             'Mark the requisition filled and notify finance.',      'TODO',        'LOW',      4,    CURRENT_DATE + INTERVAL '45 days', NULL, NOW() - INTERVAL '2 days'),

 -- Workflow 4: QA Regression Suite (8)
 (32, 4, 'Refresh test data fixtures',    'Regenerate the shared fixture dataset.',               'COMPLETED',   'MEDIUM',   3,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '3 days', NOW() - INTERVAL '35 days'),
 (33, 4, 'Run smoke test suite',          'Execute the pre-merge smoke pack.',                    'COMPLETED',   'HIGH',     6,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '7 days', NOW() - INTERVAL '34 days'),
 (34, 4, 'Triage failing assertions',     'Classify regressions from the nightly run.',           'BLOCKED',     'CRITICAL', 7,    CURRENT_DATE - INTERVAL '7 days',  NULL, NOW() - INTERVAL '22 days'),
 (35, 4, 'Update browser matrix',         'Refresh the supported browser versions.',              'TODO',        'LOW',      3,    CURRENT_DATE + INTERVAL '12 days', NULL, NOW() - INTERVAL '9 days'),
 (36, 4, 'Investigate flaky checkout test','Diagnose intermittent failure in checkout flow.',     'BLOCKED',     'HIGH',     10,   CURRENT_DATE - INTERVAL '11 days', NULL, NOW() - INTERVAL '26 days'),
 (37, 4, 'Extend API contract tests',     'Add contract coverage for new endpoints.',             'IN_PROGRESS', 'MEDIUM',   6,    CURRENT_DATE + INTERVAL '6 days',  NULL, NOW() - INTERVAL '13 days'),
 (38, 4, 'Publish coverage report',       'Generate and circulate the coverage summary.',         'TODO',        'LOW',      7,    CURRENT_DATE + INTERVAL '18 days', NULL, NOW() - INTERVAL '5 days'),
 (39, 4, 'Retire obsolete test cases',    'Delete tests for removed functionality.',              'COMPLETED',   'LOW',      12,   NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '15 days', NOW() - INTERVAL '42 days'),

 -- Workflow 5: Release Management (7)
 (40, 5, 'Cut release branch',            'Create the release branch from main.',                 'COMPLETED',   'HIGH',     2,    NULL,                            date_trunc('month', CURRENT_DATE) + INTERVAL '8 days', NOW() - INTERVAL '18 days'),
 (41, 5, 'Compile release notes',         'Summarise changes for the release announcement.',      'IN_PROGRESS', 'MEDIUM',   5,    CURRENT_DATE,                      NULL, NOW() - INTERVAL '8 days'),
 (42, 5, 'Verify migration scripts',      'Dry-run schema migrations against staging.',           'BLOCKED',     'CRITICAL', 4,    CURRENT_DATE - INTERVAL '5 days',  NULL, NOW() - INTERVAL '16 days'),
 (43, 5, 'Sign off staging validation',   'Record formal QA sign-off on staging.',                'TODO',        'HIGH',     5,    CURRENT_DATE + INTERVAL '1 day',   NULL, NOW() - INTERVAL '7 days'),
 (44, 5, 'Tag production build',          'Apply the release tag to the built artefact.',         'TODO',        'HIGH',     10,   CURRENT_DATE + INTERVAL '8 days',  NULL, NOW() - INTERVAL '6 days'),
 (45, 5, 'Announce release to stakeholders','Circulate the release note to the business.',        'TODO',        'LOW',      1,    CURRENT_DATE + INTERVAL '11 days', NULL, NOW() - INTERVAL '5 days'),
 (46, 5, 'Archive build artefacts',       'Move prior build outputs to cold storage.',            'COMPLETED',   'LOW',      12,   NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '12 days', NOW() - INTERVAL '40 days'),

 -- Workflow 6: Campaign Launch (4)
 (47, 6, 'Draft campaign brief',          'Write the positioning and objectives brief.',          'IN_PROGRESS', 'MEDIUM',   8,    CURRENT_DATE + INTERVAL '15 days', NULL, NOW() - INTERVAL '9 days'),
 (48, 6, 'Design landing page mockups',   'Produce desktop and mobile page mockups.',             'TODO',        'HIGH',     3,    CURRENT_DATE + INTERVAL '20 days', NULL, NOW() - INTERVAL '8 days'),
 (49, 6, 'Define audience segments',      'Specify the target segments and exclusions.',          'BLOCKED',     'MEDIUM',   8,    CURRENT_DATE - INTERVAL '8 days',  NULL, NOW() - INTERVAL '10 days'),
 (50, 6, 'Estimate media budget',         'Cost the paid media plan for the campaign.',           'COMPLETED',   'LOW',      9,    NULL,                            date_trunc('month', CURRENT_DATE) - INTERVAL '10 days', NOW() - INTERVAL '32 days');

-- Task created_at must be UNIQUE, or "the 5 newest tasks" has no single right
-- answer and the benchmark would mark a correct query wrong. The literal
-- offsets above collide in a few places, so they are normalised here to one
-- distinct day per task: 119 days ago (id 1) through 70 days ago (id 50).
-- All are in the past and earlier than any completed_at, so no task is ever
-- recorded as having finished before it existed.
UPDATE tasks SET created_at = NOW() - ((120 - id) || ' days')::interval;
