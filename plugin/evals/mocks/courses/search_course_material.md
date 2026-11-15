---
expect:
  course_id: number
  query: string
---

{
  "course_id": {{input.course_id}},
  "query": "{{input.query}}",
  "results": [
    {"n": 1, "source": "syllabus · p.3", "url": "https://canvas.example.edu/courses/55710/assignments/syllabus", "text": "Grading: labs 40%, midterm exam 20%, final exam 25%, participation 15%. The midterm exam is on Wednesday, October 7. The final exam is on Monday, December 14, 1:00-4:00 PM, in person and closed book."},
    {"n": 2, "source": "syllabus · p.5", "url": "https://canvas.example.edu/courses/55710/assignments/syllabus", "text": "Late work: labs lose 10% per day late, up to three days. After three days, or once solutions are posted, late labs get no credit."},
    {"n": 3, "source": "06 Test Doubles.pdf · slide 4", "url": "https://canvas.example.edu/courses/55710/files/40106", "text": "Stubs return canned answers to the calls made during a test. Mocks also record the calls they receive, so the test can verify the interaction."},
    {"n": 4, "source": "Lab 3: Branch Coverage", "url": "https://canvas.example.edu/courses/55710/assignments/301", "text": "Write JUnit tests for the BankAccount class that reach 100% branch coverage. Submit your test file and the coverage report. Due Friday, November 20 at 11:59 PM. Worth 50 points."}
  ]
}
