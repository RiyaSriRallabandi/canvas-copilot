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

## Answered by content search (`course_content`, hybrid keyword + vector)

Handled when the material is in Canvas; when it is only in an off-Canvas
syllabus, the answer is the link:

- What is the grading policy / grade cutoffs? (syllabus)
- What is the late policy in prose? (syllabus)
- What time is my class? Where is it? (syllabus / a page)
- When are office hours? (syllabus / pages / the class calendar page)
- Is Lockdown Browser required? → the announcement or assignment that names it
- What are we covering this week / what should I read? (modules + pages)
- Is class cancelled today? (announcements)
- What's the Zoom link for class? (syllabus / a page)
- How do I contact my TA? (syllabus / a page)

Still hybrid — structured data plus one retrieved fact:

- How much do I need on the final to get an A? (current grade + group weights
  from the API, grade cutoffs from the syllabus)

## Ingestion coverage and gaps

Covered: the syllabus text field, a syllabus PDF attached to the course, Canvas
pages, the course home page, module names with their item titles, announcements,
and assignment descriptions. Courses vary a lot in structure, so ingestion skips
any disabled tab without failing.

A syllabus that is only an external link (a Google Doc, a course website) is
detected at index time and stored as a URL; `course_content` hands that link
back instead of guessing. The linked document itself is never fetched — the
product navigates Canvas, it does not read outside it.

Not covered: Canvas calendar events used as a schedule (structured data — a
candidate for a structured tool rather than retrieval).

### The class-schedule gap

"When does my AI Strategy class meet" currently routes to content search, which
looks at the syllabus and pages only. When the meeting time is not written
there, the answer is "not found" — even though the recurring class sessions are
in Canvas as calendar events. `get_upcoming_events` reads those events but is
all-courses and next-week-only, and is never reached for a meeting-time
question. The fix is a course-scoped schedule tool (or letting meeting-time
questions fall through to the calendar) so "when does X meet" and "any exams in
X" draw on the same source.

## Notes

- Adding structured tools has a cost. The 3B model juggles more tools less
  reliably — it currently sees six — so new tools are worth batching and
  re-checking against the eval rather than adding one at a time.
- Several items in the RAG list are really hybrid: structured data plus one fact
  from the syllabus (for example, "how much do I need on the final" needs the
  current grade and group weights from the API, and only the grade cutoffs from
  the syllabus). The retrieval layer should be able to hand a single retrieved
  fact back into a structured calculation.
