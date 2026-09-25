TidyLab ~ Pranay Singhal
 
TidyLab is a web application which assists any non-technical-but-motivated to get some value from the data. I chose the application of cleaning as my fundamental mantra for this app. Any user can upload up a messy or untidy file (Csv/Excel), review the issues in simple terms and explore how the cleaning changes the answer along with a summary of how much the incorrect issues were costing them. All in plain language – no technical jargon. 

Target market: built for one who works with a sheet but isn’t technical or data person. Analysts. Sales op lead. A small business owner. 
 
Why I built this, and not something else
The assignment mentions cleanup, transformation, visualization/storytelling as example operations. I selected cleaning, but my actual focus of design was proving how this cleaning mattered. 

The reasoning: messy data doesn’t unravel itself. Any business owner would open a sheet which looks like a table, and they entrust the average operation off it without any signal of “N/A” or the correct spellings of same “Sales” category and how they might be affecting the data. I tested this on a sample employee dataset before coding: the average salary shifted by $2004 based on how “N/A” is treated: missing or 0. A combined column name “Department_region” hid the headcount by region or by department entirely. These were just some basic anomalies which were affecting the data heavily.
I remember the demo of Golden Analytics’ product, Tableau, Power BI, etc. and took some pointers to specially avoid building a smaller, meeker version of AI analytics jumbled with chat interface. Golden emphasizes inspectable calculations and keeps AI away from actual numbers. I envisioned that differently and followed on how AI may propose the fix but never computes a number. Here, every number or diff in the service comes up from SQL over DuckDB, the LLM layer only views column metrics and a small sample. The full data and the output are validated before the user has access to it. Along with that, I have also touched up storytelling/visualization without completely soaking in it – that would again be a homage to the already present products in the market. 
So, the idea became clearer (pun intended): upload the data, clean it, but make the payoff visible. 

The hook: before/after answers to real questions the user may have, directing to the specific step that produced that change along with new questions which were a byproduct of the clean-up. (ex. Headcount by region or department only existed after splitting the parent column. I also provide the recipe of steps which can be utilized over a similar structured file for future use.
 
How it works
The flow is: ‘Upload → Profile summary→ Detect issues → Review → what changed (+ recipe) → Compare answers (story)→ Download.’
1.	Upload. 
(CSV/Excel/xlsx/xlsm): a user can upload up to 50mb file (25mb on live demo) with automatic encoding detection, sheet picker for multiple sheets in a workbook and header detection. 
a.	The raw file is loaded to a DuckDB  (read-only mode) with every value as text. Empty rows are only skipped and counted while duplicate/blank rows are renamed.
b.	User can only upload steps from earlier file (recipe)

2.	Profile Summary. 
one plain sentence to describe what the sheet rows holds, built from column roles (id, category, number, data, contact, text). It will never guess what file is about. 

3.	Detect.
11 detectors automatically run placeholder text used for missing values, numbers stored as text, inconsistent categories, combined columns, ambiguous or mixed date formats, duplicate and near-duplicate rows, non-unique identifiers, invalid contact formats, and out-of-range values. 
a.	Rules put them in 3 tiers: 
- Fixed automatically (Safe)
- please review (likely)
- we need your call (ambiguous – as a question. For ex. “Does blank mean zero or missing?”)

4.	Review.
a.	issue cards are grouped by tier first (Decision) and ranked by impact.
b.	Each card will have example rows before and after.
c.	Accept/reject/answer updates the visible recipe on the right panel with undo available.
d.	Nothing is destructive, rejected fixed aren’t applied and removed duplicates are set aside.

5.	What changed 
a.	the core screen. Before -> after cards for headline numbers each with a “why”    highlighting the recipe steps.
b.	Paired before/after bar charts with interactive cursor depicting the change
c.	“Now you can ask” cards show questions that were impossible before
d.	Live change if an answer in decisions is updated – without full reload/reupload

6.	Story.
Short summary of major changes and significant steps. Default computation is from a template, reworded by AI when a provided is configured.

7.	Download
•	the tidy file, CSV format, protected against formulas.
•	The recipe as JSON. You can attach this with a similar structured file next time and same steps applied.
 
Some major design decisions worth calling out
1. Code execution and AI proposals.
•	Counts, diffs, averages, impact scores – all come from SQL. The model sees column facts up to 5 examples per column and at most 20 sample rows. Fixes must name real columns and values. 
•	AI fixes are never applied automatically (capped at “likely”) and the impacted row-counts are done by the engine. This was one of the contracts that I never drift across the build throughout.
2. “Before” has a simple sturdy definition. 
•	I defined a specific set of rules (how blanks are counted, how to read dates, how categories should be divided, etc.) instead of leaving them vague. I realized a few changes midway after my first draft compared values differently. 
I came across how different tools handle data differently, thus giving the user power to handle their own rules while we handle the changes (also a trade-off).
•	The idea was to make the before/after fair. 
3. Confidence tiers.
•	I realized that not every problem should be handled with same interaction. Safe fixes like extra spaces and number reading should fall under “safe” category and thus must be already fixed before review. There’s a trade-off though: applying automatic fixes results in users not noticing them in first glance. Thus Undo/’already fixed’ pane are present.

•	genuine ambiguous cases like values missing or value ==0 does raise a question which could be subjective based on the user. 
4. Front-end design spec.  I changed the design theme from a dark theme to light-amber colored them midway as that was always the plan. A dark mode theme is a future design idea and could be added easily, it’s not an impactful feature.
5. Client/server vs browser-only design.
•	the cleaning process required SQL over large files while the AI layer needed structure to save API keys server side thus the client/server design made sense.
•	a browser only design would never upload the user’s file, but my design does.
•	the render free tier sleeps and caps memory thus no issue of a server memory relapse. 
 
How I used AI
I used Claude Code (desktop app) for the entire build. I wrote the initial build plan and then finessed it using Sonnet 5, while implementation model used were Opus 5 majorly. With introduction of Opus 5.5 recently, I utilized the model and could see the cost and token difference (a lot!)
Documents like plan.md(working milestone) and claude.md(build rules) were the north star documents. Prompts document was curated along the way.

Snapshot of the plan (10 phased milestone)
#	Milestone
M1	Scaffold, ingest, profiler
M2	Step engine and recipe
M3	Issue detectors and tiers
M4	Questions and before/after comparison
M5	Attribution and unlocked questions
M6	API and review UI
M7	"What changed" UI
M8	AI layer
M9	Story, second dataset, end-to-end test
M10	Hardening, packaging, deploy (feature freeze)
A few moments/decisions that mattered:
1.	the “before rules” decision: 
described in the previous section – I made the call along with AI agent comparison on different use cases and how different tools handle it which changed a few scenarios in the milestones further. 
2.	Phone number formatting:
I tested a few files manually which came up with bugs and Opus agent recommended digits only while I suggested a per-country formatting with a library instead.

3.	Coupled testing:
I Created a few extra testing scenarios and edge-cases for further testing the scaffolding as well as model accuracy. Few examples like approving two entry scenarios initially but the second one was redundant, and once the build was visible, I quickly realized and fixed my mistake with my AI Opus agent visibly agreeing.

4.	Verification, testing and diagnosis:
I frequently used skills like /code-review, /doctor and other skills to review, test and health check the files and fix issues. It helped me delete or update the files, saving space and time complexity at crucial points. This when scaled up on a level could be a major enhancement.

5.	Deployment:
My initial plan was to use Vercel for app deployment as I had prior experience with it.
The goal was to keep the app cost-free or as frugal as possible. I and the agent researched on different options and plans which fulfilled our requirements and finally ended up on Render deployment (Vercel’s serverless model can’t hold in-memory sessions or upload large file sizes). We also discussed other methods for deployment

Current issues faced with AI during test:
a. app locks the file while it waits for the model, so was slow (30+ seconds)
b. AI understood the wrong meanings for before/now and duplication of cards
c. Model constraints – I was using Gemini free models (takes more thinking before answering)
 
What I'd do with more time
1.	Generality: 
- Work on speeding up large files to report the steps that didn’t move the answers
- faster first-time scoring on small servers, or scoring in the background
-  handle pivot/crosstab tables

2.	Attribution: 
- Handle complex data and reports with pivots/charts 
- smarter out of range defaults and checks (edge case handling)

3.	Recipe features
- Remember sheet requirements/preferences in the same file such as header features, to minimize data reset 
- saved steps could be utilized for different files 

4.	AI features: 
- Current model has AI limitations because of token limit.
- check what the AI model means, not just its numbers. Reword, contextualize and summarize.
- testing suite with LLM provider models.
- Additional fixes for AI-suggestions such as ranking them by impact on failures

5.	Polish UI
- add a dark mode
- Add a mobile layout for the recipe panel
- group cards after a maximum limit reached
 
How to run it
There are three ways to run the app. All three run the same thing: one server that hosts the web page and the API on a single port.
1.	Live link (nothing to install) – simplest way
https://tidylab.onrender.com
It's hosted on a free plan that sleeps when idle, so the first load can take 30–60 seconds. It runs without an AI key: all suggestions and wording are rule-based.
2.	Docker
Prerequisites: Docker Desktop, or any Docker engine.
```git clone https://github.com/PranaySinghal/Golden.git
cd Golden
docker build -t tidylab .
docker run -p 8000:8000 tidylab
```
Then open http://localhost:8000
3. Without Docker
•	Prerequisites: uv, for Python 3.12, and Node.js 22
```bash
git clone https://github.com/PranaySinghal/Golden.git
cd Golden
./run.sh
```
•	Then open **http://localhost:8000**. To use another port, run `PORT=9000 ./run.sh`.
•	`run.sh` installs the dependencies, builds the web page and starts the server. If a tool is missing, it says so.
With or without an AI key
•	Without a key (default): nothing to set, since `LLM_PROVIDER=none` is the default. 
•	With a key: the model adds extra suggestions and rewords text. It never computes numbers, and it sees only a column summary plus at most 20 sample rows. Copy `.env.example` to `.env` in the repo root and set:
LLM_PROVIDER=anthropic          # or gemini
ANTHROPIC_API_KEY=your-key      # or GEMINI_API_KEY
- `run.sh` loads `.env` automatically.
- Docker: add the file to the run command:
  ```bash
  docker run --env-file .env -p 8000:8000 tidylab
  ```

Model calls are capped at 20 a minute. Past that cap, or if the key is missing or invalid, the app quietly falls back to its rule-based wording. 
Sample data
All samples are in **`data/samples/`**. You can upload them through the web page.
•	`Messy_Employee_dataset.csv` 
•	`Messy_Employee_dataset_messier.csv
•	store_orders.csv
The quickest demo upload `Messy_Employee_dataset.csv`, accept "holds two things in one column", answer the Salary question, then open What changed.

 

What's out of scope
Non-goals for this build:
1.	Chat bot interface 
2.	Individual user access and authorization for collaboration
3.	Warehouse or Database connectors 
4.	Custom charts/dashboard features
5.	More file formats outside of csv and excel
6.	Features based on business requirements. Added ideas in /ideas.md 

 
