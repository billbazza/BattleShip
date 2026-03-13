# Battleship Intake Form — Tally Build Guide
Recreate in Tally.so. Add the welcome screen text first, then questions in order.

---

## WELCOME SCREEN (add as intro page in Tally)

Before you start — a word on what this is.

My name's Will. I'm 47. A year ago my Apple Watch told me my fitness age was 55. My blood pressure was creeping up. A holiday photo made me face what I'd been avoiding for years.

I didn't join a fancy gym or hire an expensive PT. I walked — 20km every day, without fail. Stopped drinking. Tracked food loosely. Five months later I added gym work at lunchtime. Four months of that and my fitness age sits at 17–18. All the excess weight gone.

I built Battleship because I know exactly where you are right now.

This questionnaire takes 4 minutes. Answer honestly — the more specific you are, the more useful your personalised diagnosis will be.

One condition: this only works if you're ready to actually do something about it.

---

## QUESTIONS (in order)

1. SHORT TEXT — What's your first name?
2. SHORT TEXT — What is your weight? (e.g. 14st 6lb or 91kg)
3. SHORT TEXT — Rough height? (e.g. 5ft 11 or 180cm)
4. EMAIL — Where should I send your Battleship Diagnosis Report?
   *Note: Your email will only ever be used to send your diagnosis and programme content. Nothing else.*
5. NUMBER — How old are you?
6. SHORT TEXT — Where are you based? (Country / region — e.g. "Manchester, UK")

---

7. MULTIPLE CHOICE (pick up to 3) — What's your biggest frustration right now?
   - Low energy / always tired
   - Carrying too much weight
   - No motivation to exercise
   - Poor sleep
   - Stress / anxiety
   - Drinking more than I should
   - Joint pain or injury limiting me
   - Feel like I've lost my old self
   - Other

8. LONG TEXT — If you picked "Other" above, please give some detail.

9. MULTIPLE CHOICE — What does your typical working day look like?
   - Desk-based / office or home
   - Mix of sitting and moving
   - Physically active job
   - Shifts / irregular hours

10. MULTIPLE CHOICE — How many hours of sleep do you get on a typical night?
    - Less than 5
    - 5–6 hours
    - 6–7 hours
    - 7–8 hours
    - More than 8

11. OPINION SCALE (1–10) — How would you describe your current stress level?
    1 = Relaxed and in control → 10 = Constantly overwhelmed

12. MULTIPLE CHOICE (tick all that apply) — Do you have any injuries or physical limitations I should know about?
    - Bad back
    - Knee problem
    - Shoulder problem
    - Hip problem
    - Heart condition or blood pressure issues
    - Other
    - No injuries

13. SHORT TEXT — If you selected "Other" above, briefly describe:

---

14. MULTIPLE CHOICE — How many times have you seriously tried to get in shape in the past 5 years?
    - Never really tried
    - Once or twice
    - Three or four times
    - Five or more times

15. MULTIPLE CHOICE (tick all that apply) — What have you tried before?
    - Gym membership
    - Personal trainer
    - Running / Couch to 5K
    - Slimming clubs (WW, Slimfast etc.)
    - Calorie counting apps
    - Fasting protocols
    - Online programmes
    - Nothing structured

16. MULTIPLE CHOICE (tick the main reasons) — Why do you think previous attempts didn't stick?
    - Too restrictive / not sustainable
    - Life got in the way
    - Didn't see results fast enough
    - Injury or illness
    - Lack of accountability
    - Wrong approach for my lifestyle
    - Willpower / motivation ran out

17. LONG TEXT — Anything else you want to tell me about why it's been hard? Tell me in your own words.

---

18. MULTIPLE CHOICE — What time of day could you realistically exercise?
    - Early morning (before 7am)
    - Morning (7–9am)
    - Lunchtime
    - Afternoon
    - Evening
    - Varies / no fixed time

19. LONG TEXT — Do you commute to work, and is any part of your journey walkable?

20. LONG TEXT — Is there anything that makes certain days or times impossible for you?

21. MULTIPLE CHOICE (tick all that apply) — Which days are your most reliable?
    - Monday
    - Tuesday
    - Wednesday
    - Thursday
    - Friday
    - Saturday
    - Sunday

---

22. MULTIPLE CHOICE — How would you describe your relationship with food?
    - Eat well most of the time
    - Healthy in the week, off-track at weekends
    - Grab what's convenient, not much planning
    - Emotional eating / comfort eating
    - Skip meals / irregular eating
    - Have tried lots of diets

23. MULTIPLE CHOICE — On a typical weekday, when do you usually eat your last meal?
    - Before 6pm
    - 6–7pm
    - 7–8pm
    - After 8pm
    - It varies a lot

24. LONG TEXT — Do you have any upcoming events that matter to you? (holiday, wedding, birthday milestone — these help me focus the plan)

25. MULTIPLE CHOICE — What does a typical weekend look like physically?
    - Pretty active (walking, sport, outdoors)
    - Mix of active and sedentary
    - Mostly sitting / resting
    - It varies

---

26. STATEMENT (display text, no answer needed):
    *This section is confidential and non-judgmental. Alcohol has a significant impact on fat loss, sleep, blood pressure, and energy. I ask because it helps me give you a more accurate diagnosis — not to judge you.*

27. MULTIPLE CHOICE — How would you describe your relationship with alcohol?
    - I rarely or never drink
    - Occasional drinker (1–2 times per month)
    - Social drinker (weekends only)
    - Regular drinker (most evenings)
    - I drink more than I'd like to
    - It's something I'm actively trying to reduce

28. MULTIPLE CHOICE — Roughly how many units do you drink per week? (1 unit = 1 small glass wine / half pint beer)
    - 0 units
    - 1–7 units (within guidelines)
    - 8–14 units
    - 15–21 units
    - More than 21 units
    - I'm not sure

29. MULTIPLE CHOICE — How do you feel about reducing alcohol as part of a reset?
    - Not applicable — I don't drink
    - Open to it, it's not a big deal
    - Would find it hard but willing to try
    - Not ready to address this right now

---

30. MULTIPLE CHOICE (pick ONE) — What's your primary goal for the next 12 weeks?
    - Lose fat / get leaner
    - Build strength and muscle
    - Improve energy and fitness
    - Sort out blood pressure / health markers
    - Feel better in myself generally

31. MULTIPLE CHOICE (tick all that apply) — What equipment do you have access to?
    - Commercial gym
    - Home gym / weights
    - Resistance bands only
    - No equipment / bodyweight only
    - Pool / swimming

32. MULTIPLE CHOICE — How much time can you realistically commit to structured exercise each week?
    - Less than 2 hours
    - 2–3 hours
    - 3–5 hours
    - More than 5 hours

33. LONG TEXT — What does success look like for you at Week 12? Describe it in your own words — the more specific the better.

34. MULTIPLE CHOICE — How did you hear about Battleship?
    - Instagram
    - Facebook
    - Google search
    - Word of mouth / friend
    - Other

35. LONG TEXT — Is there anything else you want me to know before I write your diagnosis? Anything at all.

---

## AFTER BUILDING

1. In Tally: Integrations → Webhooks → add your pipeline URL:
   http://YOUR_SERVER_IP:5100/tally-webhook

2. Note the form ID from the Tally URL (e.g. tally.so/r/XXXXXX) and update TALLY_FORM_ID in the pipeline

3. Update the Typeform link on the Carrd website and diagnosis email to the new Tally URL
