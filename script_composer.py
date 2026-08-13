#!/usr/bin/env python3
"""
script_composer.py — writes fresh, original scripts so you never run out.

How it works:
  Six themes (discipline, start-now, doubt, consistency, comparison, comeback).
  Each theme has interchangeable HOOKS (2 lines), BODIES (3 lines) and CLOSERS
  (2 lines) written to combine naturally. 4x4x4 per theme = 64 combos x 6 themes
  = 384 unique scripts (a year+ of daily videos). Used combos are tracked in
  state.json so nothing repeats.

  If trends_report.json exists (from trend_scan.py), themes matching this
  week's trending hook-words get picked more often.

Usage:
  python3 script_composer.py --ensure 7   # top up content.json to >=7 unused scripts
  python3 script_composer.py --add 7      # force-add 7 new scripts
  python3 script_composer.py --stats      # how many combos remain
"""

import argparse
import json
import os
import random
from datetime import date

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
# Per-channel paths, resolved at run time. Default to motivation so any legacy
# `import script_composer as sc; sc.compose(...)` keeps writing motivation's files.
_P = _paths.paths(None)
CONTENT = _P["content"]
STATE = _P["state"]
TRENDS = _P["trends"]
LIBRARY = _P["library"]
CONFIG = _P["config"]
# The niche whose bank we compose from (set by set_channel()).
_NICHE = _paths.channel_meta("motivation").get("niche", "motivation")

# ---------------------------------------------------------------- banks
# Rules: every hook/body/closer is self-contained (works in any combination
# within its theme). Hooks grab in the first line. Closers end with a command.

MOTIVATION_BANK = {
    "discipline": {
        "keywords": ["discipline", "disciplined", "habit", "habits", "hard", "work", "grind"],
        "hooks": [
            ["Motivation is a liar.", "It leaves the moment things get hard."],
            ["Nobody feels like it at 6 AM.", "Winners do it anyway."],
            ["Talent is everywhere.", "Discipline is rare."],
            ["Your feelings don't run this.", "Your standards do."],
        ],
        "bodies": [
            ["Discipline means doing it tired,", "doing it bored, doing it scared,", "especially when nobody is watching."],
            ["Every excuse feels reasonable in the moment.", "But excuses compound like debt,", "and one day the bill arrives."],
            ["The gym, the books, the early mornings,", "none of it is punishment.", "It is the price of the person you want to be."],
            ["You don't need a perfect routine.", "You need one promise to yourself", "that you refuse to break today."],
        ],
        "closers": [
            ["Choose what you want most,", "over what you want right now."],
            ["Keep the promise you made to yourself.", "Starting today."],
            ["Be stronger than your strongest excuse.", "That's the whole game."],
            ["Do it especially when you don't feel like it.", "That's when it counts double."],
        ],
    },
    "startnow": {
        "keywords": ["start", "now", "today", "begin", "waiting", "time"],
        "hooks": [
            ["You are not early. You are not late.", "You are exactly one decision away."],
            ["Stop planning your comeback.", "Start living it."],
            ["A year from now,", "you'll wish you had started today."],
            ["The perfect moment is a myth.", "There is only now."],
        ],
        "bodies": [
            ["The time will pass anyway.", "Twelve months from today arrives either way,", "with or without your progress."],
            ["Messy action beats perfect plans.", "You can fix a bad first attempt,", "but you can't fix the one you never made."],
            ["Waiting feels safe, but it's a slow leak.", "Every day of delay", "quietly costs you the person you could be."],
            ["You already know the first step.", "You've known it for months.", "What you're missing isn't knowledge, it's a decision."],
        ],
        "closers": [
            ["Start now. Start scared. Start small.", "Just start."],
            ["One day, or day one.", "You decide today."],
            ["Take the first step before bed tonight.", "Momentum will handle the rest."],
            ["Begin before you feel ready.", "Nobody ever feels ready."],
        ],
    },
    "doubt": {
        "keywords": ["doubt", "fear", "afraid", "believe", "mind", "mindset", "scared"],
        "hooks": [
            ["Doubt has killed more dreams", "than failure ever will."],
            ["The scariest voice you'll ever hear", "is the one inside your own head."],
            ["Fear is not a stop sign.", "It's a compass."],
            ["Nobody is thinking about your failure.", "They're too busy fearing their own."],
        ],
        "bodies": [
            ["You don't lose when you fall.", "You lose the moment you convince yourself", "you were never good enough to try."],
            ["The thing you're most afraid of", "is usually the exact direction", "your growth is hiding in."],
            ["Confidence isn't born, it's built,", "one scary rep at a time,", "by people who acted while trembling."],
            ["Your brain is built to keep you safe,", "not to make you great.", "Sometimes you have to overrule it."],
        ],
        "closers": [
            ["Silence the doubt with action.", "It can't argue with results."],
            ["Do the thing that scares you today.", "That's where your new life begins."],
            ["Feel the fear.", "Do it anyway."],
            ["Stop negotiating with your fear.", "It doesn't get a vote."],
        ],
    },
    "consistency": {
        "keywords": ["consistency", "consistent", "daily", "everyday", "small", "better", "percent"],
        "hooks": [
            ["You don't need a miracle.", "You need a Tuesday, repeated."],
            ["One percent better every day", "is invisible, until it's unstoppable."],
            ["Intensity impresses people.", "Consistency changes lives."],
            ["Anyone can go hard for a week.", "Legends go steady for years."],
        ],
        "bodies": [
            ["Small steps look like nothing at first.", "Then one day you look up", "and you're somewhere you used to dream about."],
            ["The workout you almost skipped,", "the page you almost didn't write,", "those are the bricks the whole thing is built from."],
            ["Success is boring up close.", "It's the same small choices,", "made again and again without applause."],
            ["Motivation gets you to day three.", "Systems and streaks", "get you to year three."],
        ],
        "closers": [
            ["Show up today. Show up tomorrow.", "Let time do the multiplying."],
            ["Protect your streak like it's gold.", "Because it is."],
            ["Don't break the chain today.", "Future you is counting on it."],
            ["Stay boring. Stay consistent.", "Become undeniable."],
        ],
    },
    "comparison": {
        "keywords": ["comparison", "compare", "race", "others", "watching", "scroll", "scrolling"],
        "hooks": [
            ["Comparison is the thief of joy,", "and you keep leaving the door open."],
            ["While you watch their highlight reel,", "your own story sits on pause."],
            ["Someone will always be ahead of you.", "That was never the point."],
            ["Their chapter twenty", "is not your chapter one."],
        ],
        "bodies": [
            ["The scroll is rigged.", "You're comparing your worst mornings", "to a stranger's best edited seconds."],
            ["Every minute spent measuring their life", "is a minute stolen", "from building your own."],
            ["You are not behind.", "You are on a different road,", "with a different map and a different finish line."],
            ["Envy is data, nothing more.", "It shows you what you want.", "Now go earn it instead of watching it."],
        ],
        "closers": [
            ["Run your own race.", "Win it in your own time."],
            ["Compare yourself to yesterday's you.", "Nobody else."],
            ["Put the phone down.", "Go build something they'll scroll past."],
            ["Your only rival is in the mirror.", "Beat them daily."],
        ],
    },
    "focus": {
        "keywords": ["focus", "distraction", "phone", "scroll", "deep", "study", "studymotivation", "attention"],
        "hooks": [
            ["Your attention is the most valuable thing you own.", "Stop giving it away for free."],
            ["Every notification is someone", "spending your life for you."],
            ["Focus is the new superpower.", "Almost nobody has it anymore."],
            ["You're not lazy.", "You're just addicted to easy dopamine."],
        ],
        "bodies": [
            ["Deep work is where the magic lives.", "One hour, phone in another room,", "beats a whole day of distracted busy-ness."],
            ["The scroll steals your best hours", "and hands you nothing back", "but a vague feeling that time slipped away."],
            ["Your brain can do incredible things.", "But not while it's checking a screen", "every ninety seconds."],
            ["Single-tasking looks slow.", "It's actually the fastest way", "to work that people can't ignore."],
        ],
        "closers": [
            ["Put the phone in another room.", "Then watch what you become."],
            ["Protect your focus like it's your future.", "Because it is."],
            ["Do one thing at a time.", "Do it fully. Then move on."],
            ["Close the app. Open your real life.", "Starting now."],
        ],
    },
    "growth": {
        "keywords": ["growth", "learn", "learning", "invest", "read", "skill", "better", "improve", "selfimprovement"],
        "hooks": [
            ["The best investment on earth", "is the one you make in yourself."],
            ["You will never be paid more", "than the value you're able to create."],
            ["Boring skills, quietly stacked,", "build an unfair advantage."],
            ["Five years from now,", "you'll be an expert at something. Pick what."],
        ],
        "bodies": [
            ["Read the book. Take the course.", "Learn the skill everyone avoids.", "Knowledge compounds faster than money."],
            ["Every expert was once a beginner", "who refused to stay one,", "and kept showing up to the hard parts."],
            ["An hour a day, spent learning,", "is three hundred and sixty-five hours a year", "your competition didn't invest."],
            ["Growth is uncomfortable by design.", "If it feels easy, you've stopped.", "Lean into the stretch."],
        ],
        "closers": [
            ["Invest in your mind daily.", "It pays the best interest there is."],
            ["Learn one hard thing this week.", "Future you is watching."],
            ["Get a little better today.", "Repeat for a decade. Win."],
            ["Feed your mind before your feed.", "Every single morning."],
        ],
    },
    "comeback": {
        "keywords": ["comeback", "setback", "fail", "failure", "fall", "quit", "rest", "nevergiveup"],
        "hooks": [
            ["They counted you out.", "Perfect. Now you have surprise on your side."],
            ["Rock bottom has one gift:", "it's solid enough to build on."],
            ["The comeback is always stronger", "than the setback."],
            ["You didn't come this far", "to only come this far."],
        ],
        "bodies": [
            ["Getting knocked down is not the end.", "Staying down is.", "And staying down is a choice you don't have to make."],
            ["Every champion has a chapter", "they don't tell at parties,", "the one where they almost quit."],
            ["If you're tired, rest.", "Resting is part of the plan.", "Quitting ends the story forever."],
            ["Scars aren't proof you were broken.", "They're proof that you healed", "and kept moving anyway."],
        ],
        "closers": [
            ["Get up one more time than you fall.", "That's the entire secret."],
            ["Turn the pain into fuel.", "Then go make it count."],
            ["Your setback just wrote the setup.", "Now deliver the comeback."],
            ["Stand up. Dust off.", "Go again."],
        ],
    },
    "patience": {
        "keywords": ["patience", "slow", "time", "wait", "seasons", "process", "trust"],
        "hooks": [
            ["You're not behind.", "You're early and impatient."],
            ["Everything you want", "is on the other side of boring."],
            ["Bamboo grows underground for years.", "Then it explodes."],
            ["You want in six months", "what takes six years."],
        ],
        "bodies": [
            ["Nothing real grows on your timeline.", "Trees don't apologise for their season,",
             "and neither should you."],
            ["The exciting part is the smallest part.", "The rest is repetition nobody claps for.",
             "That repetition is where it's decided."],
            ["For years it looks like nothing works.", "Roots are being built the whole time,",
             "and then the growth is impossible to miss."],
            ["Speed feels like progress.", "But depth is what actually holds,",
             "and depth cannot be rushed."],
        ],
        "closers": [
            ["Stay in it longer than feels reasonable.", "That's where most people leave."],
            ["Trust the season you're in.", "Keep watering it."],
            ["Slow is still forward.", "Don't confuse the two."],
            ["Give it time it actually needs.", "Then decide."],
        ],
    },
    "fear": {
        "keywords": ["fear", "afraid", "scared", "courage", "brave", "risk", "nervous"],
        "hooks": [
            ["Fear doesn't protect you.", "It just keeps you exactly where you are."],
            ["You're not scared of failing.", "You're scared of being seen failing."],
            ["Courage isn't the absence of fear.", "It's moving while afraid."],
            ["The thing you're avoiding", "is the thing that would change everything."],
        ],
        "bodies": [
            ["Fear shows up at the edge of growth.", "It marks the direction, not the danger,",
             "and it never points at easy things."],
            ["Nobody is watching as closely as you think.", "They're busy fearing their own audience.",
             "Do it badly in public and move on."],
            ["Brave people feel exactly what you feel.", "Their hands shake the same way,",
             "they just don't wait for the shaking to stop."],
            ["The task you keep postponing", "is usually the one that matters most.",
             "Avoidance is a signal, not a strategy."],
        ],
        "closers": [
            ["Do it scared.", "That's the only version available."],
            ["Move toward the thing you're avoiding.", "Start today."],
            ["Feel it and go anyway.", "That's courage."],
            ["Your fear knows where the growth is.", "Follow it."],
        ],
    },
    "identity": {
        "keywords": ["identity", "become", "self", "character", "who", "person", "standards"],
        "hooks": [
            ["You don't rise to your goals.", "You fall to your habits."],
            ["Stop trying to be motivated.", "Start being someone who shows up."],
            ["Every action is a vote", "for who you're becoming."],
            ["Change what you do", "and who you are follows."],
        ],
        "bodies": [
            ["Goals are what you say you want.", "Habits are what you actually do,",
             "and only one of them shapes your life."],
            ["Motivation is a feeling — it comes and goes.", "Identity is a decision you keep making,",
             "and it doesn't need a good mood."],
            ["One workout doesn't change your body.", "It casts a vote for being someone who trains.",
             "Enough votes and the identity is real."],
            ["You can't think your way into a new self.", "You act your way there, badly at first,",
             "until the evidence stacks up."],
        ],
        "closers": [
            ["Cast one vote today.", "That's how a person changes."],
            ["Be it before you feel it.", "The feeling follows."],
            ["Choose the identity, then act like it.", "Starting now."],
            ["Small actions, repeated, become you.", "Pick one."],
        ],
    },
    "ownership": {
        "keywords": ["ownership", "responsibility", "blame", "excuses", "control", "accountable"],
        "hooks": [
            ["Nobody is coming to save you.", "That's the good news."],
            ["Blame feels good", "and costs you everything."],
            ["You can't control what happened.", "You own everything after."],
            ["Stop asking why it happened to you.", "Start asking what now."],
        ],
        "bodies": [
            ["If nobody is coming, you're not waiting.", "The only permission you need is yours,",
             "and you can give it right now."],
            ["Blame hands your power to someone else.", "It's comfortable and completely useless,",
             "because they're not going to fix it."],
            ["The event isn't yours. The response is.", "That gap is where your whole life happens,",
             "and it's yours every single time."],
            ["'Why me' keeps you in the story.", "'What now' gets you out of it.",
             "One question is a trap, the other is a door."],
        ],
        "closers": [
            ["Take the responsibility nobody assigned you.", "That's where power lives."],
            ["Stop waiting for fair.", "Start working with real."],
            ["Own the next move.", "It's the only one you control."],
            ["Your life is your job.", "Clock in."],
        ],
    },
}


# ================================================================ EDUCATION
# Niche: Everyday English + communication skills. Same shape as MOTIVATION_BANK
# (hooks[2] + bodies[3] + closers[2]). 6 themes x 4x4x4 = 384 unique combos.
# All original phrasing; grammar advice is standard and correct.
EDUCATION_BANK = {
    "vocabulary": {
        "keywords": ["english", "vocabulary", "words", "word", "fluent", "speak", "learnenglish"],
        "hooks": [
            ["Stop saying 'very big'.", "It makes you sound like a beginner."],
            ["One word", "that replaces ten boring ones."],
            ["Upgrade three words today", "and instantly sound fluent."],
            ["'Very' is a weak word.", "Strong speakers rarely need it."],
        ],
        "bodies": [
            ["Instead of 'very big', say enormous.", "Instead of 'very small', say tiny.", "Instead of 'very happy', say thrilled."],
            ["Instead of 'very tired', say exhausted.", "Instead of 'very hungry', say starving.", "Instead of 'very cold', say freezing."],
            ["'Good' becomes excellent or brilliant.", "'Bad' becomes awful or terrible.", "One precise word beats two vague ones."],
            ["'Very scared' becomes terrified.", "'Very angry' becomes furious.", "'Very interesting' becomes fascinating."],
        ],
        "closers": [
            ["Save this and use one today.", "That's how fluency is built."],
            ["Pick one word and say it out loud.", "Speaking beats memorising."],
            ["Follow for one upgrade a day.", "In a month you'll sound different."],
            ["Replace one weak word right now.", "Small swaps, big difference."],
        ],
    },
    "phrases": {
        "keywords": ["phrases", "phrase", "conversation", "polite", "natural", "communication", "talk"],
        "hooks": [
            ["3 English phrases", "that instantly sound fluent."],
            ["Natives don't say 'yes' and 'no'.", "Here's what they say instead."],
            ["Sound polite in any situation", "with these three phrases."],
            ["Stop sounding like a textbook.", "Say it the way natives do."],
        ],
        "bodies": [
            ["'I'd love to' — a warm yes.", "'I'm afraid I can't' — a soft no.", "'Let me get back to you' — buys time."],
            ["'No worries' means it's fine.", "'Fair enough' means I understand.", "'Sounds good' means I agree."],
            ["'Could you...' is politer than 'can you'.", "'Would you mind...' is softer still.", "Small words make you sound kind."],
            ["'To be honest' opens a real answer.", "'By the way' adds a side point.", "'Anyway' brings you back on track."],
        ],
        "closers": [
            ["Pick one phrase and use it today.", "That's how natural speech grows."],
            ["Follow for one phrase a day.", "In a month you'll sound different."],
            ["Say it out loud right now.", "Speaking beats memorising."],
            ["Try one in your next chat.", "Confidence comes from doing."],
        ],
    },
    "grammar": {
        "keywords": ["grammar", "mistake", "mistakes", "correct", "fix", "tense", "tenses"],
        "hooks": [
            ["You say 'I am agree'?", "Here's the fix natives never miss."],
            ["This tiny grammar mistake", "makes you sound less fluent."],
            ["Two words people always mix up.", "Never confuse them again."],
            ["Fix this one error", "and your English jumps a level."],
        ],
        "bodies": [
            ["Don't say 'I am agree'.", "Say 'I agree' — no 'am'.", "Agree is a verb, not an adjective."],
            ["'Since' is for a point in time.", "'For' is for a length of time.", "Since Monday, for three days."],
            ["Use 'I have been' for ongoing.", "Use 'I went' for finished past.", "Time words decide the tense."],
            ["'Fewer' is for things you count.", "'Less' is for things you can't.", "Fewer bottles, less water."],
        ],
        "closers": [
            ["Say the correct version out loud.", "That's how it sticks."],
            ["Save this before you forget it.", "Review it tomorrow."],
            ["Follow for one fix a day.", "Clean grammar builds trust."],
            ["Catch yourself next time.", "Awareness is half the fix."],
        ],
    },
    "connectors": {
        "keywords": ["connectors", "linking", "smooth", "flow", "sentence", "advanced"],
        "hooks": [
            ["Three tiny words", "that make you sound native."],
            ["Link your sentences like a native", "with these little words."],
            ["Your English sounds choppy?", "You're missing connectors."],
            ["Small linking words", "make you sound advanced."],
        ],
        "bodies": [
            ["'Actually' corrects politely.", "'Basically' summarises fast.", "'Honestly' builds trust."],
            ["'However' shows a contrast.", "'Therefore' shows a result.", "'Meanwhile' shows another side."],
            ["'For example' proves your point.", "'In fact' adds strength.", "'On the other hand' shows balance."],
            ["'As a result' explains why.", "'In short' wraps it up.", "'That said' softens a turn."],
        ],
        "closers": [
            ["Drop one connector into your next sentence.", "Watch it flow."],
            ["Save this and practise one today.", "Smooth speech is learned."],
            ["Follow for one word a day.", "Fluency is built in pieces."],
            ["Read your writing out loud.", "Add a connector where it jumps."],
        ],
    },
    "pronunciation": {
        "keywords": ["pronunciation", "pronounce", "sound", "accent", "silent", "stress"],
        "hooks": [
            ["You're saying this word wrong.", "Almost everyone does."],
            ["Silent letters trick learners.", "Here's how to beat them."],
            ["Stress the wrong part", "and natives can't follow you."],
            ["Three words", "you've been mispronouncing."],
        ],
        "bodies": [
            ["'Comfortable' is KUMF-ta-bul.", "Not com-for-TABLE.", "Three syllables, not four."],
            ["The 'b' in 'comb' is silent.", "The 'k' in 'knife' is silent.", "The 'l' in 'salmon' is silent."],
            ["'Photograph' stresses the first part.", "'Photographer' shifts to the second.", "The stress moves with the word."],
            ["'Vegetable' is VEJ-ta-bul.", "'Wednesday' is WENZ-day.", "We swallow the middle sounds."],
        ],
        "closers": [
            ["Say it slowly three times.", "Then speed up naturally."],
            ["Record yourself and compare.", "Your ear improves fast."],
            ["Follow for one sound a day.", "Clear speech opens doors."],
            ["Practise the tricky one aloud.", "Muscle memory does the rest."],
        ],
    },
    # The flagship series. Everything else in this bank teaches English in
    # general; this teaches the specific habits that mark an Indian speaker out
    # in an interview with a foreign recruiter. It replaced a "confidence" theme
    # whose scripts ("You don't need perfect grammar") taught nothing and
    # converted 604 views into zero subscribers — the same product as the
    # motivation channel, in a teacher's costume.
    #
    # These are NOT "bad English". Indian English is a legitimate variety and
    # saying otherwise to this audience would be both false and insulting. The
    # framing every hook keeps: here is what changes when the listener is not
    # Indian. That is the audience's actual goal — placements, global teams —
    # and it is why they would subscribe for the next one.
    "indian-english": {
        "keywords": ["indian english", "interview english", "english mistakes",
                     "speak english", "placement", "interview", "fluent"],
        "hooks": [
            ["In an interview, never open with 'Myself Rohit'.", "It's the first thing that marks you out."],
            ["'I passed out in 2024'", "means you fainted."],
            ["Stop writing 'please revert back'.", "It doesn't mean what you think."],
            ["'Do the needful' confuses everyone", "outside India."],
            ["'I am having a car' is the giveaway.", "One rule fixes it forever."],
            ["'I am working here since two years.'", "Two mistakes in one sentence."],
            ["'Prepone' is not a word", "outside India."],
            ["'I'm out of station' sounds like a train.", "Here's what natives say."],
            ["'Let's discuss about the project.'", "Delete one word and it's perfect."],
            ["'Cousin brother' doesn't exist", "in English."],
            ["'Kindly do it' sounds a hundred years old.", "One word makes you modern."],
            ["Never say 'the backside of the building'.", "It means something else abroad."],
            ["'I am giving my exam tomorrow.'", "Only teachers give exams."],
            ["'What is your good name?'", "There is no bad name."],
            ["'Sleep is coming' and 'open the light'", "are translated, not spoken."],
            ["'He is my batchmate' means nothing", "to a foreign recruiter."],
            # Second wave. The first 16 were down to 4 unclaimed after a week,
            # which would have retired the series in four more uploads. A series
            # that runs out is just a theme again.
            ["'I have a doubt' worries your interviewer.", "You meant something else entirely."],
            ["'What is your native place?'", "Nobody abroad says this."],
            ["'Today morning I woke up late.'", "One word is wrong."],
            ["'One of my friend' — almost.", "One letter changes everything."],
            ["'This phone is very costly.'", "Natives reach for a different word."],
            ["'I met him two years back.'", "Back is the wrong direction."],
            ["Someone thanks you. You say 'mention not'?", "Here's what natives actually say."],
            ["'Where are you put up?'", "It sounds like you're being stored."],
            ["'We were just doing time pass.'", "That phrase doesn't travel."],
            ["Asking for a 'rubber' in America", "will get you a very strange look."],
            ["'I'm going to my friend's marriage.'", "You mean the wedding."],
            ["'Please repeat it again.'", "Two words doing one job."],
            ["'I'm from Delhi only.'", "Delete the last word."],
            ["'Convey my regards to your family.'", "It sounds like a telegram."],
        ],
        # THE FIX COMES FIRST. This is not a style preference, it is what the
        # retention data says. These Shorts run 23-25s at 37-50% average view,
        # so the audience leaves around 11 seconds. The old bodies opened with
        # context and put the correction third, which landed it at ~15s — past
        # the exit. Viewers got the setup and never the payoff, which is how
        # 4,168 views produced one subscriber.
        #
        # Every body is now [the correct form, the reason]. With a 5-line
        # budget the fix is line 3, around 8-11s, inside the window.
        "bodies": [
            ["Say: 'I'm Rohit.'", "Two words, and you sound ready."],
            ["Say: 'I graduated in 2024.'", "Passed out means you fainted."],
            ["Say: 'I'll get back to you.'", "Revert means go back to an old state."],
            ["Say exactly what you want: 'Could you approve this today?'", "Nobody abroad knows what 'the needful' is."],
            ["Say: 'I have a car.'", "Have, know, like, want — these never take '-ing'."],
            ["Say: 'I've been working here for two years.'", "Since needs a date. For needs a length."],
            ["Say: 'Can we move the meeting up?'", "Prepone does not exist outside India."],
            ["Say: 'I'm out of town.'", "Or: 'I'm away until Monday.'"],
            ["Say: 'Let's discuss the project.'", "Discuss already contains 'about'."],
            ["Say: 'my cousin'.", "A cousin is a cousin. No gender needed."],
            ["Say 'please' instead.", "Kindly belongs in hundred-year-old letters."],
            ["Say: 'behind the building'.", "Backside means your bottom."],
            ["Say: 'I'm taking my exam tomorrow.'", "The teacher gives. The student takes."],
            ["Say: 'What's your name?'", "Warmth comes from your tone, not extra words."],
            ["Say: 'I'm getting sleepy.' And: 'Turn on the light.'", "English turns lights on and off."],
            ["Say: 'We studied together.'", "Plain words travel further."],
            # Second wave — index-matched to the hooks above.
            ["Say: 'I have a question.'", "A doubt means you distrust someone."],
            ["Say: 'Where are you from?'", "Native place sounds like a census form."],
            ["Say: 'this morning'.", "Also 'this afternoon', 'tonight', 'last night'."],
            ["Say: 'one of my friends'.", "One of many — so, many."],
            ["Say: 'expensive'.", "Costly is for mistakes, not phones."],
            ["Say: 'two years ago'.", "Back is a direction. Ago is a time."],
            ["Say: 'You're welcome.'", "Or the easy one: 'No problem.'"],
            ["Say: 'Where do you live?'", "Put up is for a night, not a home."],
            ["Say: 'We were just killing time.'", "Or: 'We were hanging out.'"],
            ["Say: 'eraser'.", "In America, a rubber is a contraceptive."],
            ["Say: 'I'm going to a wedding.'", "A marriage is the relationship. A wedding is the day."],
            ["Say: 'Could you repeat that?'", "Repeat already means again."],
            ["Say: 'I'm from Delhi.'", "That 'only' is Hindi grammar wearing English words."],
            ["Say: 'Say hi to your family.'", "Warm beats formal, every time."],
        ],
        # A batch can only use each closer index once (see compose()), so the
        # number of closers is a hard cap on how many of this theme ship per
        # run. Four closers held the flagship series to 4 videos a batch no
        # matter how it was weighted — and 16 lessons sharing 4 sign-offs
        # sounded like a template anyway.
        "closers": [
            ["Follow — one Indian English fix every day.", "Your interview English sharpens with each one."],
            ["Save this before your next interview.", "Follow for tomorrow's fix."],
            ["Which one do you say? Tell me below.", "Follow — a new fix daily."],
            ["Placement season starts with how you speak.", "Follow for one fix a day."],
            ["One fix a day. That's the whole channel.", "Follow and start tomorrow."],
            ["Send this to a friend who says it.", "Follow for the next one."],
            ["You'll never unhear this one.", "Follow — a new fix every day."],
            ["Say the correct version out loud now.", "Follow for tomorrow's."],
            ["That's one less thing to worry about.", "Follow — daily fixes."],
            ["Your next interview just got easier.", "Follow for one a day."],
            ["Practise it once before you scroll on.", "Follow for the next fix."],
            ["Small change. Big difference abroad.", "Follow — one fix daily."],
        ],
    },
    "smalltalk": {
        "keywords": ["smalltalk", "conversation", "friendly", "chat", "social", "meeting"],
        "hooks": [
            ["'How are you?' isn't a real question.", "Here's what it actually means."],
            ["Small talk feels fake", "until you know the four safe topics."],
            ["Never let a conversation die again.", "Use this one trick."],
            ["Ending a chat politely", "is a skill nobody teaches you."],
        ],
        "bodies": [
            ["It's a greeting, not a health check.", "'Good, thanks — you?' is the whole answer.",
             "Save the real answer for real friends."],
            ["Weather, weekend, food, travel.", "All four are safe anywhere in the world,",
             "and everyone has something to say."],
            ["Never answer with one word.", "Add one detail, then ask back.",
             "'Busy — big project. You?' keeps it alive."],
            ["'Anyway, I should get going.'", "'It was great talking to you.'",
             "Signal first, then leave. Never just stop."],
        ],
        "closers": [
            ["Try one in your next conversation.", "Small talk is a skill, not a talent."],
            ["Follow for one social phrase a day.", "Confidence is built in small chats."],
            ["Say it out loud once now.", "Your mouth needs the practice."],
            ["Use it today, not someday.", "That's the whole difference."],
        ],
    },
    "workplace": {
        "keywords": ["work", "office", "email", "professional", "job", "career", "business"],
        "hooks": [
            ["Your English emails sound rude.", "You probably don't know why."],
            ["Say this in a meeting", "and people take you seriously."],
            ["Disagreeing politely at work", "is an English superpower."],
            ["'Sorry for the late reply'", "has a better version."],
        ],
        "bodies": [
            ["'Send me the file' is an order.", "'Could you send me the file?' is a request.",
             "One word decides how you sound."],
            ["'Can I add something here?' opens a door.", "'To build on that...' shows you listened.",
             "'My concern is...' names a problem calmly."],
            ["'I see it differently' is not rude.", "'That's fair, though have we considered...'",
             "Agree with the person, question the idea."],
            ["Don't apologise — thank instead.", "'Thanks for your patience' sounds confident,",
             "'sorry for the delay' sounds guilty."],
        ],
        "closers": [
            ["Use it in your next email.", "Small wording, big impression."],
            ["Follow for one work phrase a day.", "Professional English is learnable."],
            ["Save this before your next meeting.", "You'll want it."],
            ["Rewrite one sentence today.", "Notice how different it feels."],
        ],
    },
    "listening": {
        "keywords": ["listening", "listen", "understand", "fast", "native", "ear"],
        "hooks": [
            ["Natives don't speak fast.", "They just join their words together."],
            ["You know the words", "but can't hear them. Here's why."],
            ["'Whatcha doin?' is real English.", "Textbooks won't teach you this."],
            ["Stop watching with subtitles on.", "Do this instead."],
        ],
        "bodies": [
            ["'Want to' becomes 'wanna'.", "'Going to' becomes 'gonna'.",
             "Learn the joins and speed disappears."],
            ["Your ear expects each word separately.", "Real speech blends the endings together,",
             "so train on sound, not spelling."],
            ["'What are you doing' loses its middle.", "'Did you eat' becomes 'dijaeat'.",
             "This isn't lazy — it's the actual rhythm."],
            ["Watch once with subtitles.", "Then again without, same clip.",
             "Your ear fills the gaps the second time."],
        ],
        "closers": [
            ["Try it with one video today.", "Your ear improves faster than you think."],
            ["Follow for one listening tip a day.", "Understanding comes before speaking."],
            ["Replay one line five times.", "That's real practice."],
            ["Listen for the joins tomorrow.", "You'll start hearing them everywhere."],
        ],
    },
    "idioms": {
        "keywords": ["idiom", "idioms", "expression", "meaning", "slang", "natural"],
        "hooks": [
            ["'Break a leg' isn't a threat.", "Here's what natives really mean."],
            ["Three idioms", "you'll hear at work this week."],
            ["'It's not rocket science'", "and four more you should know."],
            ["Using idioms wrong", "is worse than not using them."],
        ],
        "bodies": [
            ["It means good luck, not injury.", "Actors said it before going on stage,",
             "because wishing luck was bad luck."],
            ["'Touch base' means check in briefly.", "'On the same page' means we agree.",
             "'Circle back' means talk about it later."],
            ["It means it's not complicated.", "'A piece of cake' means easy.",
             "'Once in a blue moon' means rarely."],
            ["Idioms are fixed — you can't change words.", "It's 'spill the beans', never 'drop the beans'.",
             "Learn the whole phrase or skip it."],
        ],
        "closers": [
            ["Use one this week.", "Idioms make you sound like a local."],
            ["Follow for one idiom a day.", "Real English lives in these phrases."],
            ["Comment an idiom you've heard.", "Let's decode it."],
            ["Learn it whole, not word by word.", "That's the rule."],
        ],
    },
    "questions": {
        "keywords": ["question", "questions", "ask", "asking", "polite", "clarify"],
        "hooks": [
            ["You've been asking questions wrong.", "This is why people pause."],
            ["Didn't understand?", "Never say 'what?' again."],
            ["One word turns a rude question", "into a polite one."],
            ["Asking for help in English", "has a formula."],
        ],
        "bodies": [
            ["'Where you are from?' is the common error.", "In questions, the verb comes first:",
             "'Where are you from?' Always."],
            ["'Sorry, could you repeat that?'", "'I didn't catch that last part.'",
             "Both are polite. 'What?' sounds sharp."],
            ["'What's your name?' is direct.", "'Could I ask your name?' is warm.",
             "'Could I' softens almost anything."],
            ["Name the problem, then ask.", "'I'm stuck on this part — could you help?'",
             "Vague requests get vague answers."],
        ],
        "closers": [
            ["Ask one question properly today.", "People notice the difference."],
            ["Follow for one speaking fix a day.", "Clear questions get real answers."],
            ["Say the correct version out loud.", "That's how it sticks."],
            ["Practise it before you need it.", "Pressure makes us forget."],
        ],
    },
    "storytelling": {
        "keywords": ["story", "storytelling", "past", "narrative", "describe", "interesting"],
        "hooks": [
            ["Your stories are boring in English.", "It's a structure problem, not vocabulary."],
            ["Natives tell stories in present tense.", "Even about last year."],
            ["Four words", "that make any story better."],
            ["Stop starting stories with 'so basically'.", "Try this instead."],
        ],
        "bodies": [
            ["Set the scene in one line.", "Then the problem, then what happened.",
             "Three beats. That's every good story."],
            ["'So I'm walking home and this guy...'", "Present tense pulls the listener in,",
             "like it's happening right now."],
            ["'Suddenly' adds surprise.", "'Meanwhile' adds a second thread.",
             "'In the end' signals you're finishing."],
            ["'You'll never guess what happened.'", "'This actually happened yesterday.'",
             "Give them a reason to listen first."],
        ],
        "closers": [
            ["Tell one short story today.", "Structure beats vocabulary."],
            ["Follow for one storytelling tip a day.", "People remember stories, not grammar."],
            ["Try the three-beat shape.", "It works in any language."],
            ["Practise on a friend tonight.", "Watch their face, not your words."],
        ],
    },
}


# ================================================================ FACTS
# Niche: Science & history "Did you know" facts. Every fact below was verified
# against mainstream reference sources before shipping. Same shape as the others.
FACTS_BANK = {
    "biology": {
        "keywords": ["body", "biology", "human", "brain", "organ", "science", "didyouknow"],
        "hooks": [
            ["Your body may have a hidden organ", "scientists only named in 2018."],
            ["An octopus has three hearts", "and blue blood."],
            ["Your stomach lining", "replaces itself every few days."],
            ["Your body makes new skin", "roughly every month."],
        ],
        "bodies": [
            ["It's called the interstitium —", "a fluid-filled layer under the skin,", "described by researchers in 2018."],
            ["Two hearts feed the gills,", "one feeds the body,", "and it pauses when the octopus swims."],
            ["Strong acid would digest the stomach itself,", "so the lining is constantly rebuilt,", "every few days, to survive it."],
            ["Skin cells are shed constantly.", "You lose millions every day,", "and grow a fresh outer layer in weeks."],
        ],
        "closers": [
            ["Follow — one brain-breaking fact daily.", "Bet you didn't know that."],
            ["Share with someone who won't believe it.", "See you tomorrow."],
            ["Comment a body fact you know.", "Let's compare."],
            ["Your body is stranger than fiction.", "Follow for more."],
        ],
    },
    "space": {
        "keywords": ["space", "star", "stars", "universe", "planet", "moon", "astronomy"],
        "hooks": [
            ["There are more stars in the sky", "than grains of sand on Earth."],
            ["A day on Venus", "is longer than its year."],
            ["Space is completely silent.", "Sound needs air to travel."],
            ["Neutron star material", "is almost unimaginably dense."],
        ],
        "bodies": [
            ["Estimates give about 10 sextillion stars.", "Beaches hold roughly 7 quintillion grains.", "The universe wins, by a lot."],
            ["Venus spins incredibly slowly.", "One rotation takes about 243 Earth days.", "Its orbit takes only about 225."],
            ["In a vacuum there's nothing to vibrate,", "so sound waves can't move.", "Space is eerily quiet."],
            ["A sugar-cube of neutron star", "would weigh about a billion tonnes.", "Gravity crushed it that tight."],
        ],
        "closers": [
            ["Follow — one cosmic fact daily.", "The universe is wilder than you think."],
            ["Share this with a stargazer.", "See you tomorrow."],
            ["Comment your favourite space fact.", "Let's hear it."],
            ["Look up tonight and wonder.", "Follow for more."],
        ],
    },
    "history": {
        "keywords": ["history", "ancient", "old", "past", "war", "empire", "historical"],
        "hooks": [
            ["Honey never spoils.", "3,000-year-old honey is still edible."],
            ["Oxford University is older", "than the Aztec Empire."],
            ["The Great Pyramid was ancient", "when Cleopatra was born."],
            ["The last woolly mammoths were alive", "while the pyramids were being built."],
        ],
        "bodies": [
            ["Bacteria can't grow in honey.", "Very low water, high acidity —", "sealed honey lasts millennia."],
            ["Teaching at Oxford began by 1096.", "The Aztec capital was founded in 1325.", "The gap is over two centuries."],
            ["The Great Pyramid was built around 2560 BC.", "Cleopatra was born in 69 BC.", "That's about 2,500 years apart."],
            ["A small population survived on Wrangel Island", "in the Arctic until roughly 1650 BC —", "centuries after the Great Pyramid was finished."],
        ],
        "closers": [
            ["Follow — one history fact daily.", "The past is stranger than you think."],
            ["Share with a history lover.", "See you tomorrow."],
            ["Comment a fact that shocked you.", "Let's compare notes."],
            ["History is full of surprises.", "Follow for more."],
        ],
    },
    "animals": {
        "keywords": ["animal", "animals", "nature", "wild", "creature", "ocean", "sea"],
        "hooks": [
            ["A shrimp's punch", "can boil the water around it."],
            ["Wombats produce", "cube-shaped droppings."],
            ["Some jellyfish", "can effectively reverse their aging."],
            ["A group of flamingos", "is called a flamboyance."],
        ],
        "bodies": [
            ["The mantis shrimp strikes so fast", "it creates a tiny collapsing bubble,", "flashing heat and light for an instant."],
            ["Their intestines shape the waste into cubes,", "which don't roll away,", "helping them mark their territory."],
            ["The 'immortal' jellyfish can revert", "to an earlier life stage,", "restarting its development."],
            ["English has wonderful group names.", "A flamboyance of flamingos,", "a parliament of owls, a murder of crows."],
        ],
        "closers": [
            ["Follow — one wild fact daily.", "Nature never runs out of surprises."],
            ["Share with an animal lover.", "See you tomorrow."],
            ["Comment the weirdest animal you know.", "Let's compare."],
            ["The wild is wilder than you think.", "Follow for more."],
        ],
    },
    "physics": {
        "keywords": ["physics", "light", "energy", "time", "water", "matter", "science"],
        "hooks": [
            ["Hot water can freeze", "faster than cold water sometimes."],
            ["Light from the Sun", "takes about 8 minutes to reach us."],
            ["Glass is not a slow-moving liquid.", "That's a myth."],
            ["A teaspoon of a black hole's pull", "would end the teaspoon."],
        ],
        "bodies": [
            ["It's called the Mpemba effect.", "Under certain conditions hot water", "can freeze faster than cold."],
            ["Sunlight travels about 300,000 km per second.", "The Sun is 150 million km away,", "so its light is roughly 8 minutes old."],
            ["Old window glass is thicker at the bottom", "because of how it was made,", "not because it flowed over centuries."],
            ["Black holes have immense gravity.", "Nothing that falls in escapes,", "not even light itself."],
        ],
        "closers": [
            ["Follow — one physics fact daily.", "Reality is stranger than fiction."],
            ["Share with a curious friend.", "See you tomorrow."],
            ["Comment a fact that broke your brain.", "Let's compare."],
            ["Physics is full of surprises.", "Follow for more."],
        ],
    },
    "geography": {
        "keywords": ["geography", "earth", "country", "ocean", "mountain", "world", "map"],
        "hooks": [
            ["Russia spans", "eleven time zones."],
            ["Africa is far bigger", "than most maps make it look."],
            ["The Pacific Ocean is so wide", "it holds every continent's landmass."],
            ["Mount Everest isn't", "the tallest mountain from base to peak."],
        ],
        "bodies": [
            ["From its west to its east,", "Russia crosses eleven time zones —", "more than any other country."],
            ["Flat maps stretch the poles.", "Africa can fit the US, China,", "India and much of Europe inside it."],
            ["The Pacific covers about a third of Earth.", "It's so vast that all the continents", "could fit within its area."],
            ["Everest is highest above sea level.", "But Mauna Kea, measured from its ocean base,", "is actually taller overall."],
        ],
        "closers": [
            ["Follow — one Earth fact daily.", "Our planet keeps surprising us."],
            ["Share with a map lover.", "See you tomorrow."],
            ["Comment a place fact you know.", "Let's compare."],
            ["The world is bigger than it looks.", "Follow for more."],
        ],
    },
    "ocean": {
        "keywords": ["ocean", "sea", "deep", "water", "marine", "underwater", "didyouknow"],
        "hooks": [
            ["We have better maps of Mars", "than of our own ocean floor."],
            ["Drop Everest into the deepest trench", "and it still wouldn't reach the top."],
            ["More than half the oxygen you breathe", "doesn't come from trees."],
            ["There are more shipwrecks underwater", "than objects in the world's museums."],
        ],
        "bodies": [
            ["Orbiters photographed all of Mars in detail.", "Most of our seafloor is mapped only roughly,",
             "because water blocks the same instruments."],
            ["The Mariana Trench runs about 11 kilometres down.", "Everest stands under 9 above sea level,",
             "leaving two kilometres of water above the peak."],
            ["Ocean plankton produce it by photosynthesis.", "Estimates put their share at half or more",
             "of all the oxygen on Earth."],
            ["UNESCO estimates roughly three million wrecks", "still lie on the seabed worldwide,",
             "most of them never surveyed."],
        ],
        "closers": [
            ["Follow — one ocean fact daily.", "The deep is barely explored."],
            ["Share with someone who loves the sea.", "See you tomorrow."],
            ["Comment an ocean fact you know.", "Let's compare."],
            ["We know the sky better than the sea.", "Follow for more."],
        ],
    },
    "sleep": {
        "keywords": ["sleep", "dream", "dreams", "night", "rest", "brain", "didyouknow"],
        "hooks": [
            ["You are taller in the morning", "than you are tonight."],
            ["Dolphins never fully fall asleep.", "Half their brain stays awake."],
            ["You cannot sneeze", "while you're dreaming."],
            ["Giraffes sleep less in a day", "than you do in a nap."],
        ],
        "bodies": [
            ["The discs in your spine hold fluid.", "Standing all day slowly compresses them,",
             "and a night lying down restores it."],
            ["One half sleeps while the other watches.", "It keeps them surfacing for air",
             "and alert for predators — all night."],
            ["In REM sleep the body is paralysed.", "The nerves that trigger a sneeze",
             "are switched off along with everything else."],
            ["Wild giraffes average only a few hours,", "often in short bursts of minutes,",
             "because lying down makes them vulnerable."],
        ],
        "closers": [
            ["Follow — one sleep fact daily.", "Your body is stranger at night."],
            ["Share with someone who never sleeps.", "See you tomorrow."],
            ["Comment a sleep fact you know.", "Let's compare."],
            ["Sleep is weirder than being awake.", "Follow for more."],
        ],
    },
    "food": {
        "keywords": ["food", "eat", "fruit", "cooking", "kitchen", "taste", "didyouknow"],
        "hooks": [
            ["Nutmeg was once worth", "more than its weight in gold."],
            ["A banana is a berry.", "A strawberry is not."],
            ["Carrots used to be purple.", "Orange was invented later."],
            ["Peanuts are not nuts.", "They grow underground."],
        ],
        "bodies": [
            ["It grew on a few tiny Indonesian islands.", "European powers fought wars over control of it,",
             "and traders guarded the route for centuries."],
            ["Botanically, a berry grows from one flower", "with seeds inside the flesh — that's a banana.",
             "A strawberry's seeds sit on the outside."],
            ["Early cultivated carrots were purple and yellow.", "Orange varieties were bred in Europe",
             "and only later became the standard."],
            ["Peanuts are legumes, like peas and beans.", "They flower above ground,",
             "then push their pods down into the soil."],
        ],
        "closers": [
            ["Follow — one food fact daily.", "Your kitchen is full of surprises."],
            ["Share with someone who loves food.", "See you tomorrow."],
            ["Comment a food fact you know.", "Let's compare."],
            ["Nothing on your plate is simple.", "Follow for more."],
        ],
    },
    "technology": {
        "keywords": ["technology", "computer", "internet", "invention", "engineering", "didyouknow"],
        "hooks": [
            ["The computer that landed Apollo 11", "was weaker than your phone charger."],
            ["The first computer bug", "was an actual insect."],
            ["The world's first webcam", "was pointed at a coffee pot."],
            ["The @ symbol is far older", "than email."],
        ],
        "bodies": [
            ["Its guidance computer held a few kilobytes.", "Modern phones carry millions of times more,",
             "and it still flew people to the Moon."],
            ["In 1947 a moth was found in a relay", "of the Harvard Mark II computer.",
             "The team taped it into the logbook."],
            ["Cambridge researchers aimed a camera at it", "so nobody would walk to an empty pot.",
             "That feed went online in the early 1990s."],
            ["Merchants used it for centuries", "to mean 'at the rate of' in ledgers.",
             "Email borrowed a symbol nobody else wanted."],
        ],
        "closers": [
            ["Follow — one tech fact daily.", "Progress is stranger than it looks."],
            ["Share with someone who loves gadgets.", "See you tomorrow."],
            ["Comment a tech fact you know.", "Let's compare."],
            ["Every invention has a weird origin.", "Follow for more."],
        ],
    },
    "weather": {
        "keywords": ["weather", "storm", "lightning", "rain", "snow", "climate", "didyouknow"],
        "hooks": [
            ["Lightning is hotter", "than the surface of the sun."],
            ["Raindrops are not teardrop shaped.", "That drawing is a lie."],
            ["Snow can be pink", "and it's alive."],
            ["It really can be too cold", "to snow."],
        ],
        "bodies": [
            ["A bolt can reach about 30,000 kelvin.", "The sun's visible surface is near 5,500,",
             "so lightning briefly runs five times hotter."],
            ["Small drops are almost perfect spheres.", "Bigger ones flatten as they fall,",
             "ending up more like a hamburger bun."],
            ["Cold-loving algae grow in old snowfields.", "Their pigment tints the surface pink,",
             "which is why hikers call it watermelon snow."],
            ["Snow needs moisture in the air.", "Extremely cold air holds almost none,",
             "so the heaviest snow falls near freezing."],
        ],
        "closers": [
            ["Follow — one weather fact daily.", "The sky is stranger than it looks."],
            ["Share with someone who watches storms.", "See you tomorrow."],
            ["Comment a weather fact you know.", "Let's compare."],
            ["Look up more often.", "Follow for more."],
        ],
    },
    "psychology": {
        "keywords": ["psychology", "mind", "memory", "perception", "thinking", "brain", "didyouknow"],
        "hooks": [
            ["Your brain deletes your nose", "from everything you see."],
            ["You cannot tickle yourself.", "Your brain won't allow it."],
            ["Your brain feels no pain.", "It has no receptors for it."],
            ["Your brain burns a fifth of your energy", "while sitting perfectly still."],
        ],
        "bodies": [
            ["Your nose is always in your vision.", "The brain treats it as constant and useless,",
             "so it edits it out of what you notice."],
            ["The cerebellum predicts your own movements.", "It cancels the sensation before it lands,",
             "which is why surprise is required."],
            ["Surgeons can operate on a waking patient.", "The brain registers pain from elsewhere,",
             "but feels nothing done to itself."],
            ["It's about two percent of your body weight.", "Yet it consumes roughly twenty percent",
             "of the calories you burn each day."],
        ],
        "closers": [
            ["Follow — one mind fact daily.", "Your brain hides things from you."],
            ["Share with someone who overthinks.", "See you tomorrow."],
            ["Comment a mind fact you know.", "Let's compare."],
            ["You don't see reality — you see a model.", "Follow for more."],
        ],
    },
}


# Registry: niche -> bank. set_channel() picks the active one.
BANKS = {
    "motivation": MOTIVATION_BANK,
    "everyday-english": EDUCATION_BANK,
    "did-you-know-facts": FACTS_BANK,
}

# In these niches each hook is a MATCHED PAIR with the body at the same index
# (a fact -> its own explanation, a tip -> its own detail). They must NOT be
# cross-combined, or you get "hot water freezes faster… black holes have gravity"
# mashups. Motivation lines ARE interchangeable, so it stays fully combinatorial.
ATOMIC_NICHES = {"everyday-english", "did-you-know-facts"}


def bank_for(niche):
    return BANKS.get(niche, MOTIVATION_BANK)


# Active bank (module-level so existing helpers keep working). Defaults to motivation.
BANK = bank_for(_NICHE)


def set_channel(channel):
    """Point CONTENT/STATE/TRENDS/LIBRARY and the active BANK at `channel`'s files."""
    global CONTENT, STATE, TRENDS, LIBRARY, CONFIG, BANK, _NICHE
    P = _paths.paths(channel)
    CONTENT, STATE, TRENDS = P["content"], P["state"], P["trends"]
    LIBRARY = P["library"]
    CONFIG = P["config"]
    _NICHE = _paths.channel_meta(channel).get("niche", "motivation")
    BANK = bank_for(_NICHE)


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ------------------------------------------------- learning from your own numbers
# A video needs a few days before its view count means anything; scoring one that
# went up last night would just rank "newest" instead of "best".
PERF_MIN_AGE_DAYS = 3
PERF_MAX_BOOST = 2.5      # a proven theme is picked more, never exclusively
PERF_MIN_FLOOR = 0.4      # a weak theme keeps being tried — see the note below


def theme_rates():
    """{theme: [views-per-day, ...]} from this channel's own published videos.

    Views-per-day, not views: a video from last week has had a week to collect
    them, and comparing raw totals just tells you which video is oldest. Only
    entries with a real video_id count — those are the ones confirmed to have
    actually reached YouTube.
    """
    lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}
    today = date.today()
    rates = {}
    for v in (lib.get("videos") or {}).values():
        if v.get("status") != "uploaded" or not v.get("video_id"):
            continue
        theme = (v.get("theme") or "").strip()
        if theme not in BANK:
            continue
        stamp = str(v.get("uploaded_at") or v.get("created") or "")[:10]
        try:
            age = (today - date.fromisoformat(stamp)).days
        except ValueError:
            continue
        if age < PERF_MIN_AGE_DAYS:
            continue
        try:
            views = float(v.get("views") or 0)
        except (TypeError, ValueError):
            continue
        rates.setdefault(theme, []).append(views / age)
    return rates


def performance_weights():
    """Multiplier per theme: how well it actually did on THIS channel.

    Three deliberate limits, because a naive "make more of what won" collapses a
    channel onto one idea and then decays:
      * small samples are shrunk toward 1.0, so a single lucky video cannot take
        over the schedule (1 video counts a third, 4 count two thirds);
      * the median is the baseline, not the mean, so one viral video does not
        make every other theme look like a failure;
      * nothing drops below PERF_MIN_FLOOR. A theme you stop making entirely is
        a theme you can never get new data about, and audiences change.
    Returns {} when there isn't enough history yet — the caller then just uses
    trends, exactly as before.
    """
    rates = theme_rates()
    if not rates:
        return {}
    means = {t: sum(rs) / len(rs) for t, rs in rates.items()}
    # Baseline = the median THEME, not the median video. Taking the median over
    # every video lets a theme you post often sit on the midpoint and get
    # compared against itself, which reads as "average" no matter how well it
    # did. One score per theme keeps the comparison between themes.
    base = _median(list(means.values()))
    if base <= 0:
        return {}

    out = {}
    for theme, mean in means.items():
        confidence = len(rates[theme]) / (len(rates[theme]) + 2.0)
        mult = 1.0 + confidence * ((mean / base) - 1.0)
        out[theme] = max(PERF_MIN_FLOOR, min(PERF_MAX_BOOST, mult))
    return out


def _median(nums):
    s = sorted(nums)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def theme_weights():
    """Weight themes by what's trending AND by what has worked on this channel."""
    weights = {t: 1.0 for t in BANK}
    trends = load(TRENDS, None)
    if trends:
        hot = {w for w, _ in trends.get("hook_words", [])}
        hot |= {t.lstrip("#") for t, _ in trends.get("hashtags", [])}
        for theme, spec in BANK.items():
            hits = sum(1 for k in spec["keywords"] if k in hot)
            weights[theme] += hits * 1.5
    # Trends say what the internet likes; this says what YOUR audience clicked.
    # Applied last and multiplicatively so it re-ranks the trend scores instead
    # of drowning them.
    perf = performance_weights()
    for theme in weights:
        weights[theme] *= perf.get(theme, 1.0)
    # A flagship series has to actually dominate the upload schedule, or it
    # isn't a series — it's an occasional theme, and there's no reason to
    # subscribe for the next one. Trends and performance still re-rank
    # everything; this just sets the starting line. Config, not a constant, so
    # it can be retuned or dropped to 1.0 without touching code.
    for theme, bias in (load(CONFIG, {}) or {}).get("theme_bias", {}).items():
        if theme in weights:
            weights[theme] *= float(bias)
    return weights


def hook_key(theme, h):
    return f"{theme}:h{h}"


def _fit_runtime(hooks, bodies, closers):
    """Trim a script to the target line count, cutting from the middle only.

    hooks + bodies + closers is 7 lines, which renders at ~25s. The trend scan
    puts the median winning Short at 18s, and a Short that outlasts its
    audience is one people swipe out of — which the algorithm reads as a worse
    signal than a shorter video watched to the end.

    What gets cut matters as much as how much. The hook is the first two
    seconds and decides whether anyone stays, so it is never touched. One
    closer line survives because that is the engagement ask, and this channel's
    weak spot is conversion (4.1 subscribers per 1,000 views) — buying runtime
    by deleting the call to action would trade the wrong thing. So the body
    gives up the lines.

    Set "short_max_lines" in a channel's config.json to override; 0 disables.
    """
    cfg = load(CONFIG, {}) or {}
    budget = cfg.get("short_max_lines", 5)
    full = list(hooks) + list(bodies) + list(closers)
    if not budget or budget >= len(full):
        return full
    keep_hook = list(hooks)[:max(1, budget - 2)]
    keep_close = list(closers)[:1] if budget > len(keep_hook) else []
    room = max(0, budget - len(keep_hook) - len(keep_close))
    return keep_hook + list(bodies)[:room] + keep_close


def _bank_parts(item):
    """(hooks, FULL body, closers) for a script, or None if it isn't from the bank.

    Rebuilds from the bank rather than reading the stored lines, so refitting is
    idempotent and — crucially — reversible. A previous run trimmed the body in
    place, which meant raising a channel's budget later could not restore the
    lines it had already cut. Facts needed exactly that: its own trend scan puts
    the winning length at 36s, well above the 18s that set the first budget.
    """
    spec = BANK.get(item.get("theme"))
    if not spec:
        return None
    lines = item["lines"]
    hooks = next((h for h in spec["hooks"] if list(h) == lines[:len(h)]), None)
    if not hooks:
        return None
    # The closer may have been cut to its first line, so match on that.
    closers = next((c for c in spec["closers"]
                    if list(c) == lines[-len(c):] or c[0] == lines[-1]), None)
    if not closers:
        return None
    kept_body = lines[len(hooks):len(lines) - 1] \
        if list(closers) != lines[-len(closers):] \
        else lines[len(hooks):len(lines) - len(closers)]
    # Recover the FULL body: the stored one may be a prefix of a bank body.
    body = next((b for b in spec["bodies"]
                 if list(b)[:len(kept_body)] == kept_body), kept_body)
    return hooks, body, closers


def refit_unused():
    """Apply the runtime budget to scripts composed before it existed.

    _fit_runtime only runs at compose time, so every script already sitting in
    content.json keeps its original seven lines and keeps rendering at ~25s.
    That is weeks of backlog on each channel.

    The split is recovered by matching against the bank rather than assuming
    fixed offsets: the head of the script is one of the theme's hooks and the
    tail is one of its closers, so whatever sits between them is the body.
    Scripts already built are left alone — re-cutting a published video's
    script would make the library disagree with what is actually on YouTube.
    """
    content = load(CONTENT, {"items": []})
    state = load(STATE, {})
    used = set(state.get("used_ids", []))
    changed = 0
    for item in content.get("items", []):
        if item["id"] in used:
            continue
        parts = _bank_parts(item)
        if not parts:
            continue                    # unrecognised shape — leave it be
        hooks, body, closers = parts
        refit = _fit_runtime(hooks, body, closers)
        if refit != item["lines"]:
            item["lines"] = refit
            changed += 1
    if changed:
        save(CONTENT, content)
    return changed


def hooks_from_combos(used_combos):
    """Recover which hooks a channel has already published, from the older
    used_combos ledger (keys look like 'theme:hbc', one digit per slot)."""
    out = set()
    for key in used_combos:
        theme, _, digits = key.rpartition(":")
        if theme and len(digits) == 3 and digits.isdigit():
            out.add(hook_key(theme, int(digits[0])))
    return out


def hook_text(theme, h):
    """The headline a hook produces, normalised for comparison."""
    return " ".join(BANK[theme]["hooks"][h]).strip().lower()


def spoken_hooks(used_hooks):
    """The headline TEXT behind each used hook key.

    used_hooks stores 'theme:hN', so two themes that happen to contain the same
    hook are two different keys and both could be published — which is how
    education carried "One word that replaces ten boring ones" in both its
    vocabulary and connectors themes. The ledger has to compare what the viewer
    actually sees, not the slot it came from.
    """
    out = set()
    for key in used_hooks:
        theme, _, idx = key.rpartition(":h")
        if theme in BANK and idx.isdigit() and int(idx) < len(BANK[theme]["hooks"]):
            out.add(hook_text(theme, int(idx)))
    return out


def remaining_combos(used, used_hooks=()):
    atomic = _NICHE in ATOMIC_NICHES
    out = []
    spoken = spoken_hooks(used_hooks)
    claimed = {}          # headline text -> the one (theme, h) allowed to use it
    for theme, spec in BANK.items():
        for h in range(len(spec["hooks"])):
            txt = hook_text(theme, h)
            if txt in spoken:
                continue          # this exact headline is already published
            owner = claimed.setdefault(txt, (theme, h))
            if owner != (theme, h):
                continue          # a different theme already offers this headline
            # The hook is the first spoken line AND becomes the video title, so
            # reusing one ships a near-identical video: same headline, same
            # opening. used_combos only blocked the exact hook+body+closer
            # triple, which let a fresh combo repeat an old hook — that is how
            # "Doubt has killed more dreams" and "You don't need perfect
            # grammar" got queued a second time behind videos already live.
            if hook_key(theme, h) in used_hooks:
                continue
            for b in range(len(spec["bodies"])):
                # facts/tips: the hook and its explanation are one unit — only
                # pair body[i] with hook[i], never mix two different facts.
                if atomic and h != b:
                    continue
                for c in range(len(spec["closers"])):
                    key = f"{theme}:{h}{b}{c}"
                    if key not in used:
                        out.append((theme, h, b, c, key))
    return out


def compose(n, prefer=None):
    content = load(CONTENT, {"items": []})
    state = load(STATE, {})
    used = set(state.get("used_combos", []))
    # Backfill on first run so hooks published before this rule existed still
    # count as used — otherwise the very next compose could repeat one.
    used_hooks = set(state.get("used_hooks") or hooks_from_combos(used))

    pool = remaining_combos(used, used_hooks)
    if not pool:
        raise SystemExit(
            f"Out of fresh hooks for this channel ({len(used_hooks)} used). "
            f"Every remaining combo would repeat a headline that is already "
            f"published. Add new hooks to the bank in script_composer.py.")

    weights = theme_weights()
    if prefer and prefer in weights:
        weights[prefer] += 10   # the pilot's chosen topic wins the pick
    random.shuffle(pool)
    pool.sort(key=lambda x: -weights[x[0]] * random.random())

    # Ids must dodge everything this channel has EVER used, not just what is in
    # content.json right now. A published script that gets pruned out of the
    # bank still owns its id: used_ids, the calendar and the library all key on
    # it, so handing the same id to a new script silently points them at the
    # wrong video.
    existing = {it["id"] for it in content["items"]}
    existing |= set(state.get("used_ids", []))

    def next_id():
        """Lowest free id — re-checked per allocation, not once per batch."""
        n = 1
        while f"c{n:03d}" in existing:
            n += 1
        return f"c{n:03d}"

    added = []
    themes_used = []
    batch_parts = set()   # (theme, part-kind, index) already used in this batch

    # Re-scan from the front for every pick rather than making one forward pass.
    #
    # The pool is sorted by weight, so a heavily-weighted theme occupies one
    # contiguous block at the head of the list. Under a single pass the
    # "no 3 in a row" rule below would skip that entire block after two picks
    # and the cursor would never return to it — capping the top theme at 2 per
    # batch no matter how it was weighted. Weighting a theme up made the block
    # tighter, which made the problem worse, not better.
    remaining = list(pool)
    while len(added) < n:
        chosen = None
        for pos, cand in enumerate(remaining):
            theme, h, b, c, key = cand
            # avoid 3 of the same theme in a row for variety
            if themes_used[-2:] == [theme, theme]:
                continue
            # avoid repeating any hook/body/closer within one batch
            parts = {(theme, "h", h), (theme, "b", b), (theme, "c", c)}
            if parts & batch_parts:
                continue
            if hook_key(theme, h) in used_hooks:
                continue             # claimed earlier in this same batch
            chosen = (pos, cand, parts)
            break
        if chosen is None:
            break                    # nothing eligible left
        pos, (theme, h, b, c, key), parts = chosen
        remaining.pop(pos)
        batch_parts |= parts
        used_hooks.add(hook_key(theme, h))
        spec = BANK[theme]
        lines = _fit_runtime(spec["hooks"][h], spec["bodies"][b], spec["closers"][c])
        item = {"id": next_id(), "theme": theme, "lines": lines}
        content["items"].append(item)
        added.append(item)
        used.add(key)
        themes_used.append(theme)
        existing.add(item["id"])

    state["used_combos"] = sorted(used)
    state["used_hooks"] = sorted(used_hooks)
    save(CONTENT, content)
    save(STATE, state)
    return added


def unused_count():
    content = load(CONTENT, {"items": []})
    state = load(STATE, {})
    used_ids = set(state.get("used_ids", []))
    return sum(1 for it in content["items"] if it["id"] not in used_ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", type=int, help="top up so this many unused scripts exist")
    ap.add_argument("--add", type=int, help="force-add this many new scripts")
    ap.add_argument("--stats", action="store_true")
    _paths.add_channel_arg(ap)
    args = ap.parse_args()
    set_channel(args.channel)

    if args.stats:
        state = load(STATE, {})
        combos = set(state.get("used_combos", []))
        hooks = set(state.get("used_hooks") or hooks_from_combos(combos))
        pool = remaining_combos(combos, hooks)
        print(f"Unused scripts in content.json : {unused_count()}")
        print(f"Fresh combos still available   : {len(pool)}")
        print(f"Unused headlines (hard limit)  : "
              f"{len({(c[0], c[1]) for c in pool})} — one video each")
        perf = performance_weights()
        if perf:
            rates = theme_rates()
            print("\nWhat this channel's own numbers say (views/day, "
                  f"videos {PERF_MIN_AGE_DAYS}+ days old):")
            for theme, mult in sorted(perf.items(), key=lambda kv: -kv[1]):
                rs = rates[theme]
                arrow = "↑ more of this" if mult > 1.05 else (
                    "↓ less of this" if mult < 0.95 else "· neutral")
                print(f"  {theme:14} {sum(rs)/len(rs):6.1f} v/day  "
                      f"n={len(rs)}  x{mult:.2f}  {arrow}")
        else:
            print(f"\nNo performance signal yet — needs videos {PERF_MIN_AGE_DAYS}+ "
                  f"days old with view counts synced. Until then themes are "
                  f"picked on trends alone.")
        w = theme_weights()
        best = sorted(w.items(), key=lambda kv: -kv[1])[:3]
        print("Most likely themes next        : "
              + ", ".join(f"{t} ({v:.2f})" for t, v in best))
        return

    if args.add:
        added = compose(args.add)
    elif args.ensure is not None:
        have = unused_count()
        need = max(0, args.ensure - have)
        added = compose(need) if need else []
        print(f"Had {have} unused; needed {args.ensure}.")
    else:
        ap.print_help()
        return

    for it in added:
        print(f"  + {it['id']} [{it['theme']}] {it['lines'][0]}")
    print(f"Added {len(added)} script(s).")


if __name__ == "__main__":
    main()
