"""Static content written for NeuroBridge: default cards, blueprint sections, sensory
strategies, routine templates, learning-hub topics, starter community groups.

Learning-hub text is original, short and general ("general suggestion", not evidence).
Each topic links to organisation pages for deeper, sourced reading; links point to
organisation pages, not invented article URLs — re-check them periodically.
"""

DEFAULT_CARDS = [
    ("I need a break.", "Needs", "⏸"), ("Please give me time.", "Needs", "⏳"),
    ("I can't explain right now.", "Communication", "💬"),
    ("Please speak slowly.", "Communication", "🐢"), ("I need help.", "Needs", "🙋"),
    ("I need quiet.", "Sensory", "🤫"), ("I need food or water.", "Needs", "🥤"),
    ("I feel overwhelmed.", "Feelings", "🌊"), ("Please don't touch me.", "Sensory", "✋"),
    ("I need to leave.", "Needs", "🚪"),
    ("I want to say something but don't know how.", "Communication", "✏️"),
    ("Yes", "Quick answers", "✅"), ("No", "Quick answers", "❌"),
    ("Not now, maybe later.", "Quick answers", "🕒"),
]

BLUEPRINT_SECTIONS = [
    ("communicate", "How I communicate"), ("helps", "What helps me"),
    ("doesnt_help", "What doesn't help me"), ("sensory", "Sensory preferences"),
    ("overwhelms", "Things that overwhelm me"), ("early_signs", "Early signs I need support"),
    ("respond", "How I prefer people to respond"), ("strengths", "My strengths"),
    ("interests", "My interests"), ("boundaries", "My boundaries"), ("goals", "My goals"),
    ("environment", "My preferred environment"), ("support", "My support preferences"),
]
BLUEPRINT_KEYS = {k for k, _ in BLUEPRINT_SECTIONS}

SENSORY_STRATEGIES = [
    {"key": "headphones", "title": "Noise-cancelling headphones or ear defenders",
     "group": "Sound", "how": "Put them on before a noisy place, not only once it is too much."},
    {"key": "brown_noise", "title": "Steady background sound", "group": "Sound",
     "how": "Brown noise, rain or a fan can cover sudden sounds."},
    {"key": "dim_lights", "title": "Dim or warm lights", "group": "Light",
     "how": "Switch off overhead lights, use a lamp, or wear a cap or tinted glasses."},
    {"key": "screen_dark", "title": "Dark mode and lower brightness", "group": "Light",
     "how": "Turn on Low-stimulation mode in NeuroBridge settings."},
    {"key": "heavy_blanket", "title": "Deep pressure", "group": "Touch",
     "how": "A heavy blanket, a firm hug from someone you trust, or pressing your palms together."},
    {"key": "soft_texture", "title": "A comfortable texture to hold", "group": "Touch",
     "how": "A soft fabric, smooth stone or a fidget you like."},
    {"key": "movement", "title": "Movement", "group": "Movement",
     "how": "Walk, rock, sway, bounce, pace — whatever your body wants."},
    {"key": "stim", "title": "Stimming freely", "group": "Movement",
     "how": "Stimming is a valid way to regulate. Find a space where you can do it comfortably."},
    {"key": "senses_54321", "title": "Name what you notice", "group": "Grounding",
     "how": "Name a few things you can see, hear and feel. Any number is fine."},
    {"key": "counting", "title": "Count something", "group": "Grounding",
     "how": "Count tiles, books, or your steps. Slowly, with no goal."},
    {"key": "special_interest", "title": "Your favourite interest", "group": "Grounding",
     "how": "Think about, read or watch something you love for a few minutes."},
    {"key": "music", "title": "Familiar music", "group": "Sound",
     "how": "A song you know well, at a volume that feels right."},
    {"key": "breathing", "title": "Slow breathing (optional)", "group": "Breathing",
     "how": "Breathe out a little longer than you breathe in. Breathing exercises don't suit "
            "everyone — skip this if it makes things worse."},
    {"key": "chewy", "title": "Something to chew or crunch", "group": "Taste",
     "how": "Chewing gum, a crunchy snack, or a chew tool."},
    {"key": "quiet_space", "title": "Go to a quieter space", "group": "Space",
     "how": "A bathroom, car, stairwell or empty room. It's OK to leave."},
]
SENSORY_KEYS = {s["key"] for s in SENSORY_STRATEGIES}
DEFAULT_KIT = ["Headphones / earplugs", "Sunglasses or cap", "Water bottle", "Snack",
               "Fidget or comfort item", "Communication card", "Phone charger"]

ROUTINE_TEMPLATES = {
    "morning": ("Morning", [("Drink some water", 1), ("Wash face", 3), ("Get dressed", 10),
                            ("Eat something", 15), ("Check today's plan", 2)]),
    "evening": ("Evening", [("Lay out tomorrow's clothes", 5), ("Brush teeth", 3),
                            ("Screens off or dimmed", 1), ("Something calming", 15)]),
    "hygiene": ("Shower", [("Get towel and clothes ready", 2), ("Water to a comfortable "
                                                               "temperature", 1),
                           ("Wash hair (optional today)", 5), ("Wash body", 5), ("Dry and dress", 8)]),
    "leaving": ("Leaving home", [("Keys", 1), ("Phone and charger", 1), ("Wallet / pass", 1),
                                 ("Headphones", 1), ("Water", 1), ("Check where I'm going", 2)]),
    "study": ("Study block", [("Clear the desk a little", 3), ("Pick ONE thing to work on", 1),
                              ("Work for 20 minutes", 20), ("Break: move or drink water", 5)]),
    "work": ("Work start", [("Check messages (5 min limit)", 5), ("Pick top 1–3 tasks", 3),
                            ("Start the easiest one", 15)]),
}

LEARNING_TOPICS = [
    {"slug": "neurodiversity", "title": "Neurodiversity basics",
     "summary": "Neurodiversity means brains naturally differ. Autism, ADHD, dyslexia and "
                "dyspraxia are differences in how people think, sense and learn — with real "
                "strengths and real challenges. Support works best when it fits the person, "
                "rather than trying to make them seem 'typical'.",
     "links": [("National Autistic Society", "https://www.autism.org.uk/"),
               ("Autistic Self Advocacy Network", "https://autisticadvocacy.org/")]},
    {"slug": "autism", "title": "Autism",
     "summary": "Autistic people may communicate, socialise and process sensory input "
                "differently. Common needs include predictability, sensory adjustments, time "
                "to process and clear, literal communication. Every autistic person is different.",
     "links": [("NHS — Autism", "https://www.nhs.uk/conditions/autism/"),
               ("CDC — Autism", "https://www.cdc.gov/autism/"),
               ("Action For Autism (India)", "https://www.actionforautism.org/")]},
    {"slug": "adhd", "title": "ADHD",
     "summary": "ADHD affects attention regulation, activity level and impulse control. Many "
                "people find external structure helps: visible reminders, small steps, body "
                "doubling and movement breaks. Diagnosis and treatment decisions belong with a "
                "qualified clinician.",
     "links": [("NHS — ADHD", "https://www.nhs.uk/conditions/attention-deficit-hyperactivity-disorder-adhd/"),
               ("CDC — ADHD", "https://www.cdc.gov/adhd/")]},
    {"slug": "dyslexia", "title": "Dyslexia and dyspraxia",
     "summary": "Dyslexia mainly affects reading and spelling; dyspraxia affects movement and "
                "coordination and often planning. Text-to-speech, extra time, clear layouts and "
                "step-by-step instructions help many people.",
     "links": [("British Dyslexia Association", "https://www.bdadyslexia.org.uk/"),
               ("Dyspraxia Foundation", "https://dyspraxiafoundation.org.uk/")]},
    {"slug": "sensory", "title": "Sensory needs",
     "summary": "People can be over- or under-sensitive to sound, light, touch, smell, taste "
                "and movement. Changing the environment (quieter, dimmer, fewer people) usually "
                "works better than asking someone to tolerate it.",
     "links": [("National Autistic Society — sensory differences", "https://www.autism.org.uk/")]},
    {"slug": "executive-function", "title": "Executive function",
     "summary": "Executive function covers starting, planning, remembering and switching. "
                "Difficulty here is not laziness. Helpful supports: one tiny first step, visible "
                "timers, checklists, fewer choices, and doing tasks alongside someone.",
     "links": [("Understood", "https://www.understood.org/")]},
    {"slug": "communication", "title": "Communication",
     "summary": "Communication can be spoken, written, typed, signed, using cards or AAC. "
                "Give time to respond, ask one question at a time, and accept non-speaking "
                "communication as real communication.",
     "links": [("Autistic Self Advocacy Network", "https://autisticadvocacy.org/")]},
    {"slug": "transitions", "title": "Transitions",
     "summary": "Changing activity can be hard. Warnings before a change, visual schedules, "
                "a 'first this, then that' plan and a transition object can help.",
     "links": [("National Autistic Society", "https://www.autism.org.uk/")]},
    {"slug": "meltdowns", "title": "Shutdowns and meltdowns",
     "summary": "Meltdowns and shutdowns are responses to overload, not bad behaviour. Reduce "
                "demands and sensory input, keep words few, keep everyone safe, and talk later "
                "if the person wants. If anyone is in danger, call 112.",
     "links": [("National Autistic Society", "https://www.autism.org.uk/")]},
    {"slug": "burnout", "title": "Burnout",
     "summary": "Autistic and ADHD burnout can follow long periods of masking and overload. "
                "It often needs real rest and reduced demands, not more effort. If low mood or "
                "thoughts of self-harm appear, contact a professional or Tele-MANAS (14416).",
     "links": [("Tele-MANAS (India)", "https://telemanas.mohfw.gov.in/"),
               ("Mind", "https://www.mind.org.uk/")]},
    {"slug": "independence", "title": "Independence and self-advocacy",
     "summary": "Independence includes choosing your own support. Self-advocacy means knowing "
                "and saying what you need. Supporters can help by offering choices and "
                "practising, rather than deciding for the person.",
     "links": [("Autistic Self Advocacy Network", "https://autisticadvocacy.org/")]},
    {"slug": "education-work", "title": "Education and workplace support",
     "summary": "Reasonable adjustments might include quieter workspaces, written "
                "instructions, flexible hours, extra time and regular check-ins. NeuroBridge can "
                "help you draft a request — the decision is yours.",
     "links": [("Understood", "https://www.understood.org/")]},
    {"slug": "caregiver", "title": "Caring for yourself as a caregiver",
     "summary": "Caregiving is hard work, and tiredness is not failure. Sharing tasks, "
                "accepting help and getting practical support matter as much as self-care.",
     "links": [("Carers UK", "https://www.carersuk.org/")]},
]

LIFE_SKILLS = [
    ("Meal planning", "Help me plan 3 simple meals for this week with a short shopping list."),
    ("Shopping", "Help me make a shopping list and a plan for a quieter shopping trip."),
    ("Laundry", "Break doing one load of laundry into small steps."),
    ("Budgeting basics", "Explain a simple way to track money for one week."),
    ("Travel preparation", "Help me prepare for a trip on public transport tomorrow."),
    ("Appointment preparation", "Help me prepare for a doctor's appointment: what to bring "
                                "and what to say."),
    ("Decision help", "Help me think through a decision using pros and cons, step by step."),
    ("Study plan", "Help me make a revision schedule for an exam in two weeks."),
    ("Homework breakdown", "Break my homework into small steps I can start now."),
    ("Accommodation request", "Help me draft a polite email asking my workplace or college for "
                              "reasonable adjustments."),
    ("Interview preparation", "Help me prepare for a job interview, including what to say about "
                              "my needs if I choose to."),
    ("Meeting preparation", "Help me prepare notes for a meeting so I don't freeze."),
]

STARTER_GROUPS = [
    ("adhd-body-doubling", "ADHD body-doubling corner", "Plan a task, post it, check back in.",
     "adhd", "everyone", 1),
    ("autistic-adults", "Autistic adults lounge", "Peer space by and for autistic adults.",
     "autism", "adults", 0),
    ("parents-caregivers", "Parents & caregivers circle", "Share what's working and what's hard.",
     "caregiving", "caregivers", 0),
    ("sensory-tips", "Sensory tips exchange", "Headphones, textures, lighting, places that "
                                              "get it right.", "sensory", "everyone", 1),
    ("special-interests", "Special interests club", "Trains, anime, bugs, maps — share what you "
                                                     "love.", "hobbies", "everyone", 1),
    ("study-work", "Study & work strategies", "Adjustments, planning, interviews, exams.",
     "work", "everyone", 1),
    ("art-and-making", "Art & making", "Drawing, crafts, music, building.", "hobbies",
     "everyone", 1),
    ("goa-meetups", "Goa meetups (planning)", "Organise low-sensory meetups; events go through "
                                               "the Events tab.", "local", "adults", 0),
    ("hearing-voices-peer", "Hearing voices peer space", "Adults who hear voices or have unusual "
     "experiences. Peer support, not treatment; in a crisis call 112 or Tele-MANAS 14416.",
     "mental-health", "adults", 0),
    ("plural-did-space", "Plural & DID respectful space", "For people with DID/OSDD or who are "
     "plural, and those who support them. Respect each part's name and pronouns.",
     "mental-health", "adults", 0),
    ("games-puzzles-night", "Games & puzzles club", "Board games, online puzzles, low-pressure "
     "chat. Plan a games night here.", "hobbies", "everyone", 1),
    ("nature-walks", "Nature walks club", "Quiet walks, birdwatching, gardening. Share calm "
     "outdoor spots.", "hobbies", "everyone", 1),
    ("quiet-social-club", "Quiet social club", "Low-demand hangouts: parallel play, quiet "
     "coffee mornings, text-first chat.", "social", "adults", 0),
    ("carer-wellbeing", "Carer wellbeing circle", "For carers looking after themselves too. "
     "No guilt here.", "caregiving", "caregivers", 0),
]
