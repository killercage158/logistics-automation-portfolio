# Logistics Automation Portfolio

I am Nguyen Minh Hieu. I studied finance. From May to November 2026 I worked at APS Group, a Vietnamese freight forwarder, as an Operations Executive. In that role I removed repetitive work from the sales, booking, trucking, customs and marketing teams.

**How I built these:** I designed four of these systems and built them with an AI coding assistant (Claude Code). The fifth, the sailing-schedule pipeline, already existed; I took it over and extended it. I gathered the requirements, defined the workflows, business rules and checks, tested with staff, and ran the systems in production. I owned the problem, the rules, the design choices, the tests with real users, and the decision of when each system was safe to switch on.

This repository describes that work. It has no company code, no real data and no internal details. The only code here is three original demos, built the same AI-assisted way, that anyone can run. They re-create the logic and rules of the production systems with fictional data. [How they differ from the real systems](#the-real-systems-and-the-demos).

## The five case studies

| # | Case study | One-line outcome |
|---|---|---|
| 1 | [Freight quote engine](case-studies/01-freight-quote-engine.md) | Checks prices on 6 carrier portals and in staff price sheets. Quote prep went from hours to minutes (a full check of all 6 carriers takes 9 to 14 minutes, unattended). |
| 2 | [Lead-to-quote workflow](case-studies/02-lead-to-quote-workflow.md) | A new customer lead is handed to the departments that price it, with a 30-minute deadline and reminders, and comes back as one combined quote. |
| 3 | [AI answers you can check](case-studies/03-ai-answers-you-can-check.md) | The pattern behind everything: the AI must cite where it read each number, and plain code re-checks the citation before staff see it. |
| 4 | [Sailing schedule pipeline](case-studies/04-sailing-schedule-pipeline.md) | Schedules from 8 carriers land in one table every day, with checks that catch silent data loss. |
| 5 | [Marketing content pipeline](case-studies/05-marketing-content-pipeline.md) | Ideas are collected, filtered, drafted by AI and published after two human approvals. |

The systems served 5 departments in total: sales, booking, trucking, customs and marketing.

## Demos

Three runnable re-creations with fictional data ([what is simulated](#the-real-systems-and-the-demos)). Each one runs offline with recorded AI answers (or live with Claude or Gemini), has automated tests, and traces every business rule it applies by ID.

| Demo | What it shows | Tests |
|---|---|---|
| [`quote-engine-demo`](quote-engine-demo/) | A full customer lead: dispatch to Booking, Trucking and Customs with deadlines and reminders; carrier portals checked one after another inside a shared time budget; price files read by AI with every cited cell verified; local charges, free time, fuel-indexed trucking, HS code and duty lookup; Sales Support picks the options and sets the margin; one combined customer quotation. 42 department rules. | 270 |
| [`schedule-pipeline-demo`](schedule-pipeline-demo/) | Schedules from five carriers in different formats, de-duplicated by voyage key, ghost sailings retired without touching booked rows, and a health check that catches a run reporting success while losing data. 19 rules. | 68 |
| [`marketing-pipeline-demo`](marketing-pipeline-demo/) | Ideas collected and de-duplicated by content, an AI relevance filter, two human approval gates, AI drafts that refuse thin sources, golden-hour scheduling and per-platform publishing rules. 18 rules. | 54 |

![Rate comparison report from the quote engine demo](quote-engine-demo/docs/screenshot.png)

## The real systems and the demos

The demos are built so that anyone can run them on a laptop in a minute, with no accounts, no API key and no connection to any outside service. To make that possible, every outside system is replaced by a local stand-in. The business logic and the department rules follow the production systems; the connections around them are simulated.

The production systems ran every working day inside the company. They were connected to live carrier websites, the teams' file server, their shared tables and their chat, and staff in five departments used them in their daily work.

| Part | In production | In the demo |
|---|---|---|
| Where staff work | Shared tables in Lark Base. Staff tick a box or press a button; results, cards and bot messages come back in Lark | Command line and HTML reports |
| Receiving jobs | A Node.js service on an office PC, reached through a Cloudflare tunnel, with job queues, worker processes and locks | A direct function call |
| Carrier prices | A real Chrome browser, driven by custom extensions, logs in to 6 carrier websites | Simulated carrier portals with fictional prices, delays and failures |
| Price sheets, haulier files, customs documents | Claude (Claude Code command line, read-only) reads the teams' real Excel, Word and image files on the company file server | Recorded AI answers over fictional files, or live Claude or Gemini with `--live` |
| Documents | Comparison and quote PDFs, and an editable Word quote for the customer; some PDFs and emails through n8n | HTML files |
| Sailing schedules | NestJS crawlers (Puppeteer and carrier APIs) for 8 carriers, twice a day, into Supabase (PostgreSQL) and Lark | 5 fictional carriers read from local files into SQLite |
| Marketing | Python crawlers (Playwright, yt-dlp, RSS) over Facebook pages, TikTok, YouTube and news sites; Gemini writes the drafts; posts go to 2 Facebook pages, single-image posts are mirrored to Instagram, and hidden Zalo OA articles are prepared for the team | Fictional sources and simulated platforms; nothing is posted |
| Daily runs | Windows scheduled tasks | You run the command |

In production:

- The booking team (4 staff) used the quote engine every day from late September 2026. A full check of all 6 carrier websites ran unattended in 9 to 14 minutes.
- Lead dispatch connected Sales Support with the Booking, Trucking and Customs teams, and was tested with 7 leads at once, run like a busy day.
- The schedule pipeline collected schedules from 8 carriers twice a day. One clean-up removed 17,514 stale duplicate database rows out of 26,803 (65%), and 5,624 duplicates from the team's table without touching any row linked to a booking.
- The marketing pipeline brought in about 20 to 50 new ideas a day, and nothing was posted without two human approvals.

What a demo cannot show are the problems of running against real systems: logins that expire, carrier websites that change without notice, rate limits, a PC that must stay on, and rounds of feedback from staff. The case studies describe those problems and how they were solved. The production code belongs to the company, so it is not published here.

## Confidentiality

Employer, carrier and software product names appear because they are public. Everything else is described in business and architecture terms only. No prices, customers, staff, account details, screenshots or internal identifiers are included.

## License

MIT. See [LICENSE](LICENSE).
