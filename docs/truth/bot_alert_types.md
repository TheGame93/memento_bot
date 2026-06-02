# For every alert
- Title: a string of text

## Type 1 - Monthly (day)
- This is a monthly recurring alert that will be triggered when some day/month condition are satisfied
- Select one or more days (1-31)
- Memo if 29,30 and 31 are selected: if the month is shorter, it will trigger on the last day
- Select the interval between months (every 1, 2, 3, etc... months). Make the user write it in the chat.
- If the interval is larger than 1 (so there are skip months) ask explicitely the user to pinpoint the first occurence of the alert

## Type 2 - Monthly (rel.)
- This is a monthly recurring alert that will be triggered when some day/month condition are satisfied
- Select one or more istances (first, second, third, fourth, fifth, second-to-last, last)
- Select one or more weekdays (MON-SUN)
- Select the interval between months (every 1, 2, 3, etc... months). Make the user write it in the chat.
- If the interval is larger than 1 (so there are skip months) ask explicitely the user to pinpoint the first occurence of the alert

## Type 3 - Weekly
- This is a weekly recurring alert that will be triggered when some day/week condition are satisfied
- Select one or more weekdays (MON-SUN)
- Select the interval between weeks (every 1, 2, 3, etc... weeks). Make the user write it in the chat.
- If the interval is larger than 1 (so there are skip months) ask explicitely the user to pinpoint the first occurence of the alert

## Type 4 - Yearly
- This is yearly a recurring alert that will be triggered on specific days
- Select one or more days, in the format DD/MM

## Type 5 - Once
- This is a one time alert, triggering on a single specific date
- Select one date in the form of DD/MM, DD/MM/YY or DD/MM/YYYY
- When DD/MM/YY is used, the bot normalizes it to DD/MM/20YY
- If the date is today, the year is required to avoid ambiguity

## Type 6 - Birthday
- This is a yearly recurring alert for birthdays
- Select one date in the form of DD/MM
- Time of the alert (10:00, CUSTOM)
- No picture

## Type 7 - Daily
- This is a daily recurring alert for events that repeat every N days
- The interval step is mandatory and appears before `Alert Settings`
- The interval prompt uses day units ("How many days between occurrences?")
- In daily mode there is no quick "Each day" button
- If the user enters interval `1`, the bot asks explicit confirmation:
  - "I'm sure"
  - "Change interval"
- The same confirm-on-`1` behavior applies both in initial add-flow and in settings edit flow
- If interval is larger than `1`, the bot asks the first occurrence date (start marker) to anchor the cycle
- Detail cards render daily recurrence as:
  - `Every Day` for interval `1`
  - `Every N Days` for interval `>1`

# For every alert
- tags (between health, Home, Work, Car, Documents, Pet, Family, Other, DONE) multiple tags or none can be selected
- Pre-alert (-1d, -1w, -1m, CUSTOM)
- Time of the alert (10:00, CUSTOM)
- Do you want to upload a picture (YES/NO)  (except Birthday)

- final review of the information inserted with a "Save" and "Discard" button
