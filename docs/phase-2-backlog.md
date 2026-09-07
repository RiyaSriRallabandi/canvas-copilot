# Phase 2 backlog — questions the agent should eventually answer

Real student questions (from daily Canvas use). Phase 1 handles logistics from
the structured REST API; most of the rest need a **RAG layer** over the
syllabus, Pages, modules, and announcement text.

## Answerable now (structured API — done or trivial)

- How many points is assignment X? — `points_possible` (done, M8.5)
- Did I submit X? / is it still open? — `submission`, `lock_at` (done, M8.5)
- What's due today / this week / in course X? — (done, M1–M6)
- Which of my courses are about AI? — course list (done)

## Structured API, not yet built (Phase 2, no RAG needed)

- What's my current grade in X? — `/users/self/enrollments` → `grades.current_score`
- What did I get on quiz/assignment X? — `submission.score`
- What is the late-submission policy? — `/courses/:id/late_policy` (%s only; prose still in syllabus)
- How long is the quiz/midterm? — `/courses/:id/quizzes` → `time_limit`
- What % of the grade is assignment X? — `/courses/:id/assignment_groups` weights
  (only if the course uses weighted groups)
- Any new announcements? (the list) — `/courses/:id/discussion_topics?only_announcements=true`

## Needs RAG (syllabus / Pages / modules / announcement text)

- What is the grading policy / grade cutoffs? (syllabus)
- What is the late policy in prose? (syllabus)
- How much do I need on the final to get an A? (current grade + weights **+** syllabus cutoffs)
- What time is my class? Where is it? (syllabus / calendar; wants a map link)
- Is class cancelled today? (announcements)
- When are office hours? (syllabus / Pages)
- What's the Zoom link for class? (syllabus)
- What are we covering this week / what should I read? (modules + Pages)
- Is Lockdown Browser required? → recommend setup + link (scan announcements/assignment text)
- How do I contact my TA? (People / syllabus)

## Ingestion coverage and gaps

Covered: the syllabus text field, a syllabus PDF attached to the course, Canvas
pages, the course home page, module names with their item titles, announcements,
and assignment descriptions. Courses vary a lot in structure, so ingestion skips
any disabled tab without failing.

Not covered: a syllabus that is an external link (a Google Doc, a course
website). Canvas only returns the link, not its contents. Also not covered:
Canvas calendar events used as a schedule (structured data — a candidate for a
structured tool rather than retrieval).

## Notes

- Adding structured tools has a cost. The 3B model juggles more tools less
  reliably — it currently sees five — so new tools are worth batching and
  re-checking against the eval rather than adding one at a time.
- Several items in the RAG list are really hybrid: structured data plus one fact
  from the syllabus (for example, "how much do I need on the final" needs the
  current grade and group weights from the API, and only the grade cutoffs from
  the syllabus). The retrieval layer should be able to hand a single retrieved
  fact back into a structured calculation.
