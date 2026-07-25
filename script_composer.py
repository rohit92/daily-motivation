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
            ["One word", "that replaces ten boring ones."],
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
    "confidence": {
        "keywords": ["confidence", "speaking", "hesitate", "fear", "practice", "mindset"],
        "hooks": [
            ["Afraid to speak English?", "This mindset changes everything."],
            ["You don't need perfect grammar.", "You need to be understood."],
            ["Stop translating in your head.", "Here's what to do instead."],
            ["Fluency isn't speed.", "It's not stopping."],
        ],
        "bodies": [
            ["Mistakes are proof you're trying.", "Every fluent speaker made thousands.", "Speak now, polish later."],
            ["Think in simple English first.", "Short clear sentences win.", "Complexity comes with time."],
            ["Nobody is judging your accent.", "They're listening to your idea.", "Say it and keep going."],
            ["Learn phrases, not just words.", "Whole chunks come out faster.", "That's how natural speech feels."],
        ],
        "closers": [
            ["Speak one English sentence today.", "Out loud, to anyone."],
            ["Progress beats perfection.", "Start messy, get better."],
            ["Follow for daily confidence.", "You're closer than you think."],
            ["Say it before you feel ready.", "Ready comes from doing."],
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
            ["Cleopatra lived closer to us", "than to the pyramids' builders."],
        ],
        "bodies": [
            ["Bacteria can't grow in honey.", "Very low water, high acidity —", "sealed honey lasts millennia."],
            ["Teaching at Oxford began by 1096.", "The Aztec capital was founded in 1325.", "The gap is over two centuries."],
            ["The Great Pyramid was built around 2560 BC.", "Cleopatra was born in 69 BC.", "That's about 2,500 years apart."],
            ["The pyramids rose around 2560 BC.", "Cleopatra lived around 30 BC.", "The Moon landing was 1969 AD."],
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
    global CONTENT, STATE, TRENDS, LIBRARY, BANK, _NICHE
    P = _paths.paths(channel)
    CONTENT, STATE, TRENDS = P["content"], P["state"], P["trends"]
    LIBRARY = P["library"]
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
    return weights


def hook_key(theme, h):
    return f"{theme}:h{h}"


def hooks_from_combos(used_combos):
    """Recover which hooks a channel has already published, from the older
    used_combos ledger (keys look like 'theme:hbc', one digit per slot)."""
    out = set()
    for key in used_combos:
        theme, _, digits = key.rpartition(":")
        if theme and len(digits) == 3 and digits.isdigit():
            out.add(hook_key(theme, int(digits[0])))
    return out


def remaining_combos(used, used_hooks=()):
    atomic = _NICHE in ATOMIC_NICHES
    out = []
    for theme, spec in BANK.items():
        for h in range(len(spec["hooks"])):
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

    existing = {it["id"] for it in content["items"]}
    seq = 1
    while f"c{seq:03d}" in existing:
        seq += 1

    added = []
    themes_used = []
    batch_parts = set()   # (theme, part-kind, index) already used in this batch
    for theme, h, b, c, key in pool:
        if len(added) >= n:
            break
        # avoid 3 of the same theme in a row for variety
        if themes_used[-2:] == [theme, theme]:
            continue
        # avoid repeating any hook/body/closer within one batch
        parts = {(theme, "h", h), (theme, "b", b), (theme, "c", c)}
        if parts & batch_parts:
            continue
        if hook_key(theme, h) in used_hooks:
            continue                 # claimed earlier in this same batch
        batch_parts |= parts
        used_hooks.add(hook_key(theme, h))
        spec = BANK[theme]
        lines = spec["hooks"][h] + spec["bodies"][b] + spec["closers"][c]
        item = {"id": f"c{seq:03d}", "theme": theme, "lines": lines}
        content["items"].append(item)
        added.append(item)
        used.add(key)
        themes_used.append(theme)
        existing.add(item["id"])
        seq += 1

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
