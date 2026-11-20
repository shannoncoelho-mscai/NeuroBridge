/* NeuroBridge UI translations.
   English is the source. Hindi covers navigation and the main actions; these strings were
   machine-assisted and NEED REVIEW by a native speaker before release, especially safety and
   health wording. Other languages fall back to English for the interface, while the AI
   assistant replies in the chosen language (see agent/middleware/language_support.py). */
window.NB_LANGS = [
  ["en", "English"], ["hi", "हिन्दी (Hindi)"], ["kok", "कोंकणी (Konkani)"], ["mr", "मराठी (Marathi)"],
  ["bn", "বাংলা (Bengali)"], ["ta", "தமிழ் (Tamil)"], ["te", "తెలుగు (Telugu)"], ["ml", "മലയാളം (Malayalam)"],
  ["kn", "ಕನ್ನಡ (Kannada)"], ["gu", "ગુજરાતી (Gujarati)"], ["pa", "ਪੰਜਾਬੀ (Punjabi)"], ["ur", "اردو (Urdu)"],
];
window.NB_RTL = ["ur"];
window.NB_STRINGS = {
  hi: {
    "My Day": "मेरा दिन", "Assistant": "सहायक", "Tasks": "काम", "Routines": "दिनचर्या",
    "Check-in": "हालचाल", "Sensory toolkit": "संवेदी साधन", "Communication": "संवाद",
    "Journal": "डायरी", "Support Blueprint": "सहायता खाका", "Goals": "लक्ष्य",
    "Learn & life skills": "सीखें और जीवन कौशल", "Community": "समुदाय", "Events & groups": "कार्यक्रम और समूह",
    "My circle": "मेरा सहायता घेरा", "Settings": "सेटिंग्स", "Dashboard": "डैशबोर्ड",
    "Care assistant": "देखभाल सहायक", "Care calendar": "देखभाल कैलेंडर", "Care journal": "देखभाल डायरी",
    "People I support": "जिनकी मैं मदद करता/करती हूँ", "Coordination": "तालमेल",
    "Support requests": "मदद के अनुरोध", "Learning hub": "सीखने का केंद्र",
    "Providers & appointments": "विशेषज्ञ और अपॉइंटमेंट", "Wellbeing": "मेरी भलाई",
    "I'm overwhelmed": "मैं बहुत परेशान हूँ", "Sign out": "साइन आउट", "Notifications": "सूचनाएँ",
    "Save": "सहेजें", "Cancel": "रद्द करें", "Add": "जोड़ें", "Delete": "हटाएँ", "Send": "भेजें",
    "Help me start": "शुरू करने में मदद", "What should I do next?": "अब मैं क्या करूँ?",
    "Today": "आज", "Plan": "योजना", "Support": "सहायता", "Me": "मैं", "Connect": "जुड़ें", "Care": "देखभाल",
    "Moderation": "मॉडरेशन",
  },
};
window.t = function (s) {
  const lang = (window.NB_LANG || "en");
  return (window.NB_STRINGS[lang] && window.NB_STRINGS[lang][s]) || s;
};
