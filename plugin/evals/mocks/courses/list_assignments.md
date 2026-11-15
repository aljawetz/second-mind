---
expect:
  course_id: number
---

{
  "course_id": {{input.course_id}},
  "as_of": "2026-11-14T17:00:00Z",
  "days": 14,
  "assignments": [
    {"assignment_id": 301, "name": "Lab 3: Branch Coverage", "due_at": "2026-11-21T04:59:00Z", "points_possible": 50, "status": "not submitted", "score": null, "late": false, "missing": false, "url": "https://canvas.example.edu/courses/55710/assignments/301"},
    {"assignment_id": 302, "name": "Reading response 9", "due_at": "2026-11-18T04:59:00Z", "points_possible": 10, "status": "not submitted", "score": null, "late": false, "missing": false, "url": "https://canvas.example.edu/courses/55710/assignments/302"},
    {"assignment_id": 299, "name": "Lab 2: Test Doubles", "due_at": "2026-11-10T04:59:00Z", "points_possible": 50, "status": "past due, not submitted", "score": null, "late": false, "missing": true, "url": "https://canvas.example.edu/courses/55710/assignments/299"}
  ]
}
