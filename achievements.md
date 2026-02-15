# Achievement Authoring Guide

This guide explains how to create custom achievements in `achievements.points.json`. Each achievement is evaluated by a specific **evaluator** based on its `category` field. The `trigger` field is parsed by natural language pattern matching — the exact wording matters.

## Achievement Schema

Every achievement is a JSON object with these fields:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique identifier (use snake_case, descriptive) |
| `category` | Yes | Determines which evaluator processes this achievement (see below) |
| `title` | Yes | Short display title |
| `achievement` | No | Alternate display name (shown in notifications) |
| `trigger` | Yes | Natural-language rule the evaluator parses (see category-specific syntax) |
| `flavorText` | No | Fun description shown in notifications and dashboard |
| `points` | Yes | Point value (integer) |
| `rarity` | No | `Common`, `Uncommon`, `Rare`, `Epic`, or `Legendary` (default: `Common`) |
| `iconPath` | No | Path to icon PNG, e.g. `/icons/myicon.png` |
| `keywords_any` | No | List of keywords (used by `title_keyword` category only) |
| `tags` | No | Freeform tags (not used by evaluators, for organization only) |

### Example

```json
{
  "id": "finish_20_books_total_bookworm",
  "category": "milestone_books",
  "title": "Bookworm",
  "achievement": "The Awakened Reader",
  "flavorText": "Twenty books down. Your TBR pile is losing.",
  "trigger": "Finish 20 books total.",
  "points": 30,
  "rarity": "Uncommon",
  "iconPath": "/icons/bookworm.png"
}
```

---

## Categories & Trigger Syntax

### `milestone_books` — Total Books Finished

**Evaluator**: `evaluator_phase1.py`
**What it checks**: Total number of finished books across all time.
**Trigger parsing**: Extracts the first integer from the trigger string.

| Trigger wording | What happens |
|---|---|
| `Finish 5 books total.` | Awards when user has >= 5 finished books |
| `Finish 100 books total.` | Awards when user has >= 100 finished books |

**Rules**:
- The trigger must contain a number. The evaluator extracts the **first integer** it finds.
- The rest of the wording is ignored — `"Finish 5 books total"`, `"Complete 5 audiobooks"`, `"5 books"` all work the same.
- Backdated to when the Nth book was actually finished.

---

### `milestone_series` — Total Series Completed

**Evaluator**: `evaluator_phase1.py`
**What it checks**: Number of fully completed series (all books in the series finished).
**Trigger parsing**: Extracts the first integer from the trigger string.

| Trigger wording | What happens |
|---|---|
| `Finish 5 complete series.` | Awards when user has completed >= 5 series |
| `Finish 25 complete series.` | Awards when user has completed >= 25 series |

**Rules**:
- A series is "complete" when the user has finished **every** book that Audiobookshelf lists in that series.
- Series data comes from abs-stats `/api/series`, which reads from your ABS library.
- Backdated to when the Nth series was completed.

---

### `milestone_time` — Total Listening Hours

**Evaluator**: `evaluator_milestone_time.py`
**What it checks**: Cumulative listening time across all sessions.
**Trigger parsing**: Looks for a number followed by "hour" (e.g., `100 hours`, `1,000 hours`).

| Trigger wording | What happens |
|---|---|
| `Reach 100 hours of total listening time.` | Awards at 100 cumulative hours |
| `Reach 1,000 hours of total listening time.` | Awards at 1000 cumulative hours |

**Rules**:
- The trigger must contain `<number> hour`.
- Commas in numbers are stripped automatically (so `1,000` works).
- Backdated by walking through sessions chronologically to find the exact moment the threshold was crossed.

---

### `milestone_yearly` — Books in a Calendar Year

**Evaluator**: Inline in `main.py`
**What it checks**: Number of books finished within a single calendar year.
**Trigger parsing**: Looks for trigger containing both "books" and "year", then extracts the first integer.

| Trigger wording | What happens |
|---|---|
| `Finish 100 books in a single calendar year` | Awards when any year has >= 100 finished books |

**Rules**:
- The trigger must contain both the words **"books"** and **"year"**.
- Extracts the first integer as the target count.
- Checks all calendar years, awards for the first year that meets the threshold.
- Backdated to the last book finished in the qualifying year.

---

### `series_complete` — Specific Series Completion

**Evaluator**: `evaluator_phase1.py`
**What it checks**: Whether the user has completed all books in a **specific named** series.
**Trigger parsing**: Expects format `Complete all books in <Series Name>` or `Finish all books in <Series Name>`.

| Trigger wording | What happens |
|---|---|
| `Complete all books in The Wandering Inn` | Awards when all books in "The Wandering Inn" series are finished |
| `Complete all books in Cradle` | Awards when all books in "Cradle" are finished |

**Rules**:
- The series name is extracted from everything after `"all books in "`.
- Name matching is case-insensitive and tries exact match first, then substring.
- The series must exist in your Audiobookshelf library.
- Backdated to when the last book in the series was finished.
- If the trigger doesn't match the pattern, the achievement's `title` field is used as the series name instead.

---

### `series_shape` — Series Shape/Size Patterns

**Evaluator**: `evaluator_series_shape.py`
**What it checks**: Completing series of specific sizes or starting many series.
**Trigger parsing**: Keyword-based matching.

| Trigger wording | What happens |
|---|---|
| `Finish a series with exactly 2 books.` | Complete any series that has exactly 2 books |
| `Finish a complete trilogy.` | Complete any series that has exactly 3 books |
| `Finish a series with more than 10 books.` | Complete any series with 10+ books |
| `Finish a series with 10+ books.` | Same as above |
| `Read the first book of 5 different series` | Start (finish book 1 of) 5 different series |

**Keywords the evaluator looks for**:
- `"exactly 2"` — duology (2-book series)
- `"trilogy"` — exactly 3 books
- `"10+ books"` or `"more than 10"` — 10 or more books
- `"first book of"` — counts series where you've finished the first book; extracts the target number from the trigger

**Rules**:
- For size-based triggers, the user must have finished **all** books in a qualifying series.
- For "first book of", only the first book (by sequence number) needs to be finished.
- Backdated to completion of the qualifying series (or Nth first book).

---

### `duration` — Book Duration

**Evaluator**: `evaluator_duration.py`
**What it checks**: Whether the user has finished books above or below a duration threshold.
**Trigger parsing**: Looks for `over`/`under` or `>=`/`<=` followed by hours, and optionally a count of books.

| Trigger wording | What happens |
|---|---|
| `Finish a book that is over 50 hours long.` | Finish any book >= 50 hours |
| `Finish a book that is over 30 hours long.` | Finish any book >= 30 hours |
| `Finish a book that is under 3 hours long.` | Finish any book <= 3 hours |
| `Finish 5 books that are over 20 hours long.` | Finish 5 books each >= 20 hours |
| `Finish a book >= 40 hours` | Same as "over 40 hours" |

**Rules**:
- `over` / `longer than` → book duration must be **>=** the threshold.
- `under` / `shorter than` → book duration must be **<=** the threshold.
- `>=` and `<=` operators also work directly.
- If a count like `"5 books"` is found, that many qualifying books are required. Default is 1.
- Duration is the total audio length from Audiobookshelf, obtained via abs-stats session data.
- Backdated to when the Nth qualifying book was finished.

---

### `author` — Author-Based Achievements

**Evaluator**: `evaluator_author.py`
**What it checks**: Books/series by the same author, author diversity, self-narration.
**Trigger parsing**: Keyword-based with integer extraction.

| Trigger wording | What happens |
|---|---|
| `Finish 10 books by the same author.` | Any single author with >= 10 finished books |
| `Finish 20 books by the same author` | Any single author with >= 20 finished books |
| `Finish 50 books by the same author` | Any single author with >= 50 finished books |
| `Finish 3 complete series by the same author` | One author with >= 3 fully completed series |
| `Finish 5 complete series by the same author` | One author with >= 5 fully completed series |
| `Finish books by 25 different authors` | 25 distinct authors across all finished books |
| `Finish a book narrated by the author` | Any book where an author is also listed as narrator |

**Keywords the evaluator looks for**:
- `"books by the same author"` — counts books per author, picks the best
- `"complete series by the same author"` — counts completed series per author
- `"different authors"` or `"distinct authors"` — counts unique authors
- `"narrated by the author"` — checks if author and narrator overlap

**Rules**:
- Author names are matched case-insensitively with normalized whitespace.
- Author/narrator data comes from abs-stats `/api/item/:id` endpoint.
- For "same author" triggers, the evaluator finds the author with the highest qualifying count.
- Backdated to when the threshold-crossing book/series was finished.

---

### `narrator` — Narrator Loyalty

**Evaluator**: `evaluator_narrator.py`
**What it checks**: Number of books finished by the same narrator.
**Trigger parsing**: Extracts the first integer as the threshold.

| Trigger wording | What happens |
|---|---|
| `finish 10 books by the same narrator` | Any single narrator with >= 10 finished books |
| `finish 5 books by the same narrator` | Any single narrator with >= 5 finished books |

**Rules**:
- The trigger must contain a number. The evaluator uses the first integer found.
- Narrator names come from abs-stats `/api/item/:id`.
- The evaluator finds the narrator with the highest qualifying count.
- Backdated to when the Nth book by that narrator was finished.

---

### `title_keyword` — Keywords in Book Titles

**Evaluator**: `evaluator_title_keyword.py`
**What it checks**: Whether the user has finished a book whose title contains specific keywords.
**Trigger parsing**: Looks for the pattern `with <keywords> in the title`.

| Trigger wording | What happens |
|---|---|
| `Finish a book with 'Dragon' in the title.` | Any finished book with "Dragon" in title |
| `Finish a book with mage OR wizard OR sorcerer in the title` | Any book matching any of those words |
| `Finish a book with 'Space,' 'Galaxy,' or 'Star' in the title.` | Any book matching any keyword |

**Alternate method — `keywords_any` field**:

Instead of (or in addition to) putting keywords in the trigger, you can use the `keywords_any` array:

```json
{
  "trigger": "Finish a book with a magic-themed title",
  "keywords_any": ["mage", "wizard", "sorcerer", "witch"]
}
```

**Rules**:
- Keywords are matched using **word boundaries** — `"mage"` will match "The Mage's Tower" but not "ImageCraft".
- Matching is case-insensitive.
- The evaluator checks both `title` and `subtitle` from Audiobookshelf metadata.
- If `keywords_any` is populated, those are used. Otherwise, keywords are parsed from the trigger text between `"with "` and `" in the title"`, split by commas and `"or"`.
- Backdated to when the qualifying book was finished.
- Only one match is needed — first matching book triggers the award.

---

### `social` — Multi-User Social Achievements

**Evaluator**: `evaluator_social.py`
**What it checks**: Overlapping books between users.

| Trigger wording | What happens |
|---|---|
| `Two users finish the same book within the same week` | Checks if any two users finished the same book within 7 days of each other |
| *(any other social trigger)* | Checks if the user shares at least 1 finished book with every other tracked user |

**Keywords the evaluator looks for**:
- `"same book"` + `"same week"` — the "Shared Experience" pattern
- Everything else falls through to the overlap-with-all-users check

**Rules**:
- Social achievements require **multiple users** to be tracked. If only one user exists, social achievements cannot trigger.
- The "same week" check uses a 7-day window between finish dates.
- The overlap check requires at least 1 book in common with **every** other user.
- Backdated to the relevant book completion timestamp.

---

### `behavior_time` — Time-of-Day Listening

**Evaluator**: `evaluator_behavior_time.py`
**What it checks**: Whether the user has listening sessions at specific times of day.
**Trigger parsing**: Looks for specific time patterns in the trigger text.

| Trigger wording | What happens |
|---|---|
| `...session that reaches 2:00 AM...` | Session ending between 2-5 AM ET on a weekday |
| `...before 6:00 AM...` | Session starting before 6 AM ET |

**Rules**:
- Currently only recognizes two specific patterns: `"2:00 AM"` and `"before 6:00 AM"`.
- Times are evaluated in **America/New_York timezone** (hardcoded).
- The "2:00 AM" check only triggers on weekdays (Mon-Fri).
- Adding new time-of-day checks requires modifying the evaluator code — the trigger is not fully dynamic for this category.

---

### `behavior_session` — Session-Based Behavior

**Evaluator**: `evaluator_behavior_session.py`
**What it checks**: Single session duration, weekend binges, finishing books quickly.
**Trigger parsing**: Keyword-based with hour extraction.

| Trigger wording | What happens |
|---|---|
| `Any single listening session lasts at least 5 hours` | A session of >= 5 hours |
| `Any single listening session lasts at least 10 hours` | A session of >= 10 hours |
| `Listen for at least 10 hours over a single weekend` | >= 10 hours total across one Sat+Sun |
| `Finish a book in a single day` | Start and finish a book on the same calendar day |
| `...20+ hours...7 days...` | Finish a book >= 20 hours long within 7 calendar days |

**Keywords the evaluator looks for**:
- `"single listening session"` — checks max single session duration
- `"over a single weekend"` — sums Saturday + Sunday listening
- `"finish a book in a single day"` — exact phrase match
- `"20+ hours"` + `"7 days"` — speed reader pattern

**Rules**:
- Session durations are capped at the lesser of: reported listening time, book duration, and wall-clock time. Hard cap at 24 hours.
- Weekend = Saturday + Sunday (grouped by the Saturday date).
- "Single day" means the first and last session for that book are on the same calendar date.
- Backdated to the session/completion timestamp.

---

### `behavior_streak` — Listening Streaks & Consistency

**Evaluator**: `evaluator_behavior_streak.py`
**What it checks**: Consecutive listening days, monthly frequency, monthly listening time.
**Trigger parsing**: Keyword-based with integer extraction.

| Trigger wording | What happens |
|---|---|
| `Listen on 7 consecutive days` | 7-day listening streak |
| `Listen on 30 consecutive days` | 30-day streak |
| `Listen on 20 distinct days in a single month` | 20 unique days with listening in one month |
| `Listen 100 hours in a single month` | 100+ hours of listening in one calendar month |

**Keywords the evaluator looks for**:
- `"consecutive"` or `"streak"` — consecutive day streaks
- `"distinct days"` + `"month"` — unique listening days per month
- `"hours"` + `"month"` — total hours per month

**Rules**:
- Days are calculated in **America/New_York timezone**.
- A "listening day" is any calendar day with at least one listening session.
- Streaks require no gaps — 1 missed day resets the streak.
- Backdated to the end of the streak or qualifying month.

---

### `meta` — Meta Achievements

**Evaluator**: Inline in `main.py`
**What it checks**: Total number of achievements earned.
**Trigger parsing**: Looks for "earn" and "achievement" in the trigger, extracts the first integer.

| Trigger wording | What happens |
|---|---|
| `Earn 50 other achievements` | Awards when user has >= 50 total achievements |

**Rules**:
- The trigger must contain both **"earn"** and **"achievement"**.
- Counts all achievements in the database for that user.
- Not backdated (uses current timestamp since it depends on other awards).

---

## What Data Is Available

The engine has access to this data from abs-stats and Audiobookshelf:

| Data | Source | Used by |
|---|---|---|
| Finished book IDs per user | `/api/completed` | All evaluators |
| Finish date per book per user | `/api/completed` (finishedDates) | Backdating in all evaluators |
| Listening sessions (start, end, duration, device) | `/api/listening-sessions` | behavior_*, duration, milestone_time |
| Total listening time per user | `/api/listening-time` | milestone_time (fallback) |
| Series index (series name, book IDs, sequence) | `/api/series` | milestone_series, series_complete, series_shape, author |
| Individual book metadata (title, authors, narrators, duration) | `/api/item/:id` | duration, title_keyword, author, narrator |
| User list and usernames | `/api/usernames` | social, dashboard |

## What You CAN'T Do (Without Code Changes)

These require modifying evaluator code:

- **New time-of-day patterns** — `behavior_time` only recognizes `"2:00 AM"` and `"before 6:00 AM"`
- **Genre-based achievements** — Audiobookshelf metadata doesn't reliably expose genre through abs-stats
- **Listening speed/playback rate** — not tracked in session data
- **DNF (did-not-finish) achievements** — the engine only knows about finished books
- **"First to finish" achievements** — no cross-user race tracking
- **Date-specific achievements** (e.g., "finish a book on Christmas") — no evaluator checks calendar dates
- **Custom math or compound conditions** — each evaluator handles one pattern family; you can't combine triggers like "finish 10 books by the same author AND narrator"

## Tips

1. **Test your trigger wording** by looking at the keyword patterns listed for each category. If your trigger doesn't contain the right keywords, the evaluator will silently skip it.

2. **Use existing achievements as templates.** Copy a working achievement in the same category, change the `id`, `title`, `trigger`, and numbers.

3. **IDs must be unique.** If two achievements share the same ID, only one will be tracked.

4. **The JSON is re-read every evaluation cycle** (default: every 5 minutes). No restart needed after editing.

5. **Rarity doesn't affect evaluation** — it's purely cosmetic (display color in notifications and dashboard).

6. **Points are arbitrary** — set them to whatever feels right for your group. Higher points = more impressive on the leaderboard.

7. **Icons** go in the `icons/` directory. Reference them as `/icons/filename.png` in `iconPath`.

8. **One achievement per trigger.** Don't try to make one achievement cover multiple categories. Create separate achievements instead.

9. **Backdating works automatically.** The engine figures out when the achievement was *actually* earned based on historical data. You don't need to configure this.

10. **Empty `keywords_any` fields are fine.** If your category doesn't use keywords, leave them empty or omit them entirely.
