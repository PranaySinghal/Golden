import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const here = dirname(fileURLToPath(import.meta.url))
const SAMPLE = join(here, '../../data/samples/Messy_Employee_dataset.csv')
const MESSIER = join(here, '../../data/samples/Messy_Employee_dataset_messier.csv')
const ORDERS = join(here, '../../data/samples/store_orders.csv')

function columnCount(csv: string): number {
  return csv.split('\n')[0].split(',').length
}

test('a messy file becomes a tidy one, and says what that did to the answers', async ({
  page,
}) => {
  await page.goto('/')

  // --- the landing page --------------------------------------------------------
  await expect(page.getByRole('heading', { level: 1 })).toContainText('what it was hiding')
  await expect(page.getByRole('link', { name: 'FAQ' })).toBeVisible()
  await expect(page.getByText('Drop a CSV or Excel file here')).toBeVisible()
  await page.getByLabel('Choose a file to upload').setInputFiles(SAMPLE)

  // --- the file ----------------------------------------------------------------
  await expect(page.getByRole('heading', { name: 'Messy_Employee_dataset.csv' })).toBeVisible()
  await expect(page.getByText('1,020 rows · 12 columns')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Features' })).toHaveCount(0)

  // how the file was read now lives behind the toggle. Closed again afterwards so
  // the column table doesn't compete with the review below it.
  await page.getByRole('button', { name: 'See the columns' }).click()
  await expect(page.getByRole('checkbox', { name: 'First row has column names' })).toBeChecked()
  await page.getByRole('button', { name: 'Hide columns' }).click()
  await expect(page.getByRole('checkbox', { name: 'First row has column names' })).toHaveCount(0)

  // --- review ------------------------------------------------------------------
  await expect(page.getByRole('heading', { name: /Already fixed/ })).toBeVisible()
  const panel = page.getByRole('complementary', { name: "What we're doing" })
  await expect(panel.getByText('Read "Join_Date" as dates')).toBeVisible()

  // accept a suggestion
  const suggestion = page
    .locator('article')
    .filter({ hasText: 'holds two things in one column' })
    .first()
  await suggestion.getByRole('button', { name: 'Accept' }).click()
  await expect(panel.getByText(/Split "Department_Region"/)).toBeVisible()

  // answer a question, which is what moves the numbers
  const salary = page.locator('article').filter({ hasText: '"N/A" instead of a number' }).first()
  await salary.getByRole('radio', { name: /Zero/ }).click()
  await salary.getByRole('button', { name: 'Use this answer' }).click()
  await expect(salary.getByText('Your answer:')).toBeVisible()

  // --- what changed ------------------------------------------------------------
  await page.getByRole('tab', { name: 'What changed' }).click()

  const story = page.locator('.story')
  await expect(story).toBeVisible()
  await expect(page.getByText(/Cleaning changed \d+ of your \d+ answers/)).toBeVisible()

  const averageSalary = page.locator('article').filter({ hasText: 'average "Salary"?' }).first()
  await expect(averageSalary.getByText('85,155.06')).toBeVisible()
  await expect(averageSalary.getByText('83,151.41')).toBeVisible()

  // a figure in the story goes to the answer it came from
  await story.getByRole('button').first().click()
  await expect(page.locator('.answer--lit')).toHaveCount(1)

  // the reason behind a change names the step responsible
  await averageSalary.getByRole('button', { name: 'Why?' }).click()
  await expect(averageSalary.getByText('Caused by:')).toBeVisible()

  // --- download ----------------------------------------------------------------
  const saving = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'Download cleaned file' }).click()
  const file = await saving

  expect(file.suggestedFilename()).toBe('Messy_Employee_dataset (tidied).csv')
  const cleaned = readFileSync(await file.path(), 'utf8')
  expect(columnCount(cleaned)).toBeGreaterThan(columnCount(readFileSync(SAMPLE, 'utf8')))
  expect(cleaned).toContain('Department')

  // --- and back to the start -----------------------------------------------------
  await page.getByRole('button', { name: 'Home' }).click()
  await expect(page.getByText('Drop a CSV or Excel file here')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('dataset')).toBeNull()
})

// The same flow on a file shaped nothing like the employee list. Every check is
// on the page's structure, never on this file's column names: if it only passed
// because of what the columns are called, it wouldn't prove "any table".
test('a differently shaped file goes through the same flow', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Choose a file to upload').setInputFiles(ORDERS)

  // --- what the file is, and what matters most in it ---------------------------------
  await expect(page.getByRole('heading', { name: 'store_orders.csv' })).toBeVisible()
  await expect(page.locator('.review__about')).toHaveText(/^Each row has .+\.$/)
  const problems = page.locator('.main-problems').getByRole('button')
  await expect(problems.first()).toBeVisible()
  await problems.first().click()
  await expect(page.locator('.card--lit')).toHaveCount(1)

  // --- accept the first suggestion ------------------------------------------------
  const panel = page.getByRole('complementary', { name: "What we're doing" })
  const stepsBefore = await panel.getByRole('listitem').count()
  await page.getByRole('button', { name: 'Accept', exact: true }).first().click()
  await expect(panel.getByRole('listitem')).toHaveCount(stepsBefore + 1)

  // --- what changed: either answers moved, or it says they didn't ---------------------
  await page.getByRole('tab', { name: 'What changed' }).click()
  await expect(
    page.locator('article.answer').first().or(page.getByText('came out the same either way')),
  ).toBeVisible()

  // --- download ----------------------------------------------------------------
  const saving = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'Download cleaned file' }).click()
  const file = await saving
  expect(file.suggestedFilename()).toBe('store_orders (tidied).csv')
  const cleaned = readFileSync(await file.path(), 'utf8').trim().split('\n')
  const raw = readFileSync(ORDERS, 'utf8').trim().split('\n')
  expect(cleaned.length).toBeGreaterThan(1)
  expect(cleaned.length).toBeLessThanOrEqual(raw.length)
})

test('steps saved from one file clean the next one', async ({ page }) => {
  await page.goto('/')

  // --- clean a file, and keep its steps ----------------------------------------
  await page.getByLabel('Choose a file to upload').setInputFiles(SAMPLE)
  await expect(page.getByRole('heading', { name: /Already fixed/ })).toBeVisible()

  const suggestion = page
    .locator('article')
    .filter({ hasText: 'holds two things in one column' })
    .first()
  await suggestion.getByRole('button', { name: 'Accept' }).click()
  const panel = page.getByRole('complementary', { name: "What we're doing" })
  await expect(panel.getByText(/Split "Department_Region"/)).toBeVisible()

  const saving = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'Download the steps' }).click()
  const steps = await (await saving).path()

  // --- use them on next month's file -------------------------------------------
  await page.getByRole('button', { name: 'Home' }).click()
  await expect(page.getByText('Drop a CSV or Excel file here')).toBeVisible()

  await page.getByLabel('Choose a saved recipe file').setInputFiles(steps)
  await page.getByLabel('Choose a file to upload').setInputFiles(MESSIER)

  await expect(page.getByRole('heading', { name: 'Messy_Employee_dataset_messier.csv' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'We re-used' })).toBeVisible()
  // The split it was told to do is in the panel, without anyone accepting it again.
  await expect(panel.getByText(/Split "Department_Region"/)).toBeVisible()
  // And the review screen still renders: the steps it detects carry the same ids.
  await expect(page.getByRole('heading', { name: /Already fixed/ })).toBeVisible()
})

test('steps that do not fit are refused without costing the upload', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Choose a file to upload').setInputFiles(SAMPLE)
  await expect(page.getByRole('heading', { name: /Already fixed/ })).toBeVisible()
  const panel = page.getByRole('complementary', { name: "What we're doing" })
  const saving = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'Download the steps' }).click()
  const steps = await (await saving).path()

  await page.getByRole('button', { name: 'Home' }).click()
  await page.getByLabel('Choose a saved recipe file').setInputFiles(steps)
  await page.getByLabel('Choose a file to upload').setInputFiles(ORDERS)

  // The file is open and usable; only the steps were turned away.
  await expect(page.getByRole('heading', { name: 'store_orders.csv' })).toBeVisible()
  const refusal = page.getByRole('alert').filter({ hasText: "couldn't use those steps" })
  await expect(refusal).toBeVisible()
  await expect(refusal.getByRole('listitem').first()).toContainText('needs a column called')
})
