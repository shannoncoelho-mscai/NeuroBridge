# Demo
Live site (hosted models): the agent, web search, booking, community.
Colab: the same website, with your NeuroBridge SFT+ORPO model selected in the Assistant’s model dropdown. 
## Live demo
**https://neurobridge-428948222095.asia-south1.run.app**

## Start the website in Google Colab (about 5 minutes)

1. Download this repository as a zip (**Code → Download ZIP** on GitHub) and upload it to the
   top of your Google Drive (*My Drive*).
2. Open [`RUN_NeuroBridge_Website.ipynb`](RUN_NeuroBridge_Website.ipynb) in Google Colab.
3. Click the 🔑 key icon (*Secrets*) and add, with **Notebook access** on:
   - `GROQ_API_KEY` (console.groq.com)
   - `GEMINI_API_KEY` (aistudio.google.com)
   - `TAVILY_API_KEY` (app.tavily.com, for web search)
   - `NB_ADMIN_PASSWORD` (a password of 10+ characters you choose)
4. **Runtime → Run all.** The notebook checks each key, starts the server and opens the website.
   It prints the demo account password.

Demo accounts (all clearly labelled demo):

| Account | Role |
|---|---|
| `asha@demo.neurobridge.local` | Individual |
| `ravi@demo.neurobridge.local` | Caregiver linked to Asha |
| `mod@demo.neurobridge.local` | Demo moderator (admin) |
| `admin@neurobridge.local` | Your admin account (password = `NB_ADMIN_PASSWORD`) |

## Demo walkthrough (about 8 minutes)

1. **Asha → My Day.** Energy check-in, one suggested starting task, routines. Press
   **I'm overwhelmed** to show the calm screen.
2. **Asha → Assistant.** Ask *"I have to clean my room and I can't start"* → one tiny first step.
3. **Emergency.** Ask *"my dad is choking"* → fixed first-aid steps and **call 112**, no AI.
   Then *"what foods are choking hazards for toddlers?"* → a normal answer (no false alarm).
4. **Admin → Provider directory.** Add a psychiatrist, **Verify & list** with a note on what was
   checked, add an open time.
5. **Asha → Assistant (Research & actions, tick Allow bookings).** *"Find a psychiatrist in Panaji
   who understands adult ADHD and book an appointment."* Show the cited sources, the approval
   card with the exact doctor, time and fee, then approve.
6. **Admin → Provider directory → Reserved appointments → Clinic confirmed.** Asha's
   Providers & appointments page now shows *Confirmed by the clinic*.
7. **Clinic not in the directory.** *"Book an appointment with a speech therapist in Margao"* →
   nothing booked; **Track this clinic** → *Message to send*.
8. **Ravi → People I support.** He sees only what Asha shared; change a sharing switch as Asha
   and show it disappear for Ravi.
9. **Community.** Join a group, post; a post with a phone number is held for the moderator.
10. **Model menu → Compare** (when the trained models are loaded): one message to base, SFT and
    SFT+ORPO side by side.

## Demo video

Add the link to your recorded demo here.
