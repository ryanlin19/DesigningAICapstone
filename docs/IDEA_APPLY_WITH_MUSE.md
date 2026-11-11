# Idea: "Apply with Muse" (not built)

**Status:** an idea, saved 2026-11-11. Nothing here is built. Decisions still open are listed at the end.

A button on each job in the cohort board. It takes the person's uploaded resume (a Word file) and the job posting,
opens a prompt they can edit, and sends both to Muse. Muse tailors the resume to the job; the board shows the changes
side by side and the person downloads a Word file and a PDF, then applies on the company's site themselves. The board
never submits an application.

## Flow

```
Job card ──"Apply with Muse"──▶ Prompt editor (pre-filled, editable) + consent checkbox
                                   │ Send
                                   ▼
Board: stores the resume (R2), makes two single-use links, writes a muse_mail task row (D1)
                                   │
              Muse polls muse_mail (every 5–15 min), downloads, tailors (3–5 min)
                                   │
Muse returns numbered paragraph edits (JSON) ──▶ Board applies them, makes .docx + .pdf
                                   │
                    Review screen on the job card: changes side by side, toggle each,
                    fix text, rebuild, download. The person applies themselves.
```

Expected turnaround: about 10–20 minutes from click to "ready to review".

## Pieces

### 1. Keep the original resume (new)
Today the resume is read in the browser and only its text is sent to the server, which doesn't keep it. This feature
needs the original Word file so its formatting survives.
- On upload: "Keep my resume for Muse applications". If ticked, the `.docx` goes to R2 under that person
  (`resumes/<person>/…`).
- Word files only for this feature: a PDF's layout can't be edited reliably. PDF uploads still work for fit scoring.
- Deleted after a set time; a "Delete my resume" button.

### 2. Individual sign-ins (prerequisite)
Everyone shares one password today, so the board can't keep one person's resume from another. Each person needs their
own sign-in first: Cloudflare Access with email one-time codes (free for small groups, no password code in the board).
Resumes and requests are tied to that email.

### 3. The editable prompt
- Default template in the repo, `muse/APPLY_PROMPT.md`, with placeholders the board fills: `{job_title}`, `{company}`,
  `{job_description}` (from the job descriptions database), `{resume_paragraphs}`, `{what_you_are}` (functions,
  years), `{notes}`.
- The person edits it before sending; "Save as my default" keeps their version.
- A fixed block the person can't remove is always appended: keep everything true, no invented jobs, skills or numbers;
  return edits in the agreed JSON format.

### 4. Handing work to Muse
- **Table `muse_mail`** (new D1 migration, like 0011–0013): one row per task or message. Columns: id, from, to,
  kind (`apply`), subject, body (the filled prompt), links, status (`new` → `working` → `ready` / `failed`),
  created_at, updated_at, error. Each click is its own row, so several classmates can use it at once.
- **Files: single-use HTTPS links, no Google Drive.** Muse confirmed it can download over HTTPS and upload with PUT or
  multipart POST. The board's Worker issues one download link (the resume or its paragraph list) and one upload link
  (the results), each limited to one file and expiring after a few hours. Links go in the `muse_mail` row.
- **Trigger:** Muse polls `muse_mail` every 5–15 minutes (there's no inbound webhook to Muse). The board's existing
  15-minute schedule picks up finished rows, so nobody has to ask.
- **Instructions:** `muse/APPLY.md` in the repo, like `muse/WEEKLY.md`; Muse re-reads its instructions each run.

### 5. Edits as numbered paragraphs (not find-and-replace)
Muse's own caveat: replacing text inside existing formatted pieces (runs) of a `.docx` is safe; find-and-replace across
formatting boundaries, tables, headers and footers is risky; tracked changes and comments aren't well supported.
1. The board numbers every paragraph (body, tables, headers, footers) and sends the list:
   `[{"p": 12, "text": "Led pricing analysis for…"}, …]`.
2. Muse returns: `{"edits": [{"p": 12, "text": "…"}], "summary": "…"}` (Muse validates the JSON before writing it).
3. The board writes each new text into that paragraph's first run and clears the others, so the paragraph keeps its
   font, bold, bullets and spacing.

### 6. Building the Word file and PDF
- **Option A (recommended): the board builds them.** python-docx (small) and LibreOffice headless
  (`soffice --headless --convert-to pdf`, about +500 MB, one `deploy/ship.sh --image`) in the board's container.
  Toggling an edit or fixing a word rebuilds in about a second. Muse sees only the resume's text, never the file.
- **Option B: Muse builds them.** Muse already has Python 3.12, python-docx 1.1.0 and LibreOffice (no Microsoft Word:
  it's a Linux VM). No changes to the board's container, but every change on the review screen goes back to Muse
  (10–20 minutes each), and Muse handles the actual Word file.
- PDF fidelity with LibreOffice is very good but not pixel-identical to Word.

### 7. Review screen
The job card's button moves *Sent to Muse* → *Muse is working* → *Ready to review*. Opening it: original and tailored
side by side, each edit switchable, a text box for small fixes, Rebuild, then download PDF and Word.

## Privacy (decide before classmates use it)
Muse runs on a Meta "Secure VM". Per Muse: conversations may be logged and reviewed by Meta, and content can contribute
to AI development unless the account owner opts out (Settings > Data Controls). Muse can delete working files from its
VM after each task and won't save resume contents to long-term memory, but can't promise no trace in Meta's logs.
Muse mentioned a confidential VM as a stronger option. Proposed safeguards:
1. Peter turns on the Data Controls opt-out before launch.
2. The button explains, before anything is sent, that the resume and job go to Muse, an AI agent on Meta's service,
   that files are deleted after the job but Meta may keep logs; the person ticks a box to agree.
3. Option A, so Muse gets text, not the Word file.
4. `muse/APPLY.md` tells Muse to delete its working files when each task is done.

## Risks to check on the first live run
- Muse's runtime may ask Peter to approve each upload to an outside address. Get a standing approval for the board's
  address up front, or every resume waits on his click.
- Complex `.docx` layouts (text boxes, multi-column, tracked changes). Test with a few real resume styles.

## What Muse confirmed (2026-11-11)
| Question | Answer |
|---|---|
| Web requests | Download over HTTPS and upload with PUT or multipart POST both work; single-use expiring links are fine; keep each link scoped to one file |
| Code | Python 3.12, pip, python-docx 1.1.0, LibreOffice; no Microsoft Word |
| Word files | Edits inside existing runs keep formatting; headers, footers and tables need explicit handling; tracked changes and comments poorly supported |
| PDF | LibreOffice headless; very good, not pixel-identical to Word |
| Google Drive | Possible once connected (OAuth, one Google account); not needed for this design |
| Structured answers | Returns exactly the requested JSON, validated in Python, written to D1 with wrangler |
| New table | Can read and update `muse_mail` once a migration creates it |
| Timing | Starts when Peter asks, on a schedule it sets (5–15 min), or via a poller watching D1; 3–5 minutes per resume |
| Limits | No known daily cap (bounded by Peter's plan); resumes are tiny |

## Build order (when it's time)
1. Individual sign-ins (Cloudflare Access).
2. `muse_mail` migration and `muse/APPLY.md`.
3. Single-use links and resume storage in R2.
4. The button, editable prompt and consent checkbox.
5. Paragraph numbering, applying edits, PDF (option A).
6. Review screen.
7. First live test with Peter's own resume (also checks upload approvals).

## Open decisions
1. Option A or B for building the Word file and PDF.
2. The consent step and Meta opt-out (or a confidential VM).
3. Moving from the shared password to email sign-in.
4. Cover letters too? The same pipeline could write one per job with little extra work.
