/**
 * Every word on the landing page, in one place so the claims can be checked
 * together. Nothing here states a figure: the only numbers on the page are the
 * upload limit, which the API reports, and a literal zero.
 */

export const HERO = {
  eyebrow: 'Spreadsheet cleanup, in plain English',
  headlineLead: 'Tidy your data.',
  headlineAccent: 'See what it was hiding.',
  subhead:
    'Drop in a CSV or Excel file. Tidy Lab reads every column, says what looks wrong in ordinary ' +
    'words, and lets you take or leave each fix one at a time — then shows you which of your ' +
    'numbers the mess was changing. No sign-up, nothing to install.',
}

export const STATS: { figure: string; label: string }[] = [
  { figure: '0', label: 'Sign-ups, installs or API keys' },
  { figure: 'Seconds', label: 'From dropping a file to the first answer' },
  { figure: 'Undoable', label: 'Every step — your original is never touched' },
]

export const FEATURES = {
  eyebrow: 'What it does',
  title: 'It does the reading, you keep the say',
  lede: 'Four things happen between dropping a file in and getting a tidy one back.',
  cards: [
    {
      title: 'It reads your file the way a person would',
      body:
        'Every column gets a plain description — a date, a number, an ID, a category, a name — ' +
        'worked out from what is actually in it. Nothing to configure, and no column names it ' +
        'needs to recognise.',
    },
    {
      title: 'It says what is wrong, not what it detected',
      body:
        'Names with stray spaces around them, not "whitespace anomaly detected". The certain ' +
        'fixes are already applied by the time you arrive. The judgement calls are laid out for ' +
        'you to take or leave.',
    },
    {
      title: 'You see what a fix does before you take it',
      body:
        'Every suggestion will show you example rows, before and after. Your original table is ' +
        'never touched — the clean version is rebuilt from your file plus the list of steps, so ' +
        'any step can be switched off, pulled out or undone.',
    },
    {
      title: 'It shows which answers the mess was changing',
      body:
        'This is the part a spreadsheet cannot do for you. Tidy Lab asks the same questions of ' +
        'your file before and after cleaning, and shows you the answers that moved — and which ' +
        'step moved them.',
    },
  ],
}

export const FAQ = {
  eyebrow: 'Before you upload',
  title: 'The questions people ask first',
  items: [
    {
      question: 'Do I need an account?',
      answer:
        'No. There is no sign-up and no login, and there is nothing to install. Open the page, ' +
        'drop a file in, and you are working.',
    },
    {
      question: 'What happens to my file?',
      answer:
        'It goes to this app’s own server and gets a workspace of its own while you are working ' +
        'on it. It is not shared, and it is not used to train anything. Only a handful of recent ' +
        'files are kept at a time — the oldest is dropped as new ones arrive — and everything is ' +
        'deleted when the server stops. Nothing is kept long-term.',
    },
    {
      question: 'Does an AI read my data?',
      answer:
        'Not by default. Every check, and every number you see, is worked out by ordinary code on ' +
        'the server. If whoever is running Tidy Lab has switched a model on, it only ever sees a ' +
        'summary of your columns and at most twenty sample rows — and all it does is suggest ' +
        'extra fixes and word things more clearly. It never works out a figure and it never ' +
        'writes code.',
    },
    {
      question: 'What can I open, and how big?',
      answer:
        'Comma, tab and plain text files, plus Excel .xlsx and .xlsm workbooks. Whoever runs the ' +
        'app can set the size limit higher or lower. An Excel workbook opens one sheet at a ' +
        'time, and you can switch sheets once it is open.',
      // The real limit comes from the API rather than this file. See Faq.tsx.
      showsLimit: true,
    },
    {
      question: 'Can I undo something?',
      answer:
        'All of it. Your original table is never modified. Everything you accept becomes a step ' +
        'in a list you can see, and any step can be switched off, removed or undone — the clean ' +
        'version is rebuilt from your file plus that list every time.',
    },
  ],
}
