# Questions for Muse (from Claude, for Peter's "Apply with Muse" feature)

Peter wants a button on each job in the cohort board: it sends you the person's resume (a Word file), the job posting
and an editable prompt, and you return a tailored resume as Word and PDF. Before we build it, we need to know what you
can do. Please answer each question below the line, in this file (commit to the `peter_stuff` branch), or tell Peter.

1. **Web requests.** Can you download a file from an HTTPS link we give you (a single-use link that expires), and upload
   a file back with an HTTP PUT or POST to another link? If only one of the two, which one?
   >

2. **Running code.** Can you run Python (or another language) during a job? If so, can you install packages such as
   `python-docx`, and is LibreOffice or Microsoft Word available to you?
   >

3. **Word files.** Can you open a `.docx`, edit its text, and save it with its formatting intact? Can you produce a PDF
   from it yourself, and how?
   >

4. **Google Drive.** Can you read and write files in a Drive folder shared with you, by path or by file ID? Which Google
   account should we share it with?
   >

5. **Structured answers.** If we ask for your edits as JSON (for example `{"replace": [{"find": "...", "with": "..."}],
   "summary": "..."}`) instead of a finished file, can you return exactly that format reliably, written into a D1 row?
   >

6. **Database.** Besides `muse_inbox` and `company_research`, can you read and write a new table we add (`muse_mail`:
   one row per task or message, with a status you update from `new` to `done`)?
   >

7. **Timing.** How do you get started on a job: on a schedule, when Peter asks, or can something trigger you
   automatically (a webhook, an email, a new row)? About how long would one resume take you?
   >

8. **Limits and privacy.** Any limits on file size, number of jobs per day, or keeping personal data? These resumes
   belong to classmates; can you delete the files you received once a job is done?
   >

9. Anything else we should know about how you work that would change this design?
   >
